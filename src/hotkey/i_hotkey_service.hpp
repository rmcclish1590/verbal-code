#pragma once

#include "i_service.hpp"
#include "types.hpp"

#include <vector>
#include <string>

namespace verbal {

class IHotkeyService : public IService {
public:
    ~IHotkeyService() override = default;

    // Register hotkey with modifier names (e.g., "ctrl", "super", "alt")
    virtual void set_modifiers(const std::vector<std::string>& modifiers) = 0;

    // Callbacks
    virtual void set_on_press(VoidCallback cb) = 0;
    virtual void set_on_release(VoidCallback cb) = 0;

    // Current state
    virtual bool is_pressed() const = 0;
};

} // namespace verbal
