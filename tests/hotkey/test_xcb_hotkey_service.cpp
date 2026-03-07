#include "xcb_hotkey_service.hpp"

#include <gtest/gtest.h>

using verbal::XcbHotkeyService;

TEST(XcbHotkeyService, ModifierStateCheck) {
    XcbHotkeyService service;
    service.set_modifiers({"ctrl", "super", "alt"});

    // All pressed
    verbal::ModifierState all_pressed{true, true, true, false};
    EXPECT_TRUE(service.check_modifiers(all_pressed));

    // Missing ctrl
    verbal::ModifierState no_ctrl{false, true, true, false};
    EXPECT_FALSE(service.check_modifiers(no_ctrl));

    // Missing super
    verbal::ModifierState no_super{true, false, true, false};
    EXPECT_FALSE(service.check_modifiers(no_super));

    // Missing alt
    verbal::ModifierState no_alt{true, true, false, false};
    EXPECT_FALSE(service.check_modifiers(no_alt));

    // None pressed
    verbal::ModifierState none{false, false, false, false};
    EXPECT_FALSE(service.check_modifiers(none));
}

TEST(XcbHotkeyService, EmptyModifiers) {
    XcbHotkeyService service;
    service.set_modifiers({});

    verbal::ModifierState state{true, true, true, true};
    EXPECT_FALSE(service.check_modifiers(state)); // No modifiers = never triggered
}

TEST(XcbHotkeyService, CustomModifiers) {
    XcbHotkeyService service;
    service.set_modifiers({"ctrl", "alt"});

    verbal::ModifierState state{true, false, true, false};
    EXPECT_TRUE(service.check_modifiers(state));

    verbal::ModifierState missing{true, false, false, false};
    EXPECT_FALSE(service.check_modifiers(missing));
}
