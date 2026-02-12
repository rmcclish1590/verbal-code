#include "xcb_hotkey_service.hpp"

#include <xcb/xcb.h>
#include <xcb/xinput.h>

#include <chrono>

namespace verbal {

namespace {
constexpr const char* TAG = "Hotkey";

// X11 modifier mask bits
constexpr uint16_t CTRL_MASK  = XCB_MOD_MASK_CONTROL;
constexpr uint16_t ALT_MASK   = XCB_MOD_MASK_1;
constexpr uint16_t SUPER_MASK = XCB_MOD_MASK_4;
constexpr uint16_t SHIFT_MASK = XCB_MOD_MASK_SHIFT;
} // namespace

XcbHotkeyService::XcbHotkeyService() = default;

XcbHotkeyService::~XcbHotkeyService() {
    stop();
}

uint16_t XcbHotkeyService::modifier_name_to_mask(const std::string& name) {
    if (name == "ctrl" || name == "control") return CTRL_MASK;
    if (name == "alt")                       return ALT_MASK;
    if (name == "super" || name == "meta")   return SUPER_MASK;
    if (name == "shift")                     return SHIFT_MASK;
    return 0;
}

void XcbHotkeyService::set_modifiers(const std::vector<std::string>& modifiers) {
    std::lock_guard<std::mutex> lock(modifier_mutex_);
    required_modifiers_ = modifiers;
    required_mask_ = 0;
    for (const auto& mod : modifiers) {
        required_mask_ |= modifier_name_to_mask(mod);
    }
}

bool XcbHotkeyService::check_modifiers(const ModifierState& state) const {
    std::lock_guard<std::mutex> lock(modifier_mutex_);
    for (const auto& mod : required_modifiers_) {
        if (mod == "ctrl" || mod == "control") {
            if (!state.ctrl) return false;
        } else if (mod == "alt") {
            if (!state.alt) return false;
        } else if (mod == "super" || mod == "meta") {
            if (!state.super) return false;
        } else if (mod == "shift") {
            if (!state.shift) return false;
        }
    }
    return !required_modifiers_.empty();
}

Result<void> XcbHotkeyService::start() {
    if (running_.load()) return Result<void>::ok();

    int screen_num = 0;
    connection_ = xcb_connect(nullptr, &screen_num);
    if (!connection_ || xcb_connection_has_error(connection_)) {
        return Result<void>::err("Failed to connect to X11 server");
    }

    running_.store(true, std::memory_order_release);
    poll_thread_ = std::thread(&XcbHotkeyService::poll_thread_func, this);

    LOG_INFO(TAG, "XCB hotkey service started");
    return Result<void>::ok();
}

void XcbHotkeyService::stop() {
    running_.store(false, std::memory_order_release);

    if (poll_thread_.joinable()) {
        poll_thread_.join();
    }

    if (connection_) {
        xcb_disconnect(connection_);
        connection_ = nullptr;
    }

    LOG_INFO(TAG, "XCB hotkey service stopped");
}

XcbHotkeyService::ModifierState XcbHotkeyService::query_modifier_state() {
    ModifierState state;
    if (!connection_) return state;

    auto cookie = xcb_query_pointer(connection_, xcb_setup_roots_iterator(xcb_get_setup(connection_)).data->root);
    auto* reply = xcb_query_pointer_reply(connection_, cookie, nullptr);
    if (reply) {
        uint16_t mask = reply->mask;
        state.ctrl  = (mask & CTRL_MASK)  != 0;
        state.alt   = (mask & ALT_MASK)   != 0;
        state.super = (mask & SUPER_MASK) != 0;
        state.shift = (mask & SHIFT_MASK) != 0;
        free(reply);
    }

    return state;
}

void XcbHotkeyService::poll_thread_func() {
    while (running_.load(std::memory_order_acquire)) {
        auto state = query_modifier_state();
        bool all_pressed = check_modifiers(state);

        bool was_pressed = pressed_.load(std::memory_order_acquire);

        if (all_pressed && !was_pressed) {
            pressed_.store(true, std::memory_order_release);
            LOG_DEBUG(TAG, "Hotkey pressed");
            if (on_press_) on_press_();
        } else if (!all_pressed && was_pressed) {
            pressed_.store(false, std::memory_order_release);
            LOG_DEBUG(TAG, "Hotkey released");
            if (on_release_) on_release_();
        }

        // Poll at ~60Hz
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
}

} // namespace verbal
