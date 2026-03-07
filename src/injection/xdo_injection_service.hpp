#pragma once

#include "i_injection_service.hpp"
#include "logger.hpp"

extern "C" {
#include <xdo.h>
}

#include <atomic>
#include <string>

namespace verbal {

// X11 text injection service using libxdo.
// Uses three fallback strategies: clipboard paste, xdotool type CLI, libxdo library.
class XdoInjectionService : public IInjectionService {
public:
    XdoInjectionService();
    ~XdoInjectionService() override;

    // IService
    Result<void> start() override;
    void stop() override;
    bool is_running() const override { return running_.load(std::memory_order_acquire); }

    // IInjectionService
    Result<void> inject_text(const std::string& text) override;
    bool has_focused_input() const override;
    Result<void> replace_last_injection(const std::string& new_text) override;
    size_t last_injection_length() const override { return last_injection_len_; }

private:
    Result<void> inject_via_clipboard_paste(const std::string& text, Window window);
    Result<void> inject_via_xdotool_type(const std::string& text, Window window);
    Result<void> inject_via_xdo_lib(const std::string& text, Window window);

    xdo_t* xdo_ = nullptr;
    std::atomic<bool> running_{false};
    bool has_xclip_ = false;
    bool has_xdotool_cli_ = false;
    size_t last_injection_len_ = 0;
};

} // namespace verbal
