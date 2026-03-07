#pragma once

#include <cstdlib>
#include <string>

namespace verbal {

// Display session type. UNKNOWN (unset or unrecognized XDG_SESSION_TYPE)
// falls back to X11 backends in the application.
enum class SessionType {
    X11,
    WAYLAND,
    UNKNOWN
};

inline SessionType detect_session_type() {
    const char* session = std::getenv("XDG_SESSION_TYPE");
    if (!session) return SessionType::UNKNOWN;

    std::string s(session);
    if (s == "wayland") return SessionType::WAYLAND;
    if (s == "x11")     return SessionType::X11;
    return SessionType::UNKNOWN;
}

inline const char* session_type_str(SessionType type) {
    switch (type) {
        case SessionType::X11:     return "X11";
        case SessionType::WAYLAND: return "Wayland";
        default:                   return "Unknown";
    }
}

} // namespace verbal
