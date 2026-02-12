#include "gtk_overlay_service.hpp"

#include <gdk/gdk.h>

#include <algorithm>

namespace verbal {

namespace {
constexpr const char* TAG = "Overlay";

// Colors
constexpr double IDLE_R = 0.5, IDLE_G = 0.5, IDLE_B = 0.5;       // #808080
constexpr double REC_R  = 0.0, REC_G  = 0.8, REC_B  = 0.0;       // #00CC00
} // namespace

GtkOverlayService::GtkOverlayService(int size)
    : dot_size_(size)
{
}

GtkOverlayService::~GtkOverlayService() {
    stop();
}

Result<void> GtkOverlayService::start() {
    if (running_.load()) return Result<void>::ok();

    create_window();

    if (!window_) {
        return Result<void>::err("Failed to create GTK overlay window");
    }

    running_.store(true, std::memory_order_release);
    LOG_INFO(TAG, "GTK overlay service started");
    return Result<void>::ok();
}

void GtkOverlayService::stop() {
    running_.store(false, std::memory_order_release);
    if (window_) {
        gtk_widget_destroy(window_);
        window_ = nullptr;
    }
    LOG_INFO(TAG, "GTK overlay service stopped");
}

void GtkOverlayService::create_window() {
    window_ = gtk_window_new(GTK_WINDOW_TOPLEVEL);
    gtk_window_set_default_size(GTK_WINDOW(window_), window_size_, window_size_);
    gtk_widget_set_size_request(window_, window_size_, window_size_);
    gtk_window_set_resizable(GTK_WINDOW(window_), FALSE);
    gtk_window_set_decorated(GTK_WINDOW(window_), FALSE);
    gtk_widget_set_app_paintable(window_, TRUE);

    // DOCK type hint: always on top, no taskbar entry, not covered by other windows
    gtk_window_set_type_hint(GTK_WINDOW(window_), GDK_WINDOW_TYPE_HINT_DOCK);
    gtk_window_set_keep_above(GTK_WINDOW(window_), TRUE);
    gtk_window_set_skip_taskbar_hint(GTK_WINDOW(window_), TRUE);
    gtk_window_set_skip_pager_hint(GTK_WINDOW(window_), TRUE);
    gtk_window_stick(GTK_WINDOW(window_)); // visible on all workspaces
    gtk_window_set_accept_focus(GTK_WINDOW(window_), FALSE);

    // Transparent background
    GdkScreen* screen = gtk_widget_get_screen(window_);
    GdkVisual* visual = gdk_screen_get_rgba_visual(screen);
    if (visual) {
        gtk_widget_set_visual(window_, visual);
    }

    // Connect signals
    g_signal_connect(window_, "draw", G_CALLBACK(on_draw), this);
    g_signal_connect(window_, "button-press-event", G_CALLBACK(on_button_press), this);
    g_signal_connect(window_, "button-release-event", G_CALLBACK(on_button_release), this);
    g_signal_connect(window_, "motion-notify-event", G_CALLBACK(on_motion_notify), this);
    g_signal_connect(window_, "configure-event", G_CALLBACK(on_configure), this);

    // Enable button + motion + structure events
    gtk_widget_add_events(window_, GDK_BUTTON_PRESS_MASK | GDK_BUTTON_RELEASE_MASK
                                 | GDK_POINTER_MOTION_MASK | GDK_STRUCTURE_MASK);

    // Set position
    if (x_ < 0 || y_ < 0) {
        update_position_default();
    }
    gtk_window_move(GTK_WINDOW(window_), x_, y_);
}

void GtkOverlayService::update_position_default() {
    GdkDisplay* display = gdk_display_get_default();
    if (display) {
        GdkMonitor* monitor = gdk_display_get_primary_monitor(display);
        if (!monitor) {
            monitor = gdk_display_get_monitor(display, 0);
        }
        if (monitor) {
            GdkRectangle workarea;
            gdk_monitor_get_workarea(monitor, &workarea);
            x_ = workarea.x + (workarea.width - window_size_) / 2;
            y_ = workarea.y + (workarea.height - window_size_) / 2;
            return;
        }
    }
    x_ = 100;
    y_ = 100;
}

void GtkOverlayService::show() {
    if (window_) {
        gtk_widget_show_all(window_);
        if (x_ >= 0 && y_ >= 0) {
            gtk_window_move(GTK_WINDOW(window_), x_, y_);
        }
    }
}

void GtkOverlayService::hide() {
    if (window_) {
        gtk_widget_hide(window_);
    }
}

void GtkOverlayService::set_state(OverlayState state) {
    state_ = state;
    if (window_) {
        gtk_widget_queue_draw(window_);
    }
}

void GtkOverlayService::set_position(int x, int y) {
    x_ = x;
    y_ = y;
    if (window_) {
        gtk_window_move(GTK_WINDOW(window_), x_, y_);
    }
}

gboolean GtkOverlayService::on_draw(GtkWidget* widget, cairo_t* cr, gpointer data) {
    auto* self = static_cast<GtkOverlayService*>(data);

    int width = gtk_widget_get_allocated_width(widget);
    int height = gtk_widget_get_allocated_height(widget);

    // Clear background (transparent)
    cairo_set_source_rgba(cr, 0, 0, 0, 0);
    cairo_set_operator(cr, CAIRO_OPERATOR_SOURCE);
    cairo_paint(cr);

    // Draw filled circle (dot_size_ centered in window)
    cairo_set_operator(cr, CAIRO_OPERATOR_OVER);
    double cx = width / 2.0;
    double cy = height / 2.0;
    double radius = self->dot_size_ / 2.0;

    if (self->state_ == OverlayState::RECORDING) {
        cairo_set_source_rgb(cr, REC_R, REC_G, REC_B);
    } else {
        cairo_set_source_rgb(cr, IDLE_R, IDLE_G, IDLE_B);
    }

    cairo_arc(cr, cx, cy, radius, 0, 2 * G_PI);
    cairo_fill(cr);

    // White outline for visibility
    cairo_set_source_rgb(cr, 1.0, 1.0, 1.0);
    cairo_set_line_width(cr, 2.0);
    cairo_arc(cr, cx, cy, radius, 0, 2 * G_PI);
    cairo_stroke(cr);

    return FALSE;
}

gboolean GtkOverlayService::on_button_press(GtkWidget* /*widget*/, GdkEventButton* event, gpointer data) {
    auto* self = static_cast<GtkOverlayService*>(data);

    if (event->button == 1) {
        // Left-click: begin manual drag (WM move drag doesn't work with DOCK hint)
        self->dragging_ = true;
        self->drag_offset_x_ = event->x;
        self->drag_offset_y_ = event->y;
    } else if (event->button == 3) {
        // Right-click: show context menu
        self->show_context_menu(event);
    }

    return TRUE;
}

gboolean GtkOverlayService::on_button_release(GtkWidget* /*widget*/, GdkEventButton* event, gpointer data) {
    auto* self = static_cast<GtkOverlayService*>(data);

    if (event->button == 1 && self->dragging_) {
        self->dragging_ = false;
        if (self->on_position_changed_) {
            self->on_position_changed_(self->x_, self->y_);
        }
    }

    return TRUE;
}

gboolean GtkOverlayService::on_motion_notify(GtkWidget* widget, GdkEventMotion* event, gpointer data) {
    auto* self = static_cast<GtkOverlayService*>(data);

    if (self->dragging_) {
        int new_x = static_cast<int>(event->x_root - self->drag_offset_x_);
        int new_y = static_cast<int>(event->y_root - self->drag_offset_y_);
        gtk_window_move(GTK_WINDOW(widget), new_x, new_y);
    }

    return TRUE;
}

gboolean GtkOverlayService::on_configure(GtkWidget* /*widget*/, GdkEventConfigure* event, gpointer data) {
    auto* self = static_cast<GtkOverlayService*>(data);

    self->x_ = event->x;
    self->y_ = event->y;

    if (self->dragging_ && self->on_position_changed_) {
        self->on_position_changed_(event->x, event->y);
    }

    return FALSE;
}

void GtkOverlayService::show_context_menu(GdkEventButton* event) {
    GtkWidget* menu = gtk_menu_new();

    // "Set Hotkeys" item
    GtkWidget* hotkey_item = gtk_menu_item_new_with_label("Set Hotkeys");
    g_signal_connect_swapped(hotkey_item, "activate",
        G_CALLBACK(+[](gpointer data) {
            auto* self = static_cast<GtkOverlayService*>(data);
            self->show_hotkey_dialog();
        }), this);
    gtk_menu_shell_append(GTK_MENU_SHELL(menu), hotkey_item);

    // Separator
    gtk_menu_shell_append(GTK_MENU_SHELL(menu), gtk_separator_menu_item_new());

    // "Quit" item
    GtkWidget* quit_item = gtk_menu_item_new_with_label("Quit");
    g_signal_connect_swapped(quit_item, "activate",
        G_CALLBACK(+[](gpointer data) {
            auto* self = static_cast<GtkOverlayService*>(data);
            if (self->on_quit_requested_) {
                self->on_quit_requested_();
            }
        }), this);
    gtk_menu_shell_append(GTK_MENU_SHELL(menu), quit_item);

    gtk_widget_show_all(menu);
    gtk_menu_popup_at_pointer(GTK_MENU(menu), reinterpret_cast<const GdkEvent*>(event));
}

void GtkOverlayService::show_hotkey_dialog() {
    GtkWidget* dialog = gtk_dialog_new_with_buttons(
        "Set Hotkeys",
        nullptr,
        GTK_DIALOG_MODAL,
        "Cancel", GTK_RESPONSE_CANCEL,
        "OK", GTK_RESPONSE_OK,
        nullptr
    );

    GtkWidget* content = gtk_dialog_get_content_area(GTK_DIALOG(dialog));
    gtk_container_set_border_width(GTK_CONTAINER(content), 12);

    GtkWidget* label = gtk_label_new("Select modifier keys for the hotkey:");
    gtk_container_add(GTK_CONTAINER(content), label);

    // Check which modifiers are currently active
    auto has_mod = [this](const std::string& mod) {
        return std::find(current_modifiers_.begin(), current_modifiers_.end(), mod)
               != current_modifiers_.end();
    };

    GtkWidget* ctrl_check = gtk_check_button_new_with_label("Ctrl");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(ctrl_check), has_mod("ctrl"));
    gtk_container_add(GTK_CONTAINER(content), ctrl_check);

    GtkWidget* alt_check = gtk_check_button_new_with_label("Alt");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(alt_check), has_mod("alt"));
    gtk_container_add(GTK_CONTAINER(content), alt_check);

    GtkWidget* super_check = gtk_check_button_new_with_label("Super");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(super_check), has_mod("super"));
    gtk_container_add(GTK_CONTAINER(content), super_check);

    GtkWidget* shift_check = gtk_check_button_new_with_label("Shift");
    gtk_toggle_button_set_active(GTK_TOGGLE_BUTTON(shift_check), has_mod("shift"));
    gtk_container_add(GTK_CONTAINER(content), shift_check);

    gtk_widget_show_all(dialog);

    int response = gtk_dialog_run(GTK_DIALOG(dialog));

    if (response == GTK_RESPONSE_OK) {
        std::vector<std::string> new_modifiers;
        if (gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(ctrl_check)))  new_modifiers.push_back("ctrl");
        if (gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(alt_check)))   new_modifiers.push_back("alt");
        if (gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(super_check))) new_modifiers.push_back("super");
        if (gtk_toggle_button_get_active(GTK_TOGGLE_BUTTON(shift_check))) new_modifiers.push_back("shift");

        // Prevent lockout: at least one modifier must be selected
        if (!new_modifiers.empty()) {
            current_modifiers_ = new_modifiers;
            if (on_hotkey_change_) {
                on_hotkey_change_(new_modifiers);
            }
        }
    }

    gtk_widget_destroy(dialog);
}

} // namespace verbal
