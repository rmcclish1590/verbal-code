#include "wayland_injection_service.hpp"

#include <gtest/gtest.h>

using namespace verbal;

TEST(WaylandInjection, BuildPasteCommandNonTerminal) {
    std::string cmd = WaylandInjectionService::build_paste_command(false);
    // Ctrl+V: KEY_LEFTCTRL=29 down, KEY_V=47 down/up, KEY_LEFTCTRL up
    EXPECT_EQ(cmd, "ydotool key 29:1 47:1 47:0 29:0");
}

TEST(WaylandInjection, BuildPasteCommandTerminal) {
    std::string cmd = WaylandInjectionService::build_paste_command(true);
    // Ctrl+Shift+V: KEY_LEFTCTRL=29, KEY_LEFTSHIFT=42, KEY_V=47
    EXPECT_EQ(cmd, "ydotool key 29:1 42:1 47:1 47:0 42:0 29:0");
}

TEST(WaylandInjection, BuildBackspaceCommand) {
    std::string cmd = WaylandInjectionService::build_backspace_command(3);
    // KEY_BACKSPACE=14, three times
    EXPECT_EQ(cmd, "ydotool key 14:1 14:0 14:1 14:0 14:1 14:0");
}

TEST(WaylandInjection, BuildBackspaceCommandZero) {
    std::string cmd = WaylandInjectionService::build_backspace_command(0);
    EXPECT_EQ(cmd, "ydotool key");
}

TEST(WaylandInjection, HasFocusedInputAlwaysTrue) {
    // On Wayland, we can't detect focused input, so it always returns true
    WaylandInjectionService service;
    EXPECT_TRUE(service.has_focused_input());
}

TEST(WaylandInjection, LastInjectionLengthInitiallyZero) {
    WaylandInjectionService service;
    EXPECT_EQ(service.last_injection_length(), 0u);
}
