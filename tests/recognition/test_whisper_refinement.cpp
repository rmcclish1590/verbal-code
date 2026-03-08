#include <gtest/gtest.h>
#include "whisper_refinement_service.hpp"

#include <thread>

namespace verbal {
namespace {

TEST(WhisperRefinementServiceTest, ConstructorAcceptsModelPath) {
    WhisperRefinementService service("/tmp/nonexistent_model.bin");
    // Construction should succeed without touching the filesystem
    EXPECT_FALSE(service.is_initialized());
}

TEST(WhisperRefinementServiceTest, DefaultInitialPromptIsEmpty) {
    WhisperRefinementService service("/tmp/nonexistent_model.bin");
    EXPECT_TRUE(service.get_initial_prompt().empty());
}

TEST(WhisperRefinementServiceTest, SetInitialPromptStoresPrompt) {
    WhisperRefinementService service("/tmp/nonexistent_model.bin");
    service.set_initial_prompt("programming vocabulary test");
    EXPECT_EQ(service.get_initial_prompt(), "programming vocabulary test");
}

TEST(WhisperRefinementServiceTest, SetInitialPromptCanBeOverwritten) {
    WhisperRefinementService service("/tmp/nonexistent_model.bin");
    service.set_initial_prompt("first prompt");
    service.set_initial_prompt("second prompt");
    EXPECT_EQ(service.get_initial_prompt(), "second prompt");
}

TEST(WhisperRefinementServiceTest, SetInitialPromptCanBeClearedWithEmpty) {
    WhisperRefinementService service("/tmp/nonexistent_model.bin");
    service.set_initial_prompt("some prompt");
    service.set_initial_prompt("");
    EXPECT_TRUE(service.get_initial_prompt().empty());
}

TEST(WhisperRefinementServiceTest, ThreadCountIsCappedAt8) {
    // auto_thread_count caps at 8 -- we test via the public accessor
    WhisperRefinementService service("/tmp/nonexistent_model.bin");
    int tc = service.thread_count();
    EXPECT_GE(tc, 1);
    EXPECT_LE(tc, 8);
}

TEST(WhisperRefinementServiceTest, ThreadCountMatchesHardwareConcurrency) {
    unsigned int hw = std::thread::hardware_concurrency();
    int expected = (hw == 0) ? 4 : static_cast<int>(std::min(hw, 8u));

    WhisperRefinementService service("/tmp/nonexistent_model.bin");
    EXPECT_EQ(service.thread_count(), expected);
}

} // namespace
} // namespace verbal
