#pragma once

#include "i_overlay_service.hpp"
#include "logger.hpp"

#include <gtk/gtk.h>

#include <atomic>
#include <vector>
#include <string>

namespace verbal {

class GtkOverlayService : public IOverlayService {
public:
    GtkOverlayService(int size = 20);
    ~GtkOverlayService() override;

    // IService
    Result<void> start() override;
    void stop() override;
    bool is_running() const override { return running_.load(std::memory_order_acquire); }

    // IOverlayService
    void show() override;
    void hide() override;
    void set_state(OverlayState state) override;
    void set_position(int x, int y) override;
    int x() const override { return x_; }
    int y() const override { return y_; }
    void set_on_position_changed(PositionCallback cb) override { on_position_changed_ = std::move(cb); }
    void set_on_quit_requested(QuitCallback cb) override { on_quit_requested_ = std::move(cb); }
    void set_on_hotkey_change(HotkeyChangeCallback cb) override { on_hotkey_change_ = std::move(cb); }
    void set_current_modifiers(const std::vector<std::string>& modifiers) override { current_modifiers_ = modifiers; }

private:
    static gboolean on_draw(GtkWidget* widget, cairo_t* cr, gpointer data);
    static gboolean on_button_press(GtkWidget* widget, GdkEventButton* event, gpointer data);
    static gboolean on_button_release(GtkWidget* widget, GdkEventButton* event, gpointer data);
    static gboolean on_motion_notify(GtkWidget* widget, GdkEventMotion* event, gpointer data);
    static gboolean on_configure(GtkWidget* widget, GdkEventConfigure* event, gpointer data);

    void create_window();
    void update_position_default();
    void show_context_menu(GdkEventButton* event);
    void show_hotkey_dialog();

    int dot_size_;
    static constexpr int window_size_ = 24; // hit area; dot draws centered
    int x_ = -1;
    int y_ = -1;
    OverlayState state_ = OverlayState::IDLE;
    PositionCallback on_position_changed_;
    QuitCallback on_quit_requested_;
    HotkeyChangeCallback on_hotkey_change_;
    std::vector<std::string> current_modifiers_;

    bool dragging_ = false;
    double drag_offset_x_ = 0;
    double drag_offset_y_ = 0;

    GtkWidget* window_ = nullptr;
    std::atomic<bool> running_{false};
};

} // namespace verbal
