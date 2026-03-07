#include "transcription_orchestrator.hpp"
#include "mock_services.hpp"

#include <gtest/gtest.h>
#include <memory>

using verbal::TranscriptionOrchestrator;
using verbal::testing::MockRecognitionService;
using verbal::testing::MockRefinementService;

// ── edit_distance_ratio tests (existing) ─────────────────

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

// ── Recording flow tests ─────────────────────────────────

class OrchestratorTest : public ::testing::Test {
protected:
    void SetUp() override {
        recognition_ptr_ = std::make_unique<MockRecognitionService>();
        refinement_ptr_ = std::make_unique<MockRefinementService>();
        recognition_ = recognition_ptr_.get();
        refinement_ = refinement_ptr_.get();
        refinement_->init();
    }

    std::unique_ptr<MockRecognitionService> recognition_ptr_;
    std::unique_ptr<MockRefinementService> refinement_ptr_;
    MockRecognitionService* recognition_;
    MockRefinementService* refinement_;
};

TEST_F(OrchestratorTest, RecordingStartResetsState) {
    TranscriptionOrchestrator orch(recognition_, refinement_);
    orch.on_recording_start();

    EXPECT_TRUE(recognition_->reset_called_);
    EXPECT_TRUE(recognition_->streaming_);
}

TEST_F(OrchestratorTest, RecordingStopStopsStreaming) {
    TranscriptionOrchestrator orch(recognition_, refinement_);
    orch.on_recording_start();
    orch.on_recording_stop({});

    EXPECT_FALSE(recognition_->streaming_);
}

TEST_F(OrchestratorTest, PartialCallbackFires) {
    TranscriptionOrchestrator orch(recognition_, refinement_);

    std::string received;
    orch.set_on_partial([&](const std::string& text) { received = text; });

    orch.on_recording_start();
    recognition_->emit_partial("hello world");

    EXPECT_EQ(received, "hello world");
}

TEST_F(OrchestratorTest, NoRefinementWhenDisabled) {
    TranscriptionOrchestrator::Config config;
    config.enable_whisper_refinement = false;
    TranscriptionOrchestrator orch(recognition_, refinement_, config);

    std::string vosk_out, refined_out;
    orch.set_on_refined([&](const std::string& v, const std::string& r) {
        vosk_out = v;
        refined_out = r;
    });

    recognition_->set_final_result("hello");
    orch.on_recording_start();
    orch.on_recording_stop({1, 2, 3});

    // Both should be the vosk text since refinement is disabled
    EXPECT_EQ(vosk_out, "hello");
    EXPECT_EQ(refined_out, "hello");
    EXPECT_FALSE(orch.was_refined());
}

TEST_F(OrchestratorTest, NoRefinementWhenNullRefinement) {
    TranscriptionOrchestrator orch(recognition_, nullptr);

    std::string vosk_out, refined_out;
    orch.set_on_refined([&](const std::string& v, const std::string& r) {
        vosk_out = v;
        refined_out = r;
    });

    recognition_->set_final_result("hello");
    orch.on_recording_start();
    orch.on_recording_stop({1, 2, 3});

    EXPECT_EQ(vosk_out, "hello");
    EXPECT_EQ(refined_out, "hello");
    EXPECT_FALSE(orch.was_refined());
}

TEST_F(OrchestratorTest, RefinementAppliedWhenDifferent) {
    TranscriptionOrchestrator::Config config;
    config.enable_whisper_refinement = true;
    config.refinement_threshold = 0.2;
    TranscriptionOrchestrator orch(recognition_, refinement_, config);

    // Vosk says "helo wrld", Whisper says "hello world" — 2 edits / 11 chars ≈ 0.18
    // Use a lower threshold to trigger refinement
    config.refinement_threshold = 0.05;
    TranscriptionOrchestrator orch2(recognition_, refinement_, config);

    refinement_->set_refined_text("hello world");

    std::string vosk_out, refined_out;
    orch2.set_on_refined([&](const std::string& v, const std::string& r) {
        vosk_out = v;
        refined_out = r;
    });

    recognition_->set_final_result("helo world");
    orch2.on_recording_start();
    orch2.on_recording_stop({1, 2, 3});

    // edit distance ratio ≈ 0.09, above 0.05 threshold
    EXPECT_EQ(vosk_out, "helo world");
    EXPECT_EQ(refined_out, "hello world");
    EXPECT_TRUE(orch2.was_refined());
}

TEST_F(OrchestratorTest, RefinementSkippedWhenSimilar) {
    TranscriptionOrchestrator::Config config;
    config.enable_whisper_refinement = true;
    config.refinement_threshold = 0.5; // high threshold
    TranscriptionOrchestrator orch(recognition_, refinement_, config);

    // Vosk and Whisper produce very similar results
    refinement_->set_refined_text("hello world");

    std::string vosk_out, refined_out;
    orch.set_on_refined([&](const std::string& v, const std::string& r) {
        vosk_out = v;
        refined_out = r;
    });

    recognition_->set_final_result("hello werld");
    orch.on_recording_start();
    orch.on_recording_stop({1, 2, 3});

    // Edit distance ratio is 1/11 ≈ 0.09, below 0.5 threshold
    // So refinement is NOT applied — both should be vosk text
    EXPECT_EQ(vosk_out, "hello werld");
    EXPECT_EQ(refined_out, "hello werld");
    EXPECT_FALSE(orch.was_refined());
}

TEST_F(OrchestratorTest, RefinementFailureFallsBackToVosk) {
    TranscriptionOrchestrator::Config config;
    config.enable_whisper_refinement = true;
    TranscriptionOrchestrator orch(recognition_, refinement_, config);

    refinement_->set_should_fail(true);

    std::string vosk_out, refined_out;
    orch.set_on_refined([&](const std::string& v, const std::string& r) {
        vosk_out = v;
        refined_out = r;
    });

    recognition_->set_final_result("hello");
    orch.on_recording_start();
    orch.on_recording_stop({1, 2, 3});

    EXPECT_EQ(vosk_out, "hello");
    EXPECT_EQ(refined_out, "hello");
    EXPECT_FALSE(orch.was_refined());
}

TEST_F(OrchestratorTest, NoRefinementOnEmptyAudio) {
    TranscriptionOrchestrator::Config config;
    config.enable_whisper_refinement = true;
    TranscriptionOrchestrator orch(recognition_, refinement_, config);

    refinement_->set_refined_text("something different");

    std::string vosk_out, refined_out;
    orch.set_on_refined([&](const std::string& v, const std::string& r) {
        vosk_out = v;
        refined_out = r;
    });

    recognition_->set_final_result("hello");
    orch.on_recording_start();
    orch.on_recording_stop({}); // empty audio

    // Should skip refinement due to empty audio
    EXPECT_EQ(vosk_out, "hello");
    EXPECT_EQ(refined_out, "hello");
    EXPECT_FALSE(orch.was_refined());
}

TEST_F(OrchestratorTest, FinalCallbackUpdatesVoskText) {
    TranscriptionOrchestrator orch(recognition_, nullptr);

    std::string vosk_out;
    orch.set_on_refined([&](const std::string& v, const std::string&) {
        vosk_out = v;
    });

    // Simulate: vosk emits a final callback during streaming, then final_result returns something
    orch.on_recording_start();
    recognition_->emit_final("streaming result");

    // final_result returns empty, so the streamed result is kept
    recognition_->set_final_result("");
    orch.on_recording_stop({});

    EXPECT_EQ(vosk_out, "streaming result");
}
