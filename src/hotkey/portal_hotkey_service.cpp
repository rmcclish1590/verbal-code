#include "portal_hotkey_service.hpp"

#include <algorithm>

namespace verbal {

namespace {
constexpr const char* TAG = "PortalHotkey";
constexpr const char* PORTAL_BUS_NAME = "org.freedesktop.portal.Desktop";
constexpr const char* PORTAL_OBJECT_PATH = "/org/freedesktop/portal/desktop";
constexpr const char* SHORTCUTS_INTERFACE = "org.freedesktop.portal.GlobalShortcuts";
} // namespace

PortalHotkeyService::PortalHotkeyService() = default;

PortalHotkeyService::~PortalHotkeyService() {
    stop();
}

std::string PortalHotkeyService::build_shortcut_string(
    const std::vector<std::string>& modifiers,
    const std::string& trigger_key)
{
    std::string result;
    for (const auto& mod : modifiers) {
        std::string lower = mod;
        std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower);
        if (lower == "ctrl")       result += "<ctrl>";
        else if (lower == "alt")   result += "<alt>";
        else if (lower == "super") result += "<super>";
        else if (lower == "shift") result += "<shift>";
    }
    result += trigger_key;
    return result;
}

Result<void> PortalHotkeyService::start() {
    if (running_.load()) return Result<void>::ok();

    GError* error = nullptr;
    connection_ = g_bus_get_sync(G_BUS_TYPE_SESSION, nullptr, &error);
    if (!connection_) {
        std::string msg = "Failed to connect to session bus";
        if (error) {
            msg += std::string(": ") + error->message;
            g_error_free(error);
        }
        return Result<void>::err(msg);
    }

    running_.store(true, std::memory_order_release);

    dbus_thread_ = std::thread(&PortalHotkeyService::dbus_thread_func, this);

    LOG_INFO(TAG, "Portal hotkey service started");
    return Result<void>::ok();
}

void PortalHotkeyService::stop() {
    running_.store(false, std::memory_order_release);

    if (loop_) {
        g_main_loop_quit(loop_);
    }

    if (dbus_thread_.joinable()) {
        dbus_thread_.join();
    }

    if (signal_subscription_ && connection_) {
        g_dbus_connection_signal_unsubscribe(connection_, signal_subscription_);
        signal_subscription_ = 0;
    }

    if (connection_) {
        g_object_unref(connection_);
        connection_ = nullptr;
    }

    LOG_INFO(TAG, "Portal hotkey service stopped");
}

void PortalHotkeyService::set_modifiers(const std::vector<std::string>& modifiers) {
    std::lock_guard<std::mutex> lock(modifier_mutex_);
    modifiers_ = modifiers;
    // If already running, rebind shortcuts
    if (running_.load() && connection_) {
        bind_shortcuts();
    }
}

void PortalHotkeyService::dbus_thread_func() {
    create_session();

    loop_ = g_main_loop_new(nullptr, FALSE);
    g_main_loop_run(loop_);
    g_main_loop_unref(loop_);
    loop_ = nullptr;
}

void PortalHotkeyService::create_session() {
    GError* error = nullptr;

    // Build options for CreateSession
    GVariantBuilder options;
    g_variant_builder_init(&options, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&options, "{sv}", "handle_token",
                          g_variant_new_string("verbal_code_hotkey"));
    g_variant_builder_add(&options, "{sv}", "session_handle_token",
                          g_variant_new_string("verbal_code_session"));

    GVariant* result = g_dbus_connection_call_sync(
        connection_,
        PORTAL_BUS_NAME,
        PORTAL_OBJECT_PATH,
        SHORTCUTS_INTERFACE,
        "CreateSession",
        g_variant_new("(a{sv})", &options),
        G_VARIANT_TYPE("(o)"),
        G_DBUS_CALL_FLAGS_NONE,
        5000,
        nullptr,
        &error
    );

    if (error) {
        LOG_ERROR(TAG, std::string("CreateSession failed: ") + error->message);
        g_error_free(error);
        return;
    }

    if (result) {
        const gchar* request_path = nullptr;
        g_variant_get(result, "(o)", &request_path);
        LOG_INFO(TAG, std::string("CreateSession request: ") + (request_path ? request_path : "null"));
        g_variant_unref(result);
    }

    // The session handle follows a predictable pattern
    const char* sender = g_dbus_connection_get_unique_name(connection_);
    if (sender) {
        std::string sender_str(sender);
        // Replace ':' and '.' with '_'
        for (auto& c : sender_str) {
            if (c == ':' || c == '.') c = '_';
        }
        session_handle_ = "/org/freedesktop/portal/desktop/session/"
                         + sender_str + "/verbal_code_session";
    }

    // Subscribe to Activated/Deactivated signals
    signal_subscription_ = g_dbus_connection_signal_subscribe(
        connection_,
        PORTAL_BUS_NAME,
        SHORTCUTS_INTERFACE,
        nullptr, // all signals from this interface
        nullptr, // any object path
        nullptr, // any arg0
        G_DBUS_SIGNAL_FLAGS_NONE,
        on_signal,
        this,
        nullptr
    );

    // Bind shortcuts after session creation
    bind_shortcuts();
}

void PortalHotkeyService::bind_shortcuts() {
    if (session_handle_.empty()) {
        LOG_WARN(TAG, "No session handle, cannot bind shortcuts");
        return;
    }

    std::lock_guard<std::mutex> lock(modifier_mutex_);
    std::string shortcut = build_shortcut_string(modifiers_, trigger_key_);

    LOG_INFO(TAG, "Binding shortcut: " + shortcut);

    GError* error = nullptr;

    // Build shortcuts array: a(sa{sv})
    GVariantBuilder shortcuts;
    g_variant_builder_init(&shortcuts, G_VARIANT_TYPE("a(sa{sv})"));

    GVariantBuilder shortcut_props;
    g_variant_builder_init(&shortcut_props, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&shortcut_props, "{sv}", "description",
                          g_variant_new_string("Push-to-talk for verbal-code"));
    g_variant_builder_add(&shortcut_props, "{sv}", "preferred_trigger",
                          g_variant_new_string(shortcut.c_str()));

    g_variant_builder_add(&shortcuts, "(sa{sv})", "verbal-code-ptt", &shortcut_props);

    // Options
    GVariantBuilder options;
    g_variant_builder_init(&options, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&options, "{sv}", "handle_token",
                          g_variant_new_string("verbal_code_bind"));

    GVariant* result = g_dbus_connection_call_sync(
        connection_,
        PORTAL_BUS_NAME,
        PORTAL_OBJECT_PATH,
        SHORTCUTS_INTERFACE,
        "BindShortcuts",
        g_variant_new("(oa(sa{sv})a{sv})", session_handle_.c_str(), &shortcuts, &options),
        G_VARIANT_TYPE("(o)"),
        G_DBUS_CALL_FLAGS_NONE,
        5000,
        nullptr,
        &error
    );

    if (error) {
        LOG_ERROR(TAG, std::string("BindShortcuts failed: ") + error->message);
        g_error_free(error);
        return;
    }

    if (result) {
        g_variant_unref(result);
    }

    LOG_INFO(TAG, "Shortcuts bound successfully");
}

void PortalHotkeyService::on_signal(
    GDBusConnection* /*connection*/,
    const gchar* /*sender_name*/,
    const gchar* /*object_path*/,
    const gchar* /*interface_name*/,
    const gchar* signal_name,
    GVariant* /*parameters*/,
    gpointer user_data)
{
    auto* self = static_cast<PortalHotkeyService*>(user_data);

    if (!self->running_.load()) return;

    std::string signal(signal_name ? signal_name : "");

    if (signal == "Activated") {
        LOG_INFO(TAG, "Hotkey activated");
        self->pressed_.store(true, std::memory_order_release);
        if (self->on_press_) {
            self->on_press_();
        }
    } else if (signal == "Deactivated") {
        LOG_INFO(TAG, "Hotkey deactivated");
        self->pressed_.store(false, std::memory_order_release);
        if (self->on_release_) {
            self->on_release_();
        }
    }
}

} // namespace verbal
