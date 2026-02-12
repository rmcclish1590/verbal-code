#include "xdo_injection_service.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>

namespace verbal {

namespace {
constexpr const char* TAG = "Injection";

// Run a shell command, return exit status (0 = success)
int run_cmd(const std::string& cmd) {
    int ret = std::system(cmd.c_str());
    return WIFEXITED(ret) ? WEXITSTATUS(ret) : -1;
}

// Save current clipboard contents
std::string get_clipboard() {
    std::string result;
    FILE* pipe = popen("xclip -selection clipboard -o 2>/dev/null", "r");
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

// Set clipboard contents (writes via stdin — no shell injection risk)
bool set_clipboard(const std::string& text) {
    FILE* pipe = popen("xclip -selection clipboard 2>/dev/null", "w");
    if (!pipe) {
        pipe = popen("xsel --clipboard --input 2>/dev/null", "w");
    }
    if (!pipe) return false;

    fwrite(text.c_str(), 1, text.size(), pipe);
    int status = pclose(pipe);
    return WIFEXITED(status) && WEXITSTATUS(status) == 0;
}

// Get the WM_CLASS of the currently focused window using xdotool+xprop
std::string get_active_window_class() {
    // Use xdotool to get the active window — this respects the window manager's
    // notion of focus, not just X11 input focus
    FILE* pipe = popen("xdotool getactivewindow 2>/dev/null", "r");
    if (!pipe) return "";

    char buf[64];
    std::string wid_str;
    if (fgets(buf, sizeof(buf), pipe)) {
        wid_str = buf;
        // Trim newline
        while (!wid_str.empty() && (wid_str.back() == '\n' || wid_str.back() == '\r'))
            wid_str.pop_back();
    }
    pclose(pipe);

    if (wid_str.empty()) return "";

    std::string cmd = "xprop -id " + wid_str + " WM_CLASS 2>/dev/null";
    pipe = popen(cmd.c_str(), "r");
    if (!pipe) return "";

    std::string output;
    while (fgets(buf, sizeof(buf), pipe)) {
        output += buf;
    }
    pclose(pipe);

    return output;
}

// Check if the active window is a terminal emulator
bool is_terminal_window() {
    std::string wm_class = get_active_window_class();
    if (wm_class.empty()) return false;

    LOG_INFO("Injection", "Active window WM_CLASS: " + wm_class);

    // Common terminal emulator WM_CLASS values
    // Also includes VS Code / Codium — their integrated terminal needs
    // Ctrl+Shift+V, and Ctrl+Shift+V also works in their editor (pastes
    // without formatting), so it's safe to treat the whole app as "terminal"
    static const char* terminals[] = {
        "gnome-terminal", "xterm", "urxvt", "rxvt", "konsole",
        "alacritty", "kitty", "terminator", "tilix", "st-256color",
        "xfce4-terminal", "mate-terminal", "lxterminal",
        "cosmic-term", "wezterm", "foot", "sakura", "guake",
        "terminal", "Terminal",
        "code", "Code", "code-oss", "vscodium",
        nullptr
    };

    // Convert to lowercase for matching
    std::string lower = wm_class;
    for (auto& c : lower) c = static_cast<char>(std::tolower(c));

    for (int i = 0; terminals[i]; ++i) {
        std::string term_lower = terminals[i];
        for (auto& c : term_lower) c = static_cast<char>(std::tolower(c));
        if (lower.find(term_lower) != std::string::npos) {
            return true;
        }
    }
    return false;
}

} // namespace

XdoInjectionService::XdoInjectionService() = default;

XdoInjectionService::~XdoInjectionService() {
    stop();
}

Result<void> XdoInjectionService::start() {
    if (running_.load()) return Result<void>::ok();

    // Warn if running under Wayland
    const char* session_type = std::getenv("XDG_SESSION_TYPE");
    if (session_type && std::string(session_type) == "wayland") {
        LOG_WARN(TAG, "Running under Wayland! Text injection may not work with native Wayland apps. "
                       "Switch to an X11 session for reliable text injection.");
        wayland_ = true;
    }

    // Check for xclip
    if (run_cmd("which xclip >/dev/null 2>&1") == 0) {
        has_xclip_ = true;
        LOG_INFO(TAG, "xclip found — clipboard paste available");
    } else if (run_cmd("which xsel >/dev/null 2>&1") == 0) {
        has_xclip_ = true;
        LOG_INFO(TAG, "xsel found — clipboard paste available");
    } else {
        LOG_WARN(TAG, "Neither xclip nor xsel found. Install: sudo apt install xclip");
    }

    // Check for xdotool CLI
    if (run_cmd("which xdotool >/dev/null 2>&1") == 0) {
        has_xdotool_cli_ = true;
        LOG_INFO(TAG, "xdotool CLI found");
    }

    xdo_ = xdo_new(nullptr);
    if (!xdo_) {
        return Result<void>::err("Failed to create xdo context. Is X11 running?");
    }

    running_.store(true, std::memory_order_release);
    LOG_INFO(TAG, "Injection service started");
    return Result<void>::ok();
}

void XdoInjectionService::stop() {
    running_.store(false, std::memory_order_release);
    if (xdo_) {
        xdo_free(xdo_);
        xdo_ = nullptr;
    }
    LOG_INFO(TAG, "Injection service stopped");
}

Result<void> XdoInjectionService::inject_via_clipboard_paste(const std::string& text, Window /*window*/) {
    // Save current clipboard
    std::string saved_clipboard = get_clipboard();

    // Copy our text to clipboard
    if (!set_clipboard(text)) {
        return Result<void>::err("Failed to set clipboard content");
    }

    // Let clipboard settle
    std::this_thread::sleep_for(std::chrono::milliseconds(100));

    // Determine paste shortcut — terminals use Ctrl+Shift+V, other apps use Ctrl+V
    bool is_term = is_terminal_window();
    const char* paste_key = is_term ? "ctrl+shift+v" : "ctrl+v";
    LOG_INFO(TAG, std::string("Sending ") + paste_key +
                  (is_term ? " (terminal detected)" : " (non-terminal)"));

    // Use xdotool CLI WITHOUT --window — lets xdotool send to the actual
    // focused input widget, not just the top-level window frame
    std::string cmd = std::string("xdotool key --clearmodifiers ") + paste_key;
    int ret = run_cmd(cmd);

    // Give paste time to complete
    std::this_thread::sleep_for(std::chrono::milliseconds(200));

    // Restore original clipboard
    if (!saved_clipboard.empty()) {
        set_clipboard(saved_clipboard);
    }

    if (ret != 0) {
        return Result<void>::err("xdotool key paste failed (exit " + std::to_string(ret) + ")");
    }

    return Result<void>::ok();
}

Result<void> XdoInjectionService::inject_via_xdotool_type(const std::string& text, Window /*window*/) {
    // Use xdotool type via CLI with stdin — no --window, sends to focused widget
    FILE* pipe = popen("xdotool type --clearmodifiers --delay 12 --file -", "w");
    if (!pipe) {
        return Result<void>::err("Failed to launch xdotool type");
    }

    fwrite(text.c_str(), 1, text.size(), pipe);
    int status = pclose(pipe);

    if (!WIFEXITED(status) || WEXITSTATUS(status) != 0) {
        return Result<void>::err("xdotool type failed (exit " +
                                 std::to_string(WEXITSTATUS(status)) + ")");
    }

    return Result<void>::ok();
}

Result<void> XdoInjectionService::inject_via_xdo_lib(const std::string& text, Window window) {
    charcodemap_t* active_mods = nullptr;
    int nkeys = 0;
    xdo_get_active_modifiers(xdo_, &active_mods, &nkeys);
    if (active_mods && nkeys > 0) {
        xdo_clear_active_modifiers(xdo_, window, active_mods, nkeys);
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    int ret = xdo_enter_text_window(xdo_, window, text.c_str(), 12000);

    if (active_mods && nkeys > 0) {
        xdo_set_active_modifiers(xdo_, window, active_mods, nkeys);
    }
    free(active_mods);

    if (ret != 0) {
        return Result<void>::err("xdo_enter_text_window failed (code " + std::to_string(ret) + ")");
    }

    return Result<void>::ok();
}

Result<void> XdoInjectionService::inject_text(const std::string& text) {
    if (!xdo_ || !running_.load()) {
        return Result<void>::err("Injection service not running");
    }

    if (text.empty()) {
        return Result<void>::ok();
    }

    Window focused = 0;
    xdo_get_focused_window_sane(xdo_, &focused);

    if (focused == 0) {
        return Result<void>::err("No focused window");
    }

    LOG_INFO(TAG, "Injecting into window " + std::to_string(focused) + ": \"" + text + "\"");

    // Strategy 1: Clipboard paste (Ctrl+V / Ctrl+Shift+V) — most reliable
    if (has_xclip_ && has_xdotool_cli_) {
        LOG_INFO(TAG, "Trying clipboard paste...");
        auto result = inject_via_clipboard_paste(text, focused);
        if (result.is_ok()) {
            last_injection_text_ = text;
            last_injection_len_ = text.size();
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via clipboard paste");
            return result;
        }
        LOG_WARN(TAG, "Clipboard paste failed: " + result.error());
    }

    // Strategy 2: xdotool type CLI (synthetic key events via CLI)
    if (has_xdotool_cli_) {
        LOG_INFO(TAG, "Trying xdotool type CLI...");
        auto result = inject_via_xdotool_type(text, focused);
        if (result.is_ok()) {
            last_injection_text_ = text;
            last_injection_len_ = text.size();
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via xdotool type");
            return result;
        }
        LOG_WARN(TAG, "xdotool type failed: " + result.error());
    }

    // Strategy 3: libxdo library call (last resort)
    LOG_INFO(TAG, "Trying libxdo library...");
    auto result = inject_via_xdo_lib(text, focused);
    if (result.is_ok()) {
        last_injection_text_ = text;
        last_injection_len_ = text.size();
        LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via libxdo");
        return result;
    }

    LOG_ERROR(TAG, "All injection methods failed: " + result.error());
    return result;
}

bool XdoInjectionService::has_focused_input() {
    if (!xdo_) return false;

    Window focused = 0;
    xdo_get_focused_window_sane(xdo_, &focused);
    return focused != 0;
}

Result<void> XdoInjectionService::replace_last_injection(const std::string& new_text) {
    if (!xdo_ || !running_.load()) {
        return Result<void>::err("Injection service not running");
    }

    Window focused = 0;
    xdo_get_focused_window_sane(xdo_, &focused);

    if (focused == 0) {
        return Result<void>::err("No focused window");
    }

    // Delete old text using backspaces via CLI (no --window for reliability)
    if (has_xdotool_cli_ && last_injection_len_ > 0) {
        std::string cmd = "xdotool key --clearmodifiers --repeat " +
                          std::to_string(last_injection_len_) + " BackSpace";
        run_cmd(cmd);
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    // Inject the new text
    if (!new_text.empty()) {
        // Temporarily clear tracking so inject_text sets it fresh
        last_injection_len_ = 0;
        last_injection_text_.clear();
        return inject_text(new_text);
    }

    last_injection_text_.clear();
    last_injection_len_ = 0;
    return Result<void>::ok();
}

} // namespace verbal
