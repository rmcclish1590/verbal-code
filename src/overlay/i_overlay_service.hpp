#pragma once

#include "i_service.hpp"
#include "types.hpp"

#include <vector>
#include <string>

namespace verbal {

class IOverlayService : public IService {
public:
    ~IOverlayService() override = default;

    virtual void show() = 0;
    virtual void hide() = 0;
    virtual void set_state(OverlayState state) = 0;
    virtual void set_position(int x, int y) = 0;

    // Get current position (for saving to config)
    virtual int x() const = 0;
    virtual int y() const = 0;

    // Callback for position changes (e.g., after drag)
    using PositionCallback = std::function<void(int x, int y)>;
    virtual void set_on_position_changed(PositionCallback cb) = 0;

    // Callback when user requests quit from context menu
    using QuitCallback = VoidCallback;
    virtual void set_on_quit_requested(QuitCallback cb) = 0;

    // Callback when user changes hotkey modifiers from dialog
    using HotkeyChangeCallback = std::function<void(const std::vector<std::string>&)>;
    virtual void set_on_hotkey_change(HotkeyChangeCallback cb) = 0;

    // Set current modifiers so the dialog can pre-populate
    virtual void set_current_modifiers(const std::vector<std::string>& modifiers) = 0;

    // Callback when user requests history from context menu
    using HistoryCallback = std::function<void()>;
    virtual void set_on_history_requested(HistoryCallback cb) = 0;

    // Show the history dialog with a list of transcription texts
    virtual void show_history_dialog(const std::vector<std::string>& texts) = 0;
};

} // namespace verbal
