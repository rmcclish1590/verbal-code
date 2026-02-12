#include "transcription_orchestrator.hpp"

#include <gtest/gtest.h>

using verbal::TranscriptionOrchestrator;

TEST(TranscriptionOrchestrator, EditDistanceRatioIdentical) {
    EXPECT_DOUBLE_EQ(TranscriptionOrchestrator::edit_distance_ratio("hello", "hello"), 0.0);
}

TEST(TranscriptionOrchestrator, EditDistanceRatioEmpty) {
    EXPECT_DOUBLE_EQ(TranscriptionOrchestrator::edit_distance_ratio("", ""), 0.0);
}

TEST(TranscriptionOrchestrator, EditDistanceRatioCompleteDiff) {
    // "abc" vs "xyz" = 3 edits / 3 max = 1.0
    EXPECT_DOUBLE_EQ(TranscriptionOrchestrator::edit_distance_ratio("abc", "xyz"), 1.0);
}

TEST(TranscriptionOrchestrator, EditDistanceRatioPartialDiff) {
    // "hello" vs "hallo" = 1 edit / 5 max = 0.2
    EXPECT_DOUBLE_EQ(TranscriptionOrchestrator::edit_distance_ratio("hello", "hallo"), 0.2);
}

TEST(TranscriptionOrchestrator, EditDistanceRatioDiffLengths) {
    // "hello" vs "hell" = 1 edit / 5 max = 0.2
    EXPECT_DOUBLE_EQ(TranscriptionOrchestrator::edit_distance_ratio("hello", "hell"), 0.2);
}

TEST(TranscriptionOrchestrator, EditDistanceRatioLongerStrings) {
    // "the quick brown fox" vs "the quick brown box"
    // 1 substitution / 19 chars = ~0.0526
    double ratio = TranscriptionOrchestrator::edit_distance_ratio(
        "the quick brown fox", "the quick brown box");
    EXPECT_NEAR(ratio, 1.0 / 19.0, 0.001);
}
