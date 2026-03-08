#pragma once

#include "i_refinement_service.hpp"
#include "result.hpp"
#include "types.hpp"

#include <string>
#include <vector>

// Forward declare in global namespace to avoid whisper_context resolving to verbal::whisper_context
struct whisper_context;

namespace verbal {

class WhisperRefinementService : public IRefinementService {
public:
    explicit WhisperRefinementService(const std::string& model_path);
    ~WhisperRefinementService() override;

    WhisperRefinementService(const WhisperRefinementService&) = delete;
    WhisperRefinementService& operator=(const WhisperRefinementService&) = delete;

    Result<void> init() override;
    Result<std::string> refine(const std::vector<AudioSample>& audio, int sample_rate = DEFAULT_SAMPLE_RATE) override;
    bool is_initialized() const override { return ctx_ != nullptr; }

    void set_initial_prompt(const std::string& prompt) override;
    const std::string& get_initial_prompt() const { return initial_prompt_; }

    /// Returns the auto-detected thread count (hardware_concurrency capped at 8, fallback 4).
    int thread_count() const;

private:
    std::string model_path_;
    std::string initial_prompt_;
    ::whisper_context* ctx_ = nullptr;
};

} // namespace verbal
