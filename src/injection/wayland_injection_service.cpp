#include "wayland_injection_service.hpp"
#include "injection_utils.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>

namespace verbal {

namespace {
constexpr const char* TAG = "WaylandInjection";

constexpr auto CLIPBOARD_SETTLE_MS = std::chrono::milliseconds(100);
constexpr auto POST_PASTE_SETTLE_MS = std::chrono::milliseconds(200);
constexpr auto POST_DELETE_SETTLE_MS = std::chrono::milliseconds(50);
constexpr size_t MAX_INJECTION_LEN = 10000;

} // namespace

WaylandInjectionService::WaylandInjectionService() = default;

WaylandInjectionService::~WaylandInjectionService() {
    stop();
}

Result<void> WaylandInjectionService::start() {
    if (running_.load()) return Result<void>::ok();

    has_wl_copy_ = injection::command_exists("wl-copy");
    has_wl_paste_ = injection::command_exists("wl-paste");
    has_ydotool_ = injection::command_exists("ydotool");
    has_wtype_ = injection::command_exists("wtype");

    if (!has_wtype_ && (!has_wl_copy_ || !has_wl_paste_ || !has_ydotool_)) {
        return Result<void>::err("No Wayland injection backend found. Install one of:\n"
                                 "  sudo apt install wtype                    (recommended)\n"
                                 "  sudo apt install wl-clipboard ydotool    (fallback)");
    }

    if (has_wtype_) {
        LOG_INFO(TAG, "wtype found — direct text injection available");
    }

    running_.store(true, std::memory_order_release);
    LOG_INFO(TAG, "Wayland injection service started");
    return Result<void>::ok();
}

void WaylandInjectionService::stop() {
    if (!running_.exchange(false)) return;
    LOG_INFO(TAG, "Wayland injection service stopped");
}

std::string WaylandInjectionService::get_clipboard() {
    std::string result;
    FILE* pipe = popen("wl-paste --no-newline 2>/dev/null", "r");
    if (pipe) {
        char buf[4096];
        size_t n;
        while ((n = fread(buf, 1, sizeof(buf), pipe)) > 0) {
            result.append(buf, n);
        }
        pclose(pipe);
    }
    return result;
}

bool WaylandInjectionService::set_clipboard(const std::string& text) {
    FILE* pipe = popen("wl-copy 2>/dev/null", "w");
    if (!pipe) return false;
    fwrite(text.c_str(), 1, text.size(), pipe);
    int status = pclose(pipe);
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

std::string WaylandInjectionService::build_paste_command(bool is_terminal) {
    // ydotool key syntax: keycode:state (1=down, 0=up)
    // KEY_LEFTCTRL=29, KEY_LEFTSHIFT=42, KEY_V=47
    if (is_terminal) {
        return "ydotool key 29:1 42:1 47:1 47:0 42:0 29:0";
    }
    return "ydotool key 29:1 47:1 47:0 29:0";
}

std::string WaylandInjectionService::build_backspace_command(size_t count) {
    // KEY_BACKSPACE=14
    constexpr size_t CHARS_PER_KEY = 10; // " 14:1 14:0"
    std::string cmd;
    cmd.reserve(11 + count * CHARS_PER_KEY);
    cmd = "ydotool key";
    for (size_t i = 0; i < count; ++i) {
        cmd += " 14:1 14:0";
    }
    return cmd;
}

Result<void> WaylandInjectionService::inject_via_wtype(const std::string& text) {
    FILE* pipe = popen("wtype -", "w");
    if (!pipe) {
        return Result<void>::err("Failed to launch wtype");
    }

    fwrite(text.c_str(), 1, text.size(), pipe);
    int status = pclose(pipe);

    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        return Result<void>::err("wtype failed (exit " +
                                 std::to_string(WEXITSTATUS(status)) + ")");
    }

    return Result<void>::ok();
}

Result<void> WaylandInjectionService::inject_via_clipboard(const std::string& text) {
    std::string saved_clipboard = get_clipboard();

    if (!set_clipboard(text)) {
        return Result<void>::err("Failed to set clipboard via wl-copy");
    }

    std::this_thread::sleep_for(CLIPBOARD_SETTLE_MS);

    std::string cmd = build_paste_command(false);
    int ret = injection::run_cmd(cmd);

    std::this_thread::sleep_for(POST_PASTE_SETTLE_MS);

    if (!saved_clipboard.empty()) {
        set_clipboard(saved_clipboard);
    }

    if (ret != 0) {
        return Result<void>::err("ydotool paste failed (exit " + std::to_string(ret) + ")");
    }

    return Result<void>::ok();
}

Result<void> WaylandInjectionService::inject_text(const std::string& text) {
    if (!running_.load()) {
        return Result<void>::err("Injection service not running");
    }

    if (text.empty()) {
        return Result<void>::ok();
    }

    LOG_INFO(TAG, "Injecting " + std::to_string(text.size()) + " chars");
    LOG_DEBUG(TAG, "Injecting text: \"" + text + "\"");

    Result<void> result = Result<void>::err("No injection strategy available");

    if (has_wtype_) {
        LOG_INFO(TAG, "Trying wtype...");
        result = inject_via_wtype(text);
        if (result.is_ok()) {
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via wtype");
        } else {
            LOG_WARN(TAG, "wtype failed: " + result.error());
        }
    }

    if (result.is_err() && has_wl_copy_ && has_ydotool_) {
        LOG_INFO(TAG, "Trying clipboard paste...");
        result = inject_via_clipboard(text);
        if (result.is_ok()) {
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via wl-clipboard + ydotool");
        } else {
            LOG_WARN(TAG, "Clipboard paste failed: " + result.error());
        }
    }

    if (result.is_ok()) {
        last_injection_len_ = std::min(text.size(), MAX_INJECTION_LEN);
    }

    return result;
}

bool WaylandInjectionService::has_focused_input() const {
    // No reliable way to detect focused input on Wayland
    return true;
}

Result<void> WaylandInjectionService::replace_last_injection(const std::string& new_text) {
    if (!running_.load()) {
        return Result<void>::err("Injection service not running");
    }

    if (last_injection_len_ > 0) {
        std::string cmd = build_backspace_command(last_injection_len_);
        injection::run_cmd(cmd);
        std::this_thread::sleep_for(POST_DELETE_SETTLE_MS);
    }

    if (!new_text.empty()) {
        last_injection_len_ = 0;
        return inject_text(new_text);
    }

    last_injection_len_ = 0;
    return Result<void>::ok();
}

} // namespace verbal
