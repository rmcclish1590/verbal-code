#include "xdo_injection_service.hpp"
#include "injection_utils.hpp"

#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <thread>
#include <unordered_set>

namespace verbal {

namespace {
constexpr const char* TAG = "Injection";

constexpr auto CLIPBOARD_SETTLE_MS = std::chrono::milliseconds(100);
constexpr auto POST_PASTE_SETTLE_MS = std::chrono::milliseconds(200);
constexpr auto MODIFIER_CLEAR_SETTLE_MS = std::chrono::milliseconds(100);
constexpr int XDOTOOL_KEY_DELAY_US = 12000;
constexpr auto POST_DELETE_SETTLE_MS = std::chrono::milliseconds(50);
constexpr size_t MAX_INJECTION_LEN = 10000;

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
    FILE* pipe = popen("xdotool getactivewindow 2>/dev/null", "r");
    if (!pipe) return "";

    char buf[64];
    std::string wid_str;
    if (fgets(buf, sizeof(buf), pipe)) {
        wid_str = buf;
        while (!wid_str.empty() && (wid_str.back() == '\n' || wid_str.back() == '\r'))
            wid_str.pop_back();
    }
    pclose(pipe);

    if (wid_str.empty()) return "";

    // Validate window ID contains only digits to prevent shell injection
    for (char c : wid_str) {
        if (!std::isdigit(static_cast<unsigned char>(c))) return "";
    }

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

// Terminal emulator WM_CLASS values (also includes VS Code — its integrated
// terminal needs Ctrl+Shift+V, which also works in the editor)
const std::unordered_set<std::string> TERMINAL_CLASSES = {
    "gnome-terminal", "xterm", "urxvt", "rxvt", "konsole",
    "alacritty", "kitty", "terminator", "tilix", "st-256color",
    "xfce4-terminal", "mate-terminal", "lxterminal",
    "cosmic-term", "wezterm", "foot", "sakura", "guake",
    "terminal", "code", "code-oss", "vscodium"
};

// Check if the active window is a terminal emulator
bool is_terminal_window() {
    std::string wm_class = get_active_window_class();
    if (wm_class.empty()) return false;

    LOG_DEBUG("Injection", "Active window WM_CLASS: " + wm_class);

    // Convert to lowercase for matching
    std::string lower = wm_class;
    for (auto& c : lower) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));

    for (const auto& term : TERMINAL_CLASSES) {
        if (lower.find(term) != std::string::npos) {
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
    }

    // Check for xclip
    if (injection::command_exists("xclip")) {
        has_xclip_ = true;
        LOG_INFO(TAG, "xclip found — clipboard paste available");
    } else if (injection::command_exists("xsel")) {
        has_xclip_ = true;
        LOG_INFO(TAG, "xsel found — clipboard paste available");
    } else {
        LOG_WARN(TAG, "Neither xclip nor xsel found. Install: sudo apt install xclip");
    }

    // Check for xdotool CLI
    if (injection::command_exists("xdotool")) {
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
    if (!running_.exchange(false)) return;
    if (xdo_) {
        xdo_free(xdo_);
        xdo_ = nullptr;
    }
    LOG_INFO(TAG, "Injection service stopped");
}

Result<void> XdoInjectionService::inject_via_clipboard_paste(const std::string& text, Window /*window*/) {
    std::string saved_clipboard = get_clipboard();

    if (!set_clipboard(text)) {
        return Result<void>::err("Failed to set clipboard content");
    }

    std::this_thread::sleep_for(CLIPBOARD_SETTLE_MS);

    bool is_term = is_terminal_window();
    const char* paste_key = is_term ? "ctrl+shift+v" : "ctrl+v";
    LOG_DEBUG(TAG, std::string("Sending ") + paste_key +
                  (is_term ? " (terminal detected)" : " (non-terminal)"));

    std::string cmd = std::string("xdotool key --clearmodifiers ") + paste_key;
    int ret = injection::run_cmd(cmd);

    std::this_thread::sleep_for(POST_PASTE_SETTLE_MS);

    if (!saved_clipboard.empty()) {
        set_clipboard(saved_clipboard);
    }

    if (ret != 0) {
        return Result<void>::err("xdotool key paste failed (exit " + std::to_string(ret) + ")");
    }

    return Result<void>::ok();
}

Result<void> XdoInjectionService::inject_via_xdotool_type(const std::string& text, Window /*window*/) {
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
        std::this_thread::sleep_for(MODIFIER_CLEAR_SETTLE_MS);
    }

    int ret = xdo_enter_text_window(xdo_, window, text.c_str(), XDOTOOL_KEY_DELAY_US);

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

    LOG_DEBUG(TAG, "Injecting into window " + std::to_string(focused) + ": " + std::to_string(text.size()) + " chars");

    // Try strategies in priority order
    Result<void> result = Result<void>::err("No injection strategy available");

    if (has_xclip_ && has_xdotool_cli_) {
        LOG_INFO(TAG, "Trying clipboard paste...");
        result = inject_via_clipboard_paste(text, focused);
        if (result.is_ok()) {
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via clipboard paste");
        } else {
            LOG_WARN(TAG, "Clipboard paste failed: " + result.error());
        }
    }

    if (result.is_err() && has_xdotool_cli_) {
        LOG_INFO(TAG, "Trying xdotool type CLI...");
        result = inject_via_xdotool_type(text, focused);
        if (result.is_ok()) {
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via xdotool type");
        } else {
            LOG_WARN(TAG, "xdotool type failed: " + result.error());
        }
    }

    if (result.is_err()) {
        LOG_INFO(TAG, "Trying libxdo library...");
        result = inject_via_xdo_lib(text, focused);
        if (result.is_ok()) {
            LOG_INFO(TAG, "Injected " + std::to_string(text.size()) + " chars via libxdo");
        } else {
            LOG_ERROR(TAG, "All injection methods failed: " + result.error());
        }
    }

    if (result.is_ok()) {
        last_injection_len_ = std::min(text.size(), MAX_INJECTION_LEN);
    }

    return result;
}

bool XdoInjectionService::has_focused_input() const {
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

    // Delete old text using backspaces via CLI
    if (has_xdotool_cli_ && last_injection_len_ > 0) {
        std::string cmd = "xdotool key --clearmodifiers --repeat " +
                          std::to_string(last_injection_len_) + " BackSpace";
        injection::run_cmd(cmd);
        std::this_thread::sleep_for(POST_DELETE_SETTLE_MS);
    }

    // Inject the new text
    if (!new_text.empty()) {
        last_injection_len_ = 0;
        return inject_text(new_text);
    }

    last_injection_len_ = 0;
    return Result<void>::ok();
}

} // namespace verbal
