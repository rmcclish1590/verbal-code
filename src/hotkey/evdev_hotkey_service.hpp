#pragma once

#include "i_hotkey_service.hpp"
#include "modifier_state.hpp"
#include "logger.hpp"

#include <linux/input.h>

#include <atomic>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_set>
#include <vector>

namespace verbal {

class EvdevHotkeyService : public IHotkeyService {
public:
    EvdevHotkeyService();
    ~EvdevHotkeyService() override;

    // IService
    Result<void> start() override;
    void stop() override;
    bool is_running() const override { return running_.load(std::memory_order_acquire); }

    // IHotkeyService
    void set_modifiers(const std::vector<std::string>& modifiers) override;
    void set_on_press(VoidCallback cb) override { on_press_ = std::move(cb); }
    void set_on_release(VoidCallback cb) override { on_release_ = std::move(cb); }
    bool is_pressed() const override { return pressed_.load(std::memory_order_acquire); }
    bool any_modifiers_held() const override;

    // Check if all required modifiers are active given current state
    bool check_modifiers(const ModifierState& state) const;

    // For testing: process a single key event without hardware
    // code: linux keycode, value: 0=release, 1=press, 2=repeat
    void process_key_event(uint16_t code, int32_t value);

private:
    void poll_thread_func();
    bool is_keyboard_device(int fd);
    ModifierState build_modifier_state() const;

    // Map modifier name to set of linux keycodes
    static std::vector<uint16_t> modifier_name_to_keycodes(const std::string& name);
    static bool is_modifier_keycode(uint16_t code);

    std::vector<std::string> required_modifiers_;
    mutable std::mutex modifier_mutex_;

    // Currently held key codes
    std::unordered_set<uint16_t> held_keys_;
    mutable std::mutex key_mutex_;

    VoidCallback on_press_;
    VoidCallback on_release_;

    std::vector<int> device_fds_;
    int wakeup_pipe_[2] = {-1, -1};

    std::thread poll_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> pressed_{false};
};

} // namespace verbal
