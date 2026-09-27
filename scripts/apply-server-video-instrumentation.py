#!/usr/bin/env python3
"""Apply low-noise Intel XR server video-path markers to companion checkouts.

This script is intentionally non-destructive: it does not fetch, reset, checkout, or
otherwise change Git refs. It only patches the two companion source files that are
outside the Monado-ALVR repository.
"""
from __future__ import annotations

import os
from pathlib import Path


def project_root() -> Path:
    if os.getenv("INTEL_XR_ROOT"):
        return Path(os.environ["INTEL_XR_ROOT"]).resolve()

    here = Path(__file__).resolve()
    for candidate in (Path.cwd(), here.parent):
        for parent in (candidate, *candidate.parents):
            if parent.name == "intel-xr-prototype":
                return parent

    # Expected checkout layout: <root>/src/Monado-ALVR/scripts/this_file.py
    inferred = here.parents[3]
    if (inferred / "src" / "Monado-ALVR").is_dir():
        return inferred

    raise SystemExit("ERROR: cannot locate intel-xr-prototype; set INTEL_XR_ROOT")


def patch_once(path: Path, old: str, new: str, marker: str) -> bool:
    text = path.read_text()
    if marker in text:
        print(f"[already instrumented] {path}: {marker}")
        return False
    if old not in text:
        raise SystemExit(f"ERROR: insertion point missing in {path}: {marker}")
    path.write_text(text.replace(old, new, 1))
    print(f"[patched] {path}: {marker}")
    return True


root = project_root()



def cleanup_companion_warnings() -> None:
    """Clean actionable companion warnings and isolate ABI-only pedantic warnings."""
    import re

    renderer = root / "src" / "alvr_render" / "src" / "Renderer.hpp"
    renderer_cpp = root / "src" / "alvr_render" / "src" / "Renderer.cpp"
    encoder = root / "src" / "alvr_render" / "src" / "Encoder.cpp"
    utils = root / "src" / "alvr_render" / "src" / "utils.hpp"
    binding = root / "src" / "alvr_render" / "src" / "alvr_binding.h"

    if renderer.is_file():
        text = renderer.read_text()
        # Current alvr_render uses a named local aggregate in getImages().
        old_named = """        AlvrVkExport expt {
            .sem = monadoFinishedSem,
        };"""
        new_named = """        AlvrVkExport expt {};
        expt.sem = monadoFinishedSem;"""
        if old_named in text:
            text = text.replace(old_named, new_named, 1)
            renderer.write_text(text)
            print(f"[cleanup] {renderer}: zero-initialize named AlvrVkExport")
            text = renderer.read_text()

        # Match the actual getImages() aggregate regardless of other initialized fields.
        pattern = re.compile(r"return\s+AlvrVkExport\s*\{(?P<body>.*?)\};", re.DOTALL)
        match = pattern.search(text)
        if match and "AlvrVkExport out {};" not in text:
            body = match.group("body")
            assignments = []
            for field, expr in re.findall(r"\.([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([^,]+),?", body):
                assignments.append(f"        out.{field} = {expr.strip()};")
            if assignments:
                replacement = "AlvrVkExport out {};\n" + "\n".join(assignments) + "\n        return out;"
                text = text[:match.start()] + replacement + text[match.end():]
                renderer.write_text(text)
                print(f"[cleanup] {renderer}: zero-initialize AlvrVkExport before field assignment")
        elif "AlvrVkExport out {};" in text:
            print(f"[already cleaned] {renderer}: AlvrVkExport")

    if encoder.is_file():
        text = encoder.read_text()
        changed = False
        old = "    auto& avHwCtx = *new alvr::HWContext(vkCtx);"
        if old in text:
            text = text.replace(old, "    [[maybe_unused]] auto& avHwCtx = *new alvr::HWContext(vkCtx);", 1)
            changed = True
        old_pipe = """        pipeCIs.push_back({
            .shaderData = loadShaderFile("quad"),
        });"""
        new_pipe = """        render::PipelineCreateInfo pipe {};
        pipe.shaderData = loadShaderFile("quad");
        pipeCIs.push_back(std::move(pipe));"""
        if old_pipe in text:
            text = text.replace(old_pipe, new_pipe, 1)
            changed = True
        if changed:
            encoder.write_text(text)
            print(f"[cleanup] {encoder}: initialize pipeline data / retained HW context")

    if renderer_cpp.is_file():
        text = renderer_cpp.read_text()
        old = "    for (int i = 0; i < ImageCount; ++i) {"
        if old in text:
            renderer_cpp.write_text(text.replace(old, "    for (u32 i = 0; i < ImageCount; ++i) {", 1))
            print(f"[cleanup] {renderer_cpp}: fix ImageCount signedness")

    if utils.is_file():
        text = utils.read_text()
        old = """        assert(false);
    }"""
        if old in text and "std::abort();" not in text:
            if "#include <cstdlib>" not in text:
                text = text.replace("#include ", "#include <cstdlib>\n#include ", 1)
            utils.write_text(text.replace(old, """        assert(false);
        std::abort();
    }""", 1))
            print(f"[cleanup] {utils}: make Optional::get() non-returning")

    # alvr_binding.h is generated/ABI-facing and intentionally uses anonymous
    # structs. Do not rewrite its layout. Suppress only GCC's pedantic warning
    # locally around this external binding header.
    if binding.is_file():
        text = binding.read_text()
        marker = "INTEL_XR_PEDANTIC_GUARD"
        if marker not in text:
            prefix = """/* INTEL_XR_PEDANTIC_GUARD: ABI-facing generated binding. */
#if defined(__GNUC__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wpedantic"
#endif
"""
            suffix = """
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif
"""
            binding.write_text(prefix + text + suffix)
            print(f"[cleanup] {binding}: scope -Wpedantic suppression to ABI binding")

cleanup_companion_warnings()
alvr_render = root / "src" / "alvr_render" / "src" / "Encoder.cpp"

if not alvr_render.is_file():
    raise SystemExit(f"ERROR: required source file missing: {alvr_render}")

encoder_old = """    renderer.get().render(vkCtx, idx, timelineVal);

    // TODO: not sure, but might actually work
    static u64 counter = 0;

    encoder->PushFrame(counter++, /* idrScheduler.CheckIDRInsertion() */ true);

    alvr::FramePacket framePacket;
    if (!encoder->GetEncoded(framePacket)) {
        assert(false);
    }

    // TODO: This constant conversion sucks
"""

encoder_new = """    renderer.get().render(vkCtx, idx, timelineVal);

    // Low-noise server-side diagnostic: prove that a Monado compositor image made
    // it all the way to the encode submission boundary.
    static bool intelXrEncoderInputLogged = false;
    if (!intelXrEncoderInputLogged) {
        std::cerr << "[INTEL-XR-SERVER] ENCODER_INPUT image=" << idx
                  << " timeline=" << timelineVal << std::endl;
        intelXrEncoderInputLogged = true;
    }

    // TODO: not sure, but might actually work
    static u64 counter = 0;

    encoder->PushFrame(counter++, /* idrScheduler.CheckIDRInsertion() */ true);

    alvr::FramePacket framePacket;
    if (!encoder->GetEncoded(framePacket)) {
        assert(false);
    }

    static bool intelXrEncodedFrameLogged = false;
    if (!intelXrEncodedFrameLogged) {
        std::cerr << "[INTEL-XR-SERVER] ENCODED_FRAME bytes=" << framePacket.size
                  << " idr=" << (framePacket.isIDR ? "true" : "false")
                  << " codec=" << encoder->GetCodec() << std::endl;
        intelXrEncodedFrameLogged = true;
    }

    // TODO: This constant conversion sucks
"""

patch_once(
    alvr_render,
    encoder_old,
    encoder_new,
    "[INTEL-XR-SERVER] ENCODER_INPUT",
)

patch_once(
    alvr_render,
    """    ParseFrameNals(encoder->GetCodec(), viewParams, framePacket.data, framePacket.size, framePacket.pts, framePacket.isIDR);""",
    """    static bool intelXrParseFrameNalsLogged = false;
    if (!intelXrParseFrameNalsLogged) {
        std::cerr << "[INTEL-XR-SERVER] PARSE_FRAME_NALS_ENTER bytes=" << framePacket.size
                  << " idr=" << (framePacket.isIDR ? "true" : "false") << std::endl;
        intelXrParseFrameNalsLogged = true;
    }
    ParseFrameNals(encoder->GetCodec(), viewParams, framePacket.data, framePacket.size, framePacket.pts, framePacket.isIDR);""",
    "[INTEL-XR-SERVER] PARSE_FRAME_NALS_ENTER",
)

# Instrument the companion NAL parser itself. This file is not owned by Monado-ALVR,
# so keep the patch idempotent alongside the Encoder.cpp companion patch.
nal_parser = root / "src" / "alvr_render" / "src" / "alvr_server" / "NalParsing.cpp"
if nal_parser.is_file():
    text = nal_parser.read_text()
    if "[INTEL-XR-NAL] PARSER_ENTER" not in text:
        if "#include <stdio.h>" not in text:
            text = text.replace("#include <string.h>\n", "#include <string.h>\n#include <stdio.h>\n", 1)
        old = """    static bool av1GotFrame = false;

    if ((unsigned)len < sizeof(NAL_PREFIX_4B)) {
        return;
    }

    if (codec == ALVR_CODEC_H264) {"""
        new = """    static bool av1GotFrame = false;
    static bool intelXrParserLogged = false;

    if (!intelXrParserLogged) {
        fprintf(stderr,
                "[INTEL-XR-NAL] PARSER_ENTER codec=%d len=%d idr=%d head=%02x %02x %02x %02x\\n",
                codec,
                len,
                isIdr ? 1 : 0,
                len > 0 ? buf[0] : 0,
                len > 1 ? buf[1] : 0,
                len > 2 ? buf[2] : 0,
                len > 3 ? buf[3] : 0);
        intelXrParserLogged = true;
    }

    if ((unsigned)len < sizeof(NAL_PREFIX_4B)) {
        fprintf(stderr, "[INTEL-XR-NAL] DROP_SHORT_BUFFER len=%d\\n", len);
        return;
    }

    int8_t intelXrPrefix = getNalPrefixSize(buf);
    fprintf(stderr, "[INTEL-XR-NAL] PREFIX_SIZE=%d codec=%d\\n", intelXrPrefix, codec);

    if (codec == ALVR_CODEC_H264) {"""
        if old not in text:
            raise SystemExit(f"ERROR: NAL parser insertion point missing: {nal_parser}")
        text = text.replace(old, new, 1)
        old_send = """    alvr_send_video_nal(targetTimestampNs, viewParams, isIdr, buf, len);"""
        new_send = """    fprintf(stderr,
            "[INTEL-XR-NAL] BEFORE_SEND codec=%d len=%d idr=%d head=%02x %02x %02x %02x\\n",
            codec,
            len,
            isIdr ? 1 : 0,
            len > 0 ? buf[0] : 0,
            len > 1 ? buf[1] : 0,
            len > 2 ? buf[2] : 0,
            len > 3 ? buf[3] : 0);
    alvr_send_video_nal(targetTimestampNs, viewParams, isIdr, buf, len);
    fprintf(stderr, "[INTEL-XR-NAL] AFTER_SEND\\n");"""
        if old_send not in text:
            raise SystemExit(f"ERROR: NAL send insertion point missing: {nal_parser}")
        text = text.replace(old_send, new_send, 1)
        nal_parser.write_text(text)
        print(f"[patched] {nal_parser}: [INTEL-XR-NAL] PARSER_ENTER / BEFORE_SEND")
    else:
        print(f"[already instrumented] {nal_parser}: [INTEL-XR-NAL] PARSER_ENTER")

print()
print("Server video instrumentation is applied.")
print("Expected markers:")
print("  FRAME_RECEIVED_FROM_MONADO   (Monado-ALVR repository source)")
print("  ENCODER_INPUT                (alvr_render companion)")
print("  ENCODED_FRAME ... idr=...    (alvr_render companion)")
print("  PARSE_FRAME_NALS_ENTER       (alvr_render companion)")\nprint("  NAL PARSER_ENTER/PREFIX      (NalParsing.cpp companion)")\nprint("  NAL BEFORE_SEND/AFTER_SEND   (NalParsing.cpp companion)")
print("  VIDEO_NAL_ENTER              (JLATORRE89/ALVR branch)")
print("  VIDEO_CHANNEL_ENQUEUE        (JLATORRE89/ALVR branch)")
print("  VIDEO_CHANNEL_DEQUEUE        (JLATORRE89/ALVR branch)")
print("  VIDEO_PACKET_SENT ...        (JLATORRE89/ALVR branch)")
print("  DECODER_CONFIG_SENT ...      (JLATORRE89/ALVR branch)")
print()
print("No Git refs were changed.")
