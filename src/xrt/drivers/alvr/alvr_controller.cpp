// Copyright 2026, Intel XR Prototype contributors
// SPDX-License-Identifier: BSL-1.0
/*!
 * @file
 * @brief  Quest Touch controllers streamed by ALVR (poses, buttons, haptics).
 *
 * Poses: on every ALVR tracking sample (the event the HMD already consumes) the hand motion
 * is read with alvr_get_device_motion(hand_*) and pushed into a per-hand relation history.
 * Buttons: server core queues one batch per ALVR_EVENT_BUTTONS_UPDATED; alvr_render's event
 * loop does not consume them, so the batches are drained here on the same callback (this also
 * stops the queue from growing for the whole session). Haptics: set_output ->
 * alvr_send_haptics. Set INTEL_XR_ALVR_CONTROLLERS=0 to disable the devices.
 *
 * @ingroup drv_alvr
 */

#include "alvr_binding.h"
#include "alvr_interface.h"

#include "os/os_time.h"
#include "xrt/xrt_defines.h"
#include "xrt/xrt_device.h"

#include "math/m_api.h"
#include "math/m_mathinclude.h" // IWYU pragma: keep
#include "math/m_relation_history.h"

#include "util/u_debug.h"
#include "util/u_device.h"
#include "util/u_logging.h"
#include "util/u_misc.h"
#include "util/u_time.h"
#include "util/u_var.h"

#include <cmath>
#include <cstdlib>
#include <cstring>
#include <mutex>
#include <new>
#include <string>
#include <vector>

#include <EventManager.hpp>

DEBUG_GET_ONCE_LOG_OPTION(alvr_ctrl_log, "ALVR_CTRL_LOG", U_LOGGING_INFO)
DEBUG_GET_ONCE_BOOL_OPTION(alvr_controllers, "INTEL_XR_ALVR_CONTROLLERS", true)
// Aim ray relative to the grip pose, degrees about the grip X axis (negative pitches down).
// Tuned in the headset: -40 was high on both hands, -50 right for the left hand but still high on
// the right. The ALVR grip correction is mirror-symmetric, so the per-hand difference is empirical.
DEBUG_GET_ONCE_NUM_OPTION(alvr_aim_pitch_left_deg, "INTEL_XR_ALVR_AIM_PITCH_LEFT_DEG", -50)
DEBUG_GET_ONCE_NUM_OPTION(alvr_aim_pitch_right_deg, "INTEL_XR_ALVR_AIM_PITCH_RIGHT_DEG", -60)

#define CTRL_INFO(c, ...) U_LOG_XDEV_IFL_I(&(c)->base, (c)->log_level, __VA_ARGS__)

// Report "not tracked" when no hand sample arrived for this long (controller asleep,
// hand tracking active, or stream stopped).
static constexpr int64_t CTRL_STALE_NS = 500 * U_TIME_1MS_IN_NS;

enum alvr_ctrl_input
{
	IN_BTN1_CLICK = 0, // X (left) / A (right)
	IN_BTN1_TOUCH,
	IN_BTN2_CLICK, // Y (left) / B (right)
	IN_BTN2_TOUCH,
	IN_MENU_CLICK, // menu (left) / system (right)
	IN_SQUEEZE_VALUE,
	IN_TRIGGER_TOUCH,
	IN_TRIGGER_VALUE,
	IN_THUMBSTICK_CLICK,
	IN_THUMBSTICK_TOUCH,
	IN_THUMBSTICK,
	IN_THUMBREST_TOUCH,
	IN_GRIP_POSE,
	IN_AIM_POSE,
	IN_COUNT,
};

enum alvr_button_kind
{
	KIND_BOOL,
	KIND_FLOAT,
	KIND_STICK_X,
	KIND_STICK_Y,
};

struct alvr_button_map
{
	uint64_t id;
	int hand; // 0 left, 1 right
	alvr_ctrl_input input;
	alvr_button_kind kind;
	const char *path;
};

/*!
 * @implements xrt_device
 */
struct alvr_controller
{
	struct xrt_device base;
	enum u_logging_level log_level;
	int hand; // 0 left, 1 right
	uint64_t device_id;

	// Has its own mutex.
	struct m_relation_history *relation_hist;
	// Undoes the client's SteamVR-oriented grip offset (client_openxr get_controller_offset).
	struct xrt_pose alvr_offset_inv;
	struct xrt_pose grip_to_aim;

	std::mutex mutex;
	int64_t last_sample_ns = 0;
	bool bools[IN_COUNT] = {};
	float floats[IN_COUNT] = {};
	struct xrt_vec2 stick = {};
	int64_t last_input_ns = 0;
};

static inline struct alvr_controller *
to_ctrl(struct xrt_device *xdev)
{
	return (struct alvr_controller *)xdev;
}

// Device lifetime vs. the (unregisterable) CallbackManager callback: the callback only sees
// controllers through these pointers, cleared on destroy.
static std::mutex g_ctrl_mutex;
static struct alvr_controller *g_ctrl[2] = {nullptr, nullptr};
static std::vector<alvr_button_map> g_button_map;

static struct xrt_binding_input_pair simple_inputs_alvr[4] = {
    {XRT_INPUT_SIMPLE_SELECT_CLICK, XRT_INPUT_TOUCH_TRIGGER_VALUE},
    {XRT_INPUT_SIMPLE_MENU_CLICK, XRT_INPUT_TOUCH_MENU_CLICK},
    {XRT_INPUT_SIMPLE_GRIP_POSE, XRT_INPUT_TOUCH_GRIP_POSE},
    {XRT_INPUT_SIMPLE_AIM_POSE, XRT_INPUT_TOUCH_AIM_POSE},
};

static struct xrt_binding_output_pair simple_outputs_alvr[1] = {
    {XRT_OUTPUT_NAME_SIMPLE_VIBRATION, XRT_OUTPUT_NAME_TOUCH_HAPTIC},
};

static struct xrt_binding_profile binding_profiles_alvr[1] = {
    {
        .name = XRT_DEVICE_SIMPLE_CONTROLLER,
        .inputs = simple_inputs_alvr,
        .input_count = ARRAY_SIZE(simple_inputs_alvr),
        .outputs = simple_outputs_alvr,
        .output_count = ARRAY_SIZE(simple_outputs_alvr),
    },
};

static void
build_button_map(void)
{
	struct entry
	{
		const char *suffix;
		alvr_ctrl_input left_input;
		alvr_ctrl_input right_input;
		alvr_button_kind kind;
	};
	// Quest2Touch emulation passes these Quest Touch paths through unchanged
	// (alvr/common/src/inputs.rs, server_core/src/input_mapping.rs).
	static const entry entries[] = {
	    {"x/click", IN_BTN1_CLICK, IN_COUNT, KIND_BOOL},
	    {"x/touch", IN_BTN1_TOUCH, IN_COUNT, KIND_BOOL},
	    {"y/click", IN_BTN2_CLICK, IN_COUNT, KIND_BOOL},
	    {"y/touch", IN_BTN2_TOUCH, IN_COUNT, KIND_BOOL},
	    {"a/click", IN_COUNT, IN_BTN1_CLICK, KIND_BOOL},
	    {"a/touch", IN_COUNT, IN_BTN1_TOUCH, KIND_BOOL},
	    {"b/click", IN_COUNT, IN_BTN2_CLICK, KIND_BOOL},
	    {"b/touch", IN_COUNT, IN_BTN2_TOUCH, KIND_BOOL},
	    {"menu/click", IN_MENU_CLICK, IN_COUNT, KIND_BOOL},
	    {"system/click", IN_COUNT, IN_MENU_CLICK, KIND_BOOL},
	    {"squeeze/value", IN_SQUEEZE_VALUE, IN_SQUEEZE_VALUE, KIND_FLOAT},
	    {"trigger/touch", IN_TRIGGER_TOUCH, IN_TRIGGER_TOUCH, KIND_BOOL},
	    {"trigger/value", IN_TRIGGER_VALUE, IN_TRIGGER_VALUE, KIND_FLOAT},
	    {"thumbstick/click", IN_THUMBSTICK_CLICK, IN_THUMBSTICK_CLICK, KIND_BOOL},
	    {"thumbstick/touch", IN_THUMBSTICK_TOUCH, IN_THUMBSTICK_TOUCH, KIND_BOOL},
	    {"thumbstick/x", IN_THUMBSTICK, IN_THUMBSTICK, KIND_STICK_X},
	    {"thumbstick/y", IN_THUMBSTICK, IN_THUMBSTICK, KIND_STICK_Y},
	    {"thumbrest/touch", IN_THUMBREST_TOUCH, IN_THUMBREST_TOUCH, KIND_BOOL},
	};
	static const char *const hand_prefix[2] = {"/user/hand/left/input/", "/user/hand/right/input/"};

	g_button_map.clear();
	for (const entry &e : entries) {
		for (int hand = 0; hand < 2; hand++) {
			alvr_ctrl_input input = hand == 0 ? e.left_input : e.right_input;
			if (input == IN_COUNT) {
				continue;
			}
			char path[96];
			snprintf(path, sizeof(path), "%s%s", hand_prefix[hand], e.suffix);
			g_button_map.push_back({alvr_path_to_id(path), hand, input, e.kind, e.suffix});
		}
	}
}

// Called with g_ctrl_mutex held.
static void
apply_button(const AlvrButtonEntry &entry)
{
	for (const alvr_button_map &m : g_button_map) {
		if (m.id != entry.id) {
			continue;
		}
		struct alvr_controller *c = g_ctrl[m.hand];
		if (c == nullptr) {
			return;
		}

		std::lock_guard lock(c->mutex);
		switch (m.kind) {
		case KIND_BOOL: c->bools[m.input] = entry.value.scalar; break;
		case KIND_FLOAT: c->floats[m.input] = entry.value.floatp; break;
		case KIND_STICK_X: c->stick.x = entry.value.floatp; break;
		case KIND_STICK_Y: c->stick.y = entry.value.floatp; break;
		}
		c->last_input_ns = os_monotonic_get_ns();

		static uint64_t count = 0;
		++count;
		if (count <= 20 || count % 200 == 0) {
			CTRL_INFO(c, "[INTEL-XR-CTRL] BUTTON hand=%c %s value=%s count=%llu", m.hand == 0 ? 'L' : 'R',
			          m.path,
			          m.kind == KIND_BOOL ? (entry.value.scalar ? "1" : "0") : std::to_string(entry.value.floatp).c_str(),
			          (unsigned long long)count);
		}
		return;
	}
}

// Called with g_ctrl_mutex held. Single consumer of server core's button queue.
static void
drain_buttons(void)
{
	// alvr_get_buttons(NULL) sizes the front batch; the pop below can see a batch pushed in
	// between, so keep the buffer far larger than any batch (both hands' full set is ~30).
	static std::vector<AlvrButtonEntry> buffer(256);

	for (int batch = 0; batch < 32; batch++) {
		uint64_t const pending = alvr_get_buttons(nullptr);
		if (pending > buffer.size()) {
			buffer.resize(pending * 2);
		}
		uint64_t const got = alvr_get_buttons(buffer.data());
		for (uint64_t i = 0; i < got && i < buffer.size(); i++) {
			apply_button(buffer[i]);
		}
		if (pending == 0 && got == 0) {
			break; // queue empty (an empty batch, if any, was popped too)
		}
	}
}

// Called with g_ctrl_mutex held.
static void
update_pose(struct alvr_controller *c, uint64_t sample_ts_ns)
{
	AlvrDeviceMotion motion;
	if (!alvr_get_device_motion(c->device_id, sample_ts_ns, &motion)) {
		return;
	}

	struct xrt_space_relation rel = XRT_SPACE_RELATION_ZERO;
	rel.pose.orientation = {motion.pose.orientation.x, motion.pose.orientation.y, motion.pose.orientation.z,
	                        motion.pose.orientation.w};
	rel.pose.position = {motion.pose.position[0], motion.pose.position[1], motion.pose.position[2]};
	rel.linear_velocity = {motion.linear_velocity[0], motion.linear_velocity[1], motion.linear_velocity[2]};
	rel.angular_velocity = {motion.angular_velocity[0], motion.angular_velocity[1], motion.angular_velocity[2]};

	struct xrt_quat &q = rel.pose.orientation;
	float const norm_sq = q.x * q.x + q.y * q.y + q.z * q.z + q.w * q.w;
	if (!std::isfinite(norm_sq) || norm_sq < 1.0e-6f) {
		return;
	}
	math_quat_normalize(&q);

	struct xrt_pose grip;
	math_pose_transform(&rel.pose, &c->alvr_offset_inv, &grip);
	rel.pose = grip;
	rel.relation_flags = XRT_SPACE_RELATION_BITMASK_ALL;

	int64_t const now = os_monotonic_get_ns();
	m_relation_history_push(c->relation_hist, &rel, now);

	std::lock_guard lock(c->mutex);
	if (c->last_sample_ns == 0) {
		CTRL_INFO(c, "[INTEL-XR-CTRL] FIRST_POSE hand=%c pos=(%.3f,%.3f,%.3f)", c->hand == 0 ? 'L' : 'R',
		          grip.position.x, grip.position.y, grip.position.z);
	}
	c->last_sample_ns = now;
}

static void
on_tracking(uint64_t sample_ts_ns, AlvrDeviceMotion /*head*/)
{
	std::lock_guard lock(g_ctrl_mutex);
	for (struct alvr_controller *c : g_ctrl) {
		if (c != nullptr) {
			update_pose(c, sample_ts_ns);
		}
	}
	drain_buttons();
}

static xrt_result_t
alvr_controller_update_inputs(struct xrt_device *xdev)
{
	struct alvr_controller *c = to_ctrl(xdev);
	std::lock_guard lock(c->mutex);

	int64_t const ts = c->last_input_ns != 0 ? c->last_input_ns : os_monotonic_get_ns();
	for (int i = 0; i < IN_COUNT; i++) {
		struct xrt_input &in = c->base.inputs[i];
		in.timestamp = ts;
		switch (i) {
		case IN_SQUEEZE_VALUE:
		case IN_TRIGGER_VALUE: in.value.vec1.x = c->floats[i]; break;
		case IN_THUMBSTICK: in.value.vec2 = c->stick; break;
		case IN_GRIP_POSE:
		case IN_AIM_POSE: break;
		default: in.value.boolean = c->bools[i]; break;
		}
	}
	return XRT_SUCCESS;
}

static xrt_result_t
alvr_controller_get_tracked_pose(struct xrt_device *xdev,
                                 enum xrt_input_name name,
                                 int64_t at_timestamp_ns,
                                 struct xrt_space_relation *out_relation)
{
	struct alvr_controller *c = to_ctrl(xdev);

	if (name != XRT_INPUT_TOUCH_GRIP_POSE && name != XRT_INPUT_TOUCH_AIM_POSE) {
		U_LOG_XDEV_UNSUPPORTED_INPUT(&c->base, c->log_level, name);
		return XRT_ERROR_INPUT_UNSUPPORTED;
	}

	struct xrt_space_relation rel = XRT_SPACE_RELATION_ZERO;
	rel.pose.orientation.w = 1.0f;

	int64_t last_sample_ns;
	{
		std::lock_guard lock(c->mutex);
		last_sample_ns = c->last_sample_ns;
	}
	bool const fresh = last_sample_ns != 0 && os_monotonic_get_ns() - last_sample_ns < CTRL_STALE_NS;

	if (fresh && m_relation_history_get(c->relation_hist, at_timestamp_ns, &rel) !=
	                 M_RELATION_HISTORY_RESULT_INVALID) {
		math_quat_normalize(&rel.pose.orientation);
		if (name == XRT_INPUT_TOUCH_AIM_POSE) {
			struct xrt_pose aim;
			math_pose_transform(&rel.pose, &c->grip_to_aim, &aim);
			rel.pose = aim;
		}
	} else {
		rel = XRT_SPACE_RELATION_ZERO;
		rel.pose.orientation.w = 1.0f;
	}

	*out_relation = rel;
	return XRT_SUCCESS;
}

static void
alvr_controller_set_output(struct xrt_device *xdev, enum xrt_output_name name, const union xrt_output_value *value)
{
	struct alvr_controller *c = to_ctrl(xdev);
	if (name != XRT_OUTPUT_NAME_TOUCH_HAPTIC) {
		return;
	}

	float const amplitude = value->vibration.amplitude;
	// XRT_MIN_HAPTIC_DURATION (-1) and 0 mean "shortest"; ALVR applies its own minimum.
	float const duration_s =
	    value->vibration.duration_ns > 0 ? (float)value->vibration.duration_ns / (float)U_TIME_1S_IN_NS : 0.01f;
	float const frequency = value->vibration.frequency > 0.0f ? value->vibration.frequency : 0.0f;
	if (amplitude <= 0.0f) {
		return;
	}
	alvr_send_haptics(c->device_id, duration_s, frequency, amplitude);

	static uint64_t count = 0;
	if (++count <= 10) {
		CTRL_INFO(c, "[INTEL-XR-CTRL] HAPTIC hand=%c amp=%.2f dur=%.3f freq=%.0f", c->hand == 0 ? 'L' : 'R',
		          amplitude, duration_s, frequency);
	}
}

static void
alvr_controller_destroy(struct xrt_device *xdev)
{
	struct alvr_controller *c = to_ctrl(xdev);
	{
		std::lock_guard lock(g_ctrl_mutex);
		if (g_ctrl[c->hand] == c) {
			g_ctrl[c->hand] = nullptr;
		}
	}
	u_var_remove_root(c);
	m_relation_history_destroy(&c->relation_hist);
	c->~alvr_controller();
	u_device_free(&c->base);
}

static struct alvr_controller *
alvr_controller_create(int hand)
{
	enum u_device_alloc_flags flags = U_DEVICE_ALLOC_TRACKING_NONE;
	struct alvr_controller *c = U_DEVICE_ALLOCATE(struct alvr_controller, flags, IN_COUNT, 1);
	if (c == nullptr) {
		return nullptr;
	}
	struct xrt_device base = c->base;
	new (c) alvr_controller(); // construct the C++ members (std::mutex) in the calloc'd block
	c->base = base;

	c->log_level = debug_get_log_option_alvr_ctrl_log();
	c->hand = hand;
	AlvrDeviceIds const ids = alvr_get_ids();
	c->device_id = hand == 0 ? ids.hand_left : ids.hand_right;
	m_relation_history_create(&c->relation_hist);

	// Client offset (Quest): position (-/+0.005, -0.005, 0), rotation -15 deg about X.
	struct xrt_pose alvr_offset = XRT_POSE_IDENTITY;
	struct xrt_vec3 const x_axis = {1.0f, 0.0f, 0.0f};
	math_quat_from_angle_vector((float)(-15.0 * M_PI / 180.0), &x_axis, &alvr_offset.orientation);
	alvr_offset.position = {hand == 0 ? -0.005f : 0.005f, -0.005f, 0.0f};
	math_pose_invert(&alvr_offset, &c->alvr_offset_inv);

	c->grip_to_aim = XRT_POSE_IDENTITY;
	double const aim_pitch = (double)(hand == 0 ? debug_get_num_option_alvr_aim_pitch_left_deg()
	                                             : debug_get_num_option_alvr_aim_pitch_right_deg());
	math_quat_from_angle_vector((float)(aim_pitch * M_PI / 180.0), &x_axis, &c->grip_to_aim.orientation);

	c->base.name = XRT_DEVICE_TOUCH_CONTROLLER;
	c->base.device_type = hand == 0 ? XRT_DEVICE_TYPE_LEFT_HAND_CONTROLLER : XRT_DEVICE_TYPE_RIGHT_HAND_CONTROLLER;
	c->base.orientation_tracking_supported = true;
	c->base.position_tracking_supported = true;
	snprintf(c->base.str, XRT_DEVICE_NAME_LEN, "ALVR %s Touch Controller", hand == 0 ? "Left" : "Right");
	snprintf(c->base.serial, XRT_DEVICE_NAME_LEN, "ALVR %s Controller", hand == 0 ? "Left" : "Right");

	c->base.update_inputs = alvr_controller_update_inputs;
	c->base.get_tracked_pose = alvr_controller_get_tracked_pose;
	c->base.set_output = alvr_controller_set_output;
	c->base.destroy = alvr_controller_destroy;
	c->base.get_view_poses = u_device_ni_get_view_poses;
	c->base.compute_distortion = u_device_ni_compute_distortion;
	c->base.get_visibility_mask = u_device_ni_get_visibility_mask;
	c->base.is_form_factor_available = u_device_ni_is_form_factor_available;
	c->base.get_battery_status = u_device_ni_get_battery_status;

	static const enum xrt_input_name left_names[IN_COUNT] = {
	    XRT_INPUT_TOUCH_X_CLICK,          XRT_INPUT_TOUCH_X_TOUCH,          XRT_INPUT_TOUCH_Y_CLICK,
	    XRT_INPUT_TOUCH_Y_TOUCH,          XRT_INPUT_TOUCH_MENU_CLICK,       XRT_INPUT_TOUCH_SQUEEZE_VALUE,
	    XRT_INPUT_TOUCH_TRIGGER_TOUCH,    XRT_INPUT_TOUCH_TRIGGER_VALUE,    XRT_INPUT_TOUCH_THUMBSTICK_CLICK,
	    XRT_INPUT_TOUCH_THUMBSTICK_TOUCH, XRT_INPUT_TOUCH_THUMBSTICK,       XRT_INPUT_TOUCH_THUMBREST_TOUCH,
	    XRT_INPUT_TOUCH_GRIP_POSE,        XRT_INPUT_TOUCH_AIM_POSE,
	};
	static const enum xrt_input_name right_names[IN_COUNT] = {
	    XRT_INPUT_TOUCH_A_CLICK,          XRT_INPUT_TOUCH_A_TOUCH,          XRT_INPUT_TOUCH_B_CLICK,
	    XRT_INPUT_TOUCH_B_TOUCH,          XRT_INPUT_TOUCH_SYSTEM_CLICK,     XRT_INPUT_TOUCH_SQUEEZE_VALUE,
	    XRT_INPUT_TOUCH_TRIGGER_TOUCH,    XRT_INPUT_TOUCH_TRIGGER_VALUE,    XRT_INPUT_TOUCH_THUMBSTICK_CLICK,
	    XRT_INPUT_TOUCH_THUMBSTICK_TOUCH, XRT_INPUT_TOUCH_THUMBSTICK,       XRT_INPUT_TOUCH_THUMBREST_TOUCH,
	    XRT_INPUT_TOUCH_GRIP_POSE,        XRT_INPUT_TOUCH_AIM_POSE,
	};
	for (int i = 0; i < IN_COUNT; i++) {
		c->base.inputs[i].name = hand == 0 ? left_names[i] : right_names[i];
	}
	c->base.outputs[0].name = XRT_OUTPUT_NAME_TOUCH_HAPTIC;
	c->base.binding_profiles = binding_profiles_alvr;
	c->base.binding_profile_count = ARRAY_SIZE(binding_profiles_alvr);

	u_var_add_root(c, c->base.str, true);
	u_var_add_log_level(c, &c->log_level, "log_level");

	return c;
}

extern "C" int
alvr_controllers_create(struct xrt_device **out_left, struct xrt_device **out_right)
{
	if (!debug_get_bool_option_alvr_controllers()) {
		U_LOG_I("[INTEL-XR-CTRL] disabled (INTEL_XR_ALVR_CONTROLLERS=0)");
		return 0;
	}

	struct alvr_controller *left = alvr_controller_create(0);
	struct alvr_controller *right = alvr_controller_create(1);
	if (left == nullptr || right == nullptr) {
		if (left != nullptr) {
			alvr_controller_destroy(&left->base);
		}
		if (right != nullptr) {
			alvr_controller_destroy(&right->base);
		}
		return 0;
	}

	{
		std::lock_guard lock(g_ctrl_mutex);
		g_ctrl[0] = left;
		g_ctrl[1] = right;
		if (g_button_map.empty()) {
			build_button_map();
		}
	}

	// CallbackManager has no unregister; register once per process.
	static bool registered = false;
	if (!registered) {
		CallbackManager::get().registerCb<ALVR_EVENT_TRACKING_UPDATED>(on_tracking);
		registered = true;
	}

	U_LOG_I("[INTEL-XR-CTRL] CREATED left+right Touch controllers (aim pitch L %d R %d deg)",
	        (int)debug_get_num_option_alvr_aim_pitch_left_deg(), (int)debug_get_num_option_alvr_aim_pitch_right_deg());
	*out_left = &left->base;
	*out_right = &right->base;
	return 2;
}
