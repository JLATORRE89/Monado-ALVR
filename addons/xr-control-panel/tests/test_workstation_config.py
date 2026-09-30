"""Runtime settings: repository defaults stay in config/xr-build.json; workstation choices
(android.usb_stay_awake) go to the gitignored config/xr-build.local.json."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class WorkstationConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        runtime = d / "runtime"
        (runtime / "src/Monado-ALVR/scripts").mkdir(parents=True)
        (runtime / "src/Monado-ALVR/scripts/xr-app.sh").write_text("")
        self.cfg_dir = runtime / "src/Monado-ALVR/config"
        self.cfg_dir.mkdir()
        self.repo = self.cfg_dir / "xr-build.json"
        self.repo.write_text(json.dumps({"android": {"usb_stay_awake": False, "platform_api": 32},
                                         "network": {"mdns": True}}, indent=2) + "\n")
        (d / "panel.json").write_text(json.dumps({"runtime_root": str(runtime), "updates_dir": str(d / "u"),
                                                  "capture_dir": str(d / "c")}))
        self.env = patch.dict(os.environ, XR_PANEL_CONFIG=str(d / "panel.json"))
        self.env.start()
        spec = importlib.util.spec_from_file_location("panel_wscfg", ROOT / "server.py")
        self.s = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.s)
        self.local = self.cfg_dir / "xr-build.local.json"

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_workstation_setting_never_touches_the_tracked_file(self):
        before = self.repo.read_text()
        self.s.config_save({"android.usb_stay_awake": "true"})
        self.assertEqual(self.repo.read_text(), before)
        self.assertEqual(json.loads(self.local.read_text()), {"android": {"usb_stay_awake": True}})
        self.assertIs(self.s.config_values()["android.usb_stay_awake"], True)

    def test_repository_settings_still_go_to_the_repository_file(self):
        self.s.config_save({"network.mdns": False, "android.usb_stay_awake": True})
        repo = json.loads(self.repo.read_text())
        self.assertEqual((repo["network"]["mdns"], repo["android"]["usb_stay_awake"]), (False, False))
        self.assertEqual(self.s.config_values()["android.platform_api"], 32)

    def test_restore_drops_the_override(self):
        self.s.config_save({"android.usb_stay_awake": True})
        defaults = {"android.usb_stay_awake": False, "network.mdns": True, "android.platform_api": 32}
        with patch.object(self.s, "config_defaults", return_value=defaults):
            self.s.config_restore("android.usb_stay_awake")
        self.assertEqual(json.loads(self.local.read_text()), {"android": {}})
        self.assertIs(self.s.config_values()["android.usb_stay_awake"], False)
        self.assertEqual(json.loads(self.repo.read_text())["android"]["usb_stay_awake"], False)


if __name__ == "__main__":
    unittest.main()
