#include "config.hpp"

#include <gtest/gtest.h>
#include <filesystem>
#include <fstream>

namespace fs = std::filesystem;

class ConfigTest : public ::testing::Test {
protected:
    void SetUp() override {
        test_dir_ = fs::temp_directory_path() / "verbal_test_config";
        fs::create_directories(test_dir_);
        test_path_ = (test_dir_ / "config.json").string();
    }

    void TearDown() override {
        fs::remove_all(test_dir_);
    }

    fs::path test_dir_;
    std::string test_path_;
};

TEST_F(ConfigTest, DefaultValues) {
    verbal::Config config;
    config.load(test_path_); // File doesn't exist, should use defaults

    EXPECT_EQ(config.sample_rate(), 16000);
    EXPECT_EQ(config.channels(), 1);
    EXPECT_EQ(config.overlay_size(), 20);
    EXPECT_EQ(config.overlay_x(), -1);
    EXPECT_EQ(config.overlay_y(), -1);
    EXPECT_TRUE(config.whisper_refinement_enabled());
    EXPECT_EQ(config.max_transcriptions(), 1000);
}

TEST_F(ConfigTest, DefaultHotkeyModifiers) {
    verbal::Config config;
    config.load(test_path_);

    auto mods = config.hotkey_modifiers();
    ASSERT_EQ(mods.size(), 3u);
    EXPECT_EQ(mods[0], "ctrl");
    EXPECT_EQ(mods[1], "super");
    EXPECT_EQ(mods[2], "alt");
}

TEST_F(ConfigTest, SaveAndLoad) {
    // Save config with custom values
    {
        verbal::Config config;
        config.load(test_path_);
        config.set_overlay_position(100, 200);
        EXPECT_TRUE(config.save(test_path_));
    }

    // Load and verify
    {
        verbal::Config config;
        EXPECT_TRUE(config.load(test_path_));
        EXPECT_EQ(config.overlay_x(), 100);
        EXPECT_EQ(config.overlay_y(), 200);
        // Other defaults should still be present
        EXPECT_EQ(config.sample_rate(), 16000);
    }
}

TEST_F(ConfigTest, LoadPartialConfig) {
    // Write a config with only some fields
    {
        std::ofstream f(test_path_);
        f << R"({"audio": {"sample_rate": 44100}})";
    }

    verbal::Config config;
    EXPECT_TRUE(config.load(test_path_));

    // Overridden value
    EXPECT_EQ(config.sample_rate(), 44100);
    // Default values still present
    EXPECT_EQ(config.channels(), 1);
    EXPECT_EQ(config.overlay_size(), 20);
}

TEST_F(ConfigTest, LoadInvalidJson) {
    {
        std::ofstream f(test_path_);
        f << "not valid json {{{";
    }

    verbal::Config config;
    EXPECT_FALSE(config.load(test_path_));
    // Should fall back to defaults
    EXPECT_EQ(config.sample_rate(), 16000);
}

TEST_F(ConfigTest, MissingFileReturnsDefaults) {
    verbal::Config config;
    EXPECT_FALSE(config.load("/nonexistent/path/config.json"));
    EXPECT_EQ(config.sample_rate(), 16000);
}

TEST_F(ConfigTest, SetHotkeyModifiers) {
    verbal::Config config;
    config.load(test_path_);
    config.set_hotkey_modifiers({"ctrl", "alt"});

    auto mods = config.hotkey_modifiers();
    ASSERT_EQ(mods.size(), 2u);
    EXPECT_EQ(mods[0], "ctrl");
    EXPECT_EQ(mods[1], "alt");
}
