#include "portal_hotkey_service.hpp"

#include <gtest/gtest.h>

using namespace verbal;

TEST(PortalHotkey, BuildShortcutStringCtrlSuperAlt) {
    auto result = PortalHotkeyService::build_shortcut_string(
        {"ctrl", "super", "alt"}, "v");
    EXPECT_EQ(result, "<ctrl><super><alt>v");
}

TEST(PortalHotkey, BuildShortcutStringSingleModifier) {
    auto result = PortalHotkeyService::build_shortcut_string({"ctrl"}, "space");
    EXPECT_EQ(result, "<ctrl>space");
}

TEST(PortalHotkey, BuildShortcutStringNoModifiers) {
    auto result = PortalHotkeyService::build_shortcut_string({}, "F5");
    EXPECT_EQ(result, "F5");
}

TEST(PortalHotkey, BuildShortcutStringCaseInsensitive) {
    auto result = PortalHotkeyService::build_shortcut_string(
        {"Ctrl", "SUPER"}, "v");
    EXPECT_EQ(result, "<ctrl><super>v");
}

TEST(PortalHotkey, BuildShortcutStringWithShift) {
    auto result = PortalHotkeyService::build_shortcut_string(
        {"ctrl", "shift"}, "a");
    EXPECT_EQ(result, "<ctrl><shift>a");
}

TEST(PortalHotkey, IsPressedInitiallyFalse) {
    PortalHotkeyService service;
    EXPECT_FALSE(service.is_pressed());
}
