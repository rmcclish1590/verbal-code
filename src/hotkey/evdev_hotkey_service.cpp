#include "evdev_hotkey_service.hpp"

#include <linux/input.h>
#include <fcntl.h>
#include <unistd.h>
#include <poll.h>
#include <dirent.h>
#include <sys/ioctl.h>

#include <cstring>
#include <algorithm>

namespace verbal {

namespace {
constexpr const char* TAG = "EvdevHotkey";
} // namespace

EvdevHotkeyService::EvdevHotkeyService() = default;

EvdevHotkeyService::~EvdevHotkeyService() {
    stop();
}

std::vector<uint16_t> EvdevHotkeyService::modifier_name_to_keycodes(const std::string& name) {
    if (name == "ctrl" || name == "control") return {KEY_LEFTCTRL, KEY_RIGHTCTRL};
    if (name == "alt")                       return {KEY_LEFTALT, KEY_RIGHTALT};
    if (name == "super" || name == "meta")   return {KEY_LEFTMETA, KEY_RIGHTMETA};
    if (name == "shift")                     return {KEY_LEFTSHIFT, KEY_RIGHTSHIFT};
    return {};
}

bool EvdevHotkeyService::is_modifier_keycode(uint16_t code) {
    return code == KEY_LEFTCTRL  || code == KEY_RIGHTCTRL  ||
           code == KEY_LEFTALT   || code == KEY_RIGHTALT   ||
           code == KEY_LEFTMETA || code == KEY_RIGHTMETA  ||
           code == KEY_LEFTSHIFT || code == KEY_RIGHTSHIFT;
}

bool EvdevHotkeyService::any_modifiers_held() const {
    std::lock_guard<std::mutex> lock(key_mutex_);
    for (uint16_t code : held_keys_) {
        if (is_modifier_keycode(code)) return true;
    }
    return false;
}

void EvdevHotkeyService::set_modifiers(const std::vector<std::string>& modifiers) {
    std::lock_guard<std::mutex> lock(modifier_mutex_);
    required_modifiers_ = modifiers;
}

bool EvdevHotkeyService::check_modifiers(const ModifierState& state) const {
    std::lock_guard<std::mutex> lock(modifier_mutex_);
    return check_modifiers_match(required_modifiers_, state);
}

ModifierState EvdevHotkeyService::build_modifier_state() const {
    ModifierState state;
    state.ctrl  = held_keys_.count(KEY_LEFTCTRL)  || held_keys_.count(KEY_RIGHTCTRL);
    state.alt   = held_keys_.count(KEY_LEFTALT)   || held_keys_.count(KEY_RIGHTALT);
    state.super = held_keys_.count(KEY_LEFTMETA) || held_keys_.count(KEY_RIGHTMETA);
    state.shift = held_keys_.count(KEY_LEFTSHIFT) || held_keys_.count(KEY_RIGHTSHIFT);
    return state;
}

void EvdevHotkeyService::process_key_event(uint16_t code, int32_t value) {
    if (!is_modifier_keycode(code)) return;

    // value: 0=release, 1=press, 2=repeat (ignore repeats)
    if (value == 2) return;

    {
        std::lock_guard<std::mutex> lock(key_mutex_);
        if (value == 1) {
            held_keys_.insert(code);
        } else {
            held_keys_.erase(code);
        }
    }

    // Check modifier state after key change
    ModifierState state;
    {
        std::lock_guard<std::mutex> lock(key_mutex_);
        state = build_modifier_state();
    }

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
}

bool EvdevHotkeyService::is_keyboard_device(int fd) {
    unsigned long evbit[((EV_MAX + 7) / 8 + sizeof(unsigned long) - 1) / sizeof(unsigned long)] = {};
    if (ioctl(fd, EVIOCGBIT(0, sizeof(evbit)), evbit) < 0) return false;

    // Check if device supports EV_KEY
    if (!(evbit[0] & (1UL << EV_KEY))) return false;

    // Check if device has modifier keys (to filter out mice, joysticks, etc.)
    unsigned long keybit[((KEY_MAX + 7) / 8 + sizeof(unsigned long) - 1) / sizeof(unsigned long)] = {};
    if (ioctl(fd, EVIOCGBIT(EV_KEY, sizeof(keybit)), keybit) < 0) return false;

    // A keyboard should have at least KEY_LEFTCTRL (29)
    size_t idx = KEY_LEFTCTRL / (sizeof(unsigned long) * 8);
    size_t bit = KEY_LEFTCTRL % (sizeof(unsigned long) * 8);
    return (keybit[idx] & (1UL << bit)) != 0;
}

Result<void> EvdevHotkeyService::start() {
    if (running_.load()) return Result<void>::ok();

    // Create self-pipe for clean shutdown
    if (pipe(wakeup_pipe_) != 0) {
        return Result<void>::err("Failed to create wakeup pipe");
    }
    // Make read end non-blocking
    fcntl(wakeup_pipe_[0], F_SETFL, O_NONBLOCK);

    // Scan /dev/input/ for keyboard devices
    DIR* dir = opendir("/dev/input");
    if (!dir) {
        close(wakeup_pipe_[0]);
        close(wakeup_pipe_[1]);
        wakeup_pipe_[0] = wakeup_pipe_[1] = -1;
        return Result<void>::err("Cannot open /dev/input — check permissions (need input group)");
    }

    struct dirent* entry;
    while ((entry = readdir(dir)) != nullptr) {
        // Only look at event* devices
        if (std::strncmp(entry->d_name, "event", 5) != 0) continue;

        std::string path = std::string("/dev/input/") + entry->d_name;
        int fd = open(path.c_str(), O_RDONLY | O_NONBLOCK);
        if (fd < 0) continue;

        if (is_keyboard_device(fd)) {
            device_fds_.push_back(fd);
            LOG_DEBUG(TAG, "Opened keyboard: " + path);
        } else {
            close(fd);
        }
    }
    closedir(dir);

    if (device_fds_.empty()) {
        close(wakeup_pipe_[0]);
        close(wakeup_pipe_[1]);
        wakeup_pipe_[0] = wakeup_pipe_[1] = -1;
        return Result<void>::err("No keyboard devices found in /dev/input — check input group membership");
    }

    running_.store(true, std::memory_order_release);
    poll_thread_ = std::thread(&EvdevHotkeyService::poll_thread_func, this);

    LOG_INFO(TAG, "Evdev hotkey service started (" + std::to_string(device_fds_.size()) + " keyboards)");
    return Result<void>::ok();
}

void EvdevHotkeyService::stop() {
    running_.store(false, std::memory_order_release);

    // Wake up poll thread
    if (wakeup_pipe_[1] >= 0) {
        char c = 1;
        if (write(wakeup_pipe_[1], &c, 1) == -1) {
            // Best-effort wakeup; poll will exit via running_ flag
        }
    }

    if (poll_thread_.joinable()) {
        poll_thread_.join();
    }

    for (int fd : device_fds_) {
        close(fd);
    }
    device_fds_.clear();

    if (wakeup_pipe_[0] >= 0) {
        close(wakeup_pipe_[0]);
        wakeup_pipe_[0] = -1;
    }
    if (wakeup_pipe_[1] >= 0) {
        close(wakeup_pipe_[1]);
        wakeup_pipe_[1] = -1;
    }

    LOG_INFO(TAG, "Evdev hotkey service stopped");
}

void EvdevHotkeyService::poll_thread_func() {
    // Build pollfd array: device fds + wakeup pipe read end
    std::vector<struct pollfd> pfds;
    pfds.reserve(device_fds_.size() + 1);

    for (int fd : device_fds_) {
        pfds.push_back({fd, POLLIN, 0});
    }
    pfds.push_back({wakeup_pipe_[0], POLLIN, 0});

    while (running_.load(std::memory_order_acquire)) {
        int ret = poll(pfds.data(), pfds.size(), -1); // block until event
        if (ret <= 0) continue;

        // Check wakeup pipe
        if (pfds.back().revents & POLLIN) {
            break; // shutdown requested
        }

        // Read events from keyboard devices
        for (size_t i = 0; i < device_fds_.size(); ++i) {
            if (!(pfds[i].revents & POLLIN)) continue;

            struct input_event ev;
            while (read(device_fds_[i], &ev, sizeof(ev)) == static_cast<ssize_t>(sizeof(ev))) {
                if (ev.type == EV_KEY) {
                    process_key_event(ev.code, ev.value);
                }
            }
        }
    }
}

} // namespace verbal
