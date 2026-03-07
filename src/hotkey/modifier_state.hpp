#pragma once

#include <string>
#include <vector>

namespace verbal {

// Represents the current state of modifier keys.
// Used by hotkey services to determine if the configured hotkey combination is active.
struct ModifierState {
    bool ctrl = false;
    bool super = false;
    bool alt = false;
    bool shift = false;
};

// Returns true iff every name in required_modifiers maps to an active field in state.
// Returns false when required_modifiers is empty (no config = hotkey disabled).
// Modifier name matching: "ctrl"/"control" -> ctrl, "alt" -> alt,
// "super"/"meta" -> super, "shift" -> shift.
inline bool check_modifiers_match(
    const std::vector<std::string>& required_modifiers,
    const ModifierState& state)
{
    for (const auto& mod : required_modifiers) {
        if (mod == "ctrl" || mod == "control") {
            if (!state.ctrl) return false;
        } else if (mod == "alt") {
            if (!state.alt) return false;
        } else if (mod == "super" || mod == "meta") {
            if (!state.super) return false;
        } else if (mod == "shift") {
            if (!state.shift) return false;
        }
    }
    return !required_modifiers.empty();
}

} // namespace verbal
