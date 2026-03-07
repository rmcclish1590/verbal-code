#include "evdev_hotkey_service.hpp"

#include <linux/input-event-codes.h>
#include <gtest/gtest.h>

using verbal::EvdevHotkeyService;

// Use kernel macros directly: KEY_LEFTCTRL, KEY_RIGHTCTRL, etc.
// Alias for brevity in tests
constexpr uint16_t LCTRL  = KEY_LEFTCTRL;
constexpr uint16_t RCTRL  = KEY_RIGHTCTRL;
constexpr uint16_t LALT   = KEY_LEFTALT;
constexpr uint16_t RALT   = KEY_RIGHTALT;
constexpr uint16_t LSUPER = KEY_LEFTMETA;
constexpr uint16_t RSUPER = KEY_RIGHTMETA;
constexpr uint16_t LSHIFT = KEY_LEFTSHIFT;
constexpr uint16_t RSHIFT = KEY_RIGHTSHIFT;
constexpr uint16_t KEYA   = KEY_A;

TEST(EvdevHotkeyService, ModifierStateCheck) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl", "super", "alt"});

    // All pressed
    EvdevHotkeyService::ModifierState all{true, true, true, false};
    EXPECT_TRUE(service.check_modifiers(all));

    // Missing ctrl
    EvdevHotkeyService::ModifierState no_ctrl{false, true, true, false};
    EXPECT_FALSE(service.check_modifiers(no_ctrl));

    // Missing super
    EvdevHotkeyService::ModifierState no_super{true, false, true, false};
    EXPECT_FALSE(service.check_modifiers(no_super));

    // Missing alt
    EvdevHotkeyService::ModifierState no_alt{true, true, false, false};
    EXPECT_FALSE(service.check_modifiers(no_alt));

    // None pressed
    EvdevHotkeyService::ModifierState none{false, false, false, false};
    EXPECT_FALSE(service.check_modifiers(none));
}

TEST(EvdevHotkeyService, EmptyModifiers) {
    EvdevHotkeyService service;
    service.set_modifiers({});

    EvdevHotkeyService::ModifierState state{true, true, true, true};
    EXPECT_FALSE(service.check_modifiers(state));
}

TEST(EvdevHotkeyService, CustomModifiers) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl", "alt"});

    EvdevHotkeyService::ModifierState ok_state{true, false, true, false};
    EXPECT_TRUE(service.check_modifiers(ok_state));

    EvdevHotkeyService::ModifierState missing{true, false, false, false};
    EXPECT_FALSE(service.check_modifiers(missing));
}

TEST(EvdevHotkeyService, ProcessKeyEventFiresCallbacks) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl", "super", "alt"});

    int press_count = 0;
    int release_count = 0;
    service.set_on_press([&]() { ++press_count; });
    service.set_on_release([&]() { ++release_count; });

    // Press ctrl, super, alt in sequence — should fire on_press when all held
    service.process_key_event(LCTRL, 1);
    EXPECT_EQ(press_count, 0);

    service.process_key_event(LSUPER, 1);
    EXPECT_EQ(press_count, 0);

    service.process_key_event(LALT, 1);
    EXPECT_EQ(press_count, 1);
    EXPECT_EQ(release_count, 0);

    // Release one modifier — should fire on_release
    service.process_key_event(LALT, 0);
    EXPECT_EQ(release_count, 1);

    // Press count should not increase again without full release+repress
    EXPECT_EQ(press_count, 1);
}

TEST(EvdevHotkeyService, LeftRightVariantsBothWork) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl", "alt"});

    int press_count = 0;
    int release_count = 0;
    service.set_on_press([&]() { ++press_count; });
    service.set_on_release([&]() { ++release_count; });

    // Use right-hand variants
    service.process_key_event(RCTRL, 1);
    service.process_key_event(RALT, 1);
    EXPECT_EQ(press_count, 1);

    // Release right ctrl, press left ctrl — should stay pressed (alt still held)
    service.process_key_event(RCTRL, 0);
    EXPECT_EQ(release_count, 1);

    service.process_key_event(LCTRL, 1);
    EXPECT_EQ(press_count, 2); // re-triggered
}

TEST(EvdevHotkeyService, KeyRepeatEventsIgnored) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl", "alt"});

    int press_count = 0;
    service.set_on_press([&]() { ++press_count; });

    service.process_key_event(LCTRL, 1);
    service.process_key_event(LALT, 1);
    EXPECT_EQ(press_count, 1);

    // Repeat events (value=2) should not re-trigger
    service.process_key_event(LCTRL, 2);
    service.process_key_event(LALT, 2);
    EXPECT_EQ(press_count, 1);
}

TEST(EvdevHotkeyService, NonModifierKeysIgnored) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl"});

    int press_count = 0;
    service.set_on_press([&]() { ++press_count; });

    // Non-modifier key should not affect state
    service.process_key_event(KEYA, 1);
    EXPECT_EQ(press_count, 0);

    service.process_key_event(LCTRL, 1);
    EXPECT_EQ(press_count, 1);

    service.process_key_event(KEYA, 0);
    EXPECT_EQ(press_count, 1); // still pressed — ctrl is still held
}

TEST(EvdevHotkeyService, IsPressedReflectsState) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl"});
    service.set_on_press([]() {});
    service.set_on_release([]() {});

    EXPECT_FALSE(service.is_pressed());

    service.process_key_event(LCTRL, 1);
    EXPECT_TRUE(service.is_pressed());

    service.process_key_event(LCTRL, 0);
    EXPECT_FALSE(service.is_pressed());
}
