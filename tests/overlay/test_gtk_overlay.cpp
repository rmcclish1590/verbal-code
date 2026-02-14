#include "gtk_overlay_service.hpp"

#include <gtest/gtest.h>

using verbal::GtkOverlayService;

TEST(GtkOverlayService, InitialState) {
    GtkOverlayService service;
    EXPECT_FALSE(service.is_running());
    EXPECT_EQ(service.x(), -1);
    EXPECT_EQ(service.y(), -1);
}

TEST(GtkOverlayService, SetPosition) {
    GtkOverlayService service;
    service.set_position(100, 200);
    EXPECT_EQ(service.x(), 100);
    EXPECT_EQ(service.y(), 200);
}

TEST(GtkOverlayService, SetOnQuitRequested) {
    GtkOverlayService service;
    bool called = false;
    service.set_on_quit_requested([&called]() { called = true; });
    // Callback is stored; we can't trigger it without GTK, but setting it shouldn't crash
    EXPECT_FALSE(called);
}

TEST(GtkOverlayService, SetOnHotkeyChange) {
    GtkOverlayService service;
    std::vector<std::string> received;
    service.set_on_hotkey_change([&received](const std::vector<std::string>& mods) {
        received = mods;
    });
    // Callback is stored; verify it doesn't crash
    EXPECT_TRUE(received.empty());
}

TEST(GtkOverlayService, SetCurrentModifiers) {
    GtkOverlayService service;
    std::vector<std::string> mods = {"ctrl", "alt", "super"};
    service.set_current_modifiers(mods);
    // No getter, but it shouldn't crash and is used internally by the dialog
}

TEST(GtkOverlayService, SetOnHistoryRequested) {
    GtkOverlayService service;
    bool called = false;
    service.set_on_history_requested([&called]() { called = true; });
    // Callback is stored; we can't trigger it without GTK, but setting it shouldn't crash
    EXPECT_FALSE(called);
}
