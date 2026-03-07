#include "wayland_injection_service.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>

namespace verbal {

namespace {
constexpr const char* TAG = "WaylandInjection";

int run_cmd(const std::string& cmd) {
    int ret = std::system(cmd.c_str());
    return WIFEXITED(ret) ? WEXITSTATUS(ret) : -1;
}

bool command_exists(const char* name) {
    std::string cmd = std::string("which ") + name + " >/dev/null 2>&1";
    return run_cmd(cmd) == 0;
}

} // namespace

WaylandInjectionService::WaylandInjectionService() = default;

WaylandInjectionService::~WaylandInjectionService() {
    stop();
}

Result<void> WaylandInjectionService::start() {
    if (running_.load()) return Result<void>::ok();

    has_wl_copy_ = command_exists("wl-copy");
    has_wl_paste_ = command_exists("wl-paste");
    has_ydotool_ = command_exists("ydotool");
    has_wtype_ = command_exists("wtype");

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
    running_.store(false, std::memory_order_release);
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
        // Ctrl+Shift+V
        return "ydotool key 29:1 42:1 47:1 47:0 42:0 29:0";
    }
    // Ctrl+V
    return "ydotool key 29:1 47:1 47:0 29:0";
}

std::string WaylandInjectionService::build_backspace_command(size_t count) {
    // KEY_BACKSPACE=14
    std::string cmd = "ydotool key";
    for (size_t i = 0; i < count; ++i) {
        cmd += " 14:1 14:0";
    }
    return cmd;
}

Result<void> WaylandInjectionService::inject_via_wtype(const std::string& text) {
    // wtype types text directly via Wayland virtual-keyboard protocol.
    // No clipboard, no Ctrl+V, no modifier interference.
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
    // Save current clipboard
    std::string saved_clipboard = get_clipboard();

    // Set our text to clipboard
    if (!set_clipboard(text)) {
        return Result<void>::err("Failed to set clipboard via wl-copy");
    }

    // Let clipboard settle
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Paste via ydotool Ctrl+V
    std::string cmd = build_paste_command(false);
    int ret = run_cmd(cmd);

    // Give paste time to complete
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    // Restore original clipboard
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

    LOG_INFO(TAG, "Injecting text: \"" + text + "\"");

    // Strategy 1: wtype — types text directly via Wayland protocol.
    // No clipboard, no Ctrl+V, no modifier key interference.
    if (has_wtype_) {
        LOG_INFO(TAG, "Trying wtype...");
        auto result = inject_via_wtype(text);
        if (result.is_ok()) {
            last_injection_text_ = text;
            last_injection_len_ = text.size();
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via wtype");
            return result;
        }
        LOG_WARN(TAG, "wtype failed: " + result.error());
    }

    // Strategy 2: wl-clipboard + ydotool Ctrl+V (fallback)
    if (has_wl_copy_ && has_ydotool_) {
        LOG_INFO(TAG, "Trying clipboard paste...");
        auto result = inject_via_clipboard(text);
        if (result.is_ok()) {
            last_injection_text_ = text;
            last_injection_len_ = text.size();
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via wl-clipboard + ydotool");
            return result;
        }
        LOG_WARN(TAG, "Clipboard paste failed: " + result.error());
    }

    return Result<void>::err("All Wayland injection methods failed");
}

bool WaylandInjectionService::has_focused_input() {
    // No reliable way to detect focused input on Wayland
    return true;
}

Result<void> WaylandInjectionService::replace_last_injection(const std::string& new_text) {
    if (!running_.load()) {
        return Result<void>::err("Injection service not running");
    }

    // Delete old text using backspaces
    if (last_injection_len_ > 0) {
        std::string cmd = build_backspace_command(last_injection_len_);
        run_cmd(cmd);
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    // Inject the new text
    if (!new_text.empty()) {
        last_injection_len_ = 0;
        last_injection_text_.clear();
        return inject_text(new_text);
    }

    last_injection_text_.clear();
    last_injection_len_ = 0;
    return Result<void>::ok();
}

} // namespace verbal
