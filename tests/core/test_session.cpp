#include "session.hpp"

#include <gtest/gtest.h>
#include <cstdlib>

using namespace verbal;

TEST(SessionDetection, ReturnsWaylandWhenSet) {
    setenv("XDG_SESSION_TYPE", "wayland", 1);
    EXPECT_EQ(detect_session_type(), SessionType::WAYLAND);
}

TEST(SessionDetection, ReturnsX11WhenSet) {
    setenv("XDG_SESSION_TYPE", "x11", 1);
    EXPECT_EQ(detect_session_type(), SessionType::X11);
}

TEST(SessionDetection, ReturnsUnknownForOtherValues) {
    setenv("XDG_SESSION_TYPE", "tty", 1);
    EXPECT_EQ(detect_session_type(), SessionType::UNKNOWN);
}

TEST(SessionDetection, ReturnsUnknownWhenUnset) {
    unsetenv("XDG_SESSION_TYPE");
    EXPECT_EQ(detect_session_type(), SessionType::UNKNOWN);
}

TEST(SessionTypeStr, CorrectStrings) {
    EXPECT_STREQ(session_type_str(SessionType::X11), "X11");
    EXPECT_STREQ(session_type_str(SessionType::WAYLAND), "Wayland");
    EXPECT_STREQ(session_type_str(SessionType::UNKNOWN), "Unknown");
}
