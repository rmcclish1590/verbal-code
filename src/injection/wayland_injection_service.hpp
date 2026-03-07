#pragma once

#include "i_injection_service.hpp"
#include "logger.hpp"

#include <atomic>
#include <string>

namespace verbal {

class WaylandInjectionService : public IInjectionService {
public:
    WaylandInjectionService();
    ~WaylandInjectionService() override;

    // IService
    Result<void> start() override;
    void stop() override;
    bool is_running() const override { return running_.load(std::memory_order_acquire); }

    // IInjectionService
    Result<void> inject_text(const std::string& text) override;
    bool has_focused_input() override;
    Result<void> replace_last_injection(const std::string& new_text) override;
    size_t last_injection_length() const override { return last_injection_len_; }

    // For testing: build the paste command string
    static std::string build_paste_command(bool is_terminal);
    // For testing: build the backspace command string
    static std::string build_backspace_command(size_t count);

private:
    Result<void> inject_via_wtype(const std::string& text);
    Result<void> inject_via_clipboard(const std::string& text);
    std::string get_clipboard();
    bool set_clipboard(const std::string& text);

    std::atomic<bool> running_{false};
    bool has_wl_copy_ = false;
    bool has_wl_paste_ = false;
    bool has_ydotool_ = false;
    bool has_wtype_ = false;
    size_t last_injection_len_ = 0;
    std::string last_injection_text_;
};

} // namespace verbal
