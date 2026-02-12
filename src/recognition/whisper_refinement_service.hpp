#pragma once

#include "result.hpp"
#include "types.hpp"

#include <string>
#include <vector>

// Forward declare in global namespace to avoid whisper_context resolving to verbal::whisper_context
struct whisper_context;

namespace verbal {

class WhisperRefinementService {
public:
    explicit WhisperRefinementService(const std::string& model_path);
    ~WhisperRefinementService();

    WhisperRefinementService(const WhisperRefinementService&) = delete;
    WhisperRefinementService& operator=(const WhisperRefinementService&) = delete;

    // Initialize whisper context
    Result<void> init();

    // Process audio and return refined transcription
    Result<std::string> refine(const std::vector<AudioSample>& audio, int sample_rate = DEFAULT_SAMPLE_RATE);

    bool is_initialized() const { return ctx_ != nullptr; }

private:
    std::string model_path_;
    ::whisper_context* ctx_ = nullptr;
};

} // namespace verbal
