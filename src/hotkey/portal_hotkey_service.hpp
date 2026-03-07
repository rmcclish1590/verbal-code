#pragma once

#include "i_hotkey_service.hpp"
#include "logger.hpp"

#include <gio/gio.h>

#include <atomic>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

namespace verbal {

class PortalHotkeyService : public IHotkeyService {
public:
    PortalHotkeyService();
    ~PortalHotkeyService() override;

    // IService
    Result<void> start() override;
    void stop() override;
    bool is_running() const override { return running_.load(std::memory_order_acquire); }

    // IHotkeyService
    void set_modifiers(const std::vector<std::string>& modifiers) override;
    void set_on_press(VoidCallback cb) override { on_press_ = std::move(cb); }
    void set_on_release(VoidCallback cb) override { on_release_ = std::move(cb); }
    bool is_pressed() const override { return pressed_.load(std::memory_order_acquire); }

    // Set the trigger key (e.g., "v")
    void set_trigger_key(const std::string& key) { trigger_key_ = key; }

    // For testing: build portal shortcut string from modifiers + trigger key
    static std::string build_shortcut_string(const std::vector<std::string>& modifiers,
                                             const std::string& trigger_key);

private:
    void dbus_thread_func();
    void create_session();
    void bind_shortcuts();

    static void on_signal(GDBusConnection* connection,
                         const gchar* sender_name,
                         const gchar* object_path,
                         const gchar* interface_name,
                         const gchar* signal_name,
                         GVariant* parameters,
                         gpointer user_data);

    std::vector<std::string> modifiers_;
    std::string trigger_key_ = "v";
    mutable std::mutex modifier_mutex_;

    VoidCallback on_press_;
    VoidCallback on_release_;

    GDBusConnection* connection_ = nullptr;
    GMainLoop* loop_ = nullptr;
    std::string session_handle_;
    guint signal_subscription_ = 0;

    std::thread dbus_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> pressed_{false};
};

} // namespace verbal
