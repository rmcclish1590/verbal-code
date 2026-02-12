#include "transcription_store.hpp"

#include <gtest/gtest.h>
#include <filesystem>

namespace fs = std::filesystem;

class TranscriptionStoreTest : public ::testing::Test {
protected:
    void SetUp() override {
        test_dir_ = fs::temp_directory_path() / "verbal_test_store";
        fs::create_directories(test_dir_);
        test_path_ = (test_dir_ / "transcriptions.json").string();
    }

    void TearDown() override {
        fs::remove_all(test_dir_);
    }

    fs::path test_dir_;
    std::string test_path_;
};

TEST_F(TranscriptionStoreTest, AppendAndSize) {
    verbal::TranscriptionStore store(test_path_);
    EXPECT_EQ(store.size(), 0u);

    store.append("hello world", verbal::TranscriptionSource::VOSK);
    EXPECT_EQ(store.size(), 1u);

    store.append("goodbye world", verbal::TranscriptionSource::WHISPER);
    EXPECT_EQ(store.size(), 2u);
}

TEST_F(TranscriptionStoreTest, SaveAndLoad) {
    {
        verbal::TranscriptionStore store(test_path_);
        store.append("test text", verbal::TranscriptionSource::VOSK);
        store.append("refined text", verbal::TranscriptionSource::WHISPER);
        auto result = store.save();
        EXPECT_TRUE(result.is_ok());
    }

    {
        verbal::TranscriptionStore store(test_path_);
        auto result = store.load();
        EXPECT_TRUE(result.is_ok());
        ASSERT_EQ(store.size(), 2u);

        auto& entries = store.entries();
        EXPECT_EQ(entries[0].text, "test text");
        EXPECT_EQ(entries[1].text, "refined text");
        EXPECT_FALSE(entries[0].timestamp.empty());
    }
}

TEST_F(TranscriptionStoreTest, MaxEntries) {
    verbal::TranscriptionStore store(test_path_, 3);
    store.append("one", verbal::TranscriptionSource::VOSK);
    store.append("two", verbal::TranscriptionSource::VOSK);
    store.append("three", verbal::TranscriptionSource::VOSK);
    store.append("four", verbal::TranscriptionSource::VOSK);

    EXPECT_EQ(store.size(), 3u);
    // Oldest entry ("one") should have been evicted
    EXPECT_EQ(store.entries()[0].text, "two");
}

TEST_F(TranscriptionStoreTest, Clear) {
    verbal::TranscriptionStore store(test_path_);
    store.append("text", verbal::TranscriptionSource::VOSK);
    EXPECT_EQ(store.size(), 1u);

    store.clear();
    EXPECT_EQ(store.size(), 0u);
}

TEST_F(TranscriptionStoreTest, LoadMissingFile) {
    verbal::TranscriptionStore store("/nonexistent/path/t.json");
    auto result = store.load();
    EXPECT_TRUE(result.is_ok()); // Missing file = empty store
    EXPECT_EQ(store.size(), 0u);
}

TEST_F(TranscriptionStoreTest, TimestampFormat) {
    verbal::TranscriptionStore store(test_path_);
    store.append("test", verbal::TranscriptionSource::VOSK);

    auto& entries = store.entries();
    ASSERT_EQ(entries.size(), 1u);
    // Timestamp should look like "2024-01-15T10:30:45"
    EXPECT_GE(entries[0].timestamp.size(), 19u);
    EXPECT_EQ(entries[0].timestamp[4], '-');
    EXPECT_EQ(entries[0].timestamp[10], 'T');
}
