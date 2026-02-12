#pragma once

#include "i_hotkey_service.hpp"
#include "logger.hpp"

#include <xcb/xcb.h>
#include <xcb/xinput.h>

#include <atomic>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace verbal {

class XcbHotkeyService : public IHotkeyService {
public:
    XcbHotkeyService();
    ~XcbHotkeyService() override;

    // IService
    Result<void> start() override;
    void stop() override;
    bool is_running() const override { return running_.load(std::memory_order_acquire); }

    // IHotkeyService
    void set_modifiers(const std::vector<std::string>& modifiers) override;
    void set_on_press(VoidCallback cb) override { on_press_ = std::move(cb); }
    void set_on_release(VoidCallback cb) override { on_release_ = std::move(cb); }
    bool is_pressed() const override { return pressed_.load(std::memory_order_acquire); }

    // For testing: simulate modifier state
    struct ModifierState {
        bool ctrl = false;
        bool super = false;
        bool alt = false;
        bool shift = false;
    };

    // Check if all required modifiers are active given current state
    bool check_modifiers(const ModifierState& state) const;

private:
    void poll_thread_func();
    ModifierState query_modifier_state();

    // Map modifier name to XCB modifier mask bit
    static uint16_t modifier_name_to_mask(const std::string& name);

    xcb_connection_t* connection_ = nullptr;
    std::vector<std::string> required_modifiers_;
    uint16_t required_mask_ = 0;
    mutable std::mutex modifier_mutex_;

    VoidCallback on_press_;
    VoidCallback on_release_;

    std::thread poll_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> pressed_{false};
};

} // namespace verbal
