#include "transcription_orchestrator.hpp"
#include "logger.hpp"

#include <algorithm>
#include <vector>

namespace verbal {

namespace {
constexpr const char* TAG = "Orchestrator";

// Simple Levenshtein distance
size_t levenshtein(const std::string& a, const std::string& b) {
    const size_t m = a.size();
    const size_t n = b.size();
    std::vector<size_t> prev(n + 1), curr(n + 1);

    for (size_t j = 0; j <= n; ++j) prev[j] = j;

    for (size_t i = 1; i <= m; ++i) {
        curr[0] = i;
        for (size_t j = 1; j <= n; ++j) {
            size_t cost = (a[i - 1] == b[j - 1]) ? 0 : 1;
            curr[j] = std::min({
                prev[j] + 1,       // deletion
                curr[j - 1] + 1,   // insertion
                prev[j - 1] + cost  // substitution
            });
        }
        std::swap(prev, curr);
    }

    return prev[n];
}
} // namespace

TranscriptionOrchestrator::TranscriptionOrchestrator(
    VoskRecognitionService* vosk,
#ifdef VERBAL_ENABLE_WHISPER
    WhisperRefinementService* whisper,
#endif
    Config config)
    : vosk_(vosk)
#ifdef VERBAL_ENABLE_WHISPER
    , whisper_(whisper)
#endif
    , config_(config)
{
}

TranscriptionOrchestrator::TranscriptionOrchestrator(
    VoskRecognitionService* vosk
#ifdef VERBAL_ENABLE_WHISPER
    , WhisperRefinementService* whisper
#endif
)
    : vosk_(vosk)
#ifdef VERBAL_ENABLE_WHISPER
    , whisper_(whisper)
#endif
{
}

void TranscriptionOrchestrator::on_recording_start() {
    vosk_text_.clear();
    was_refined_ = false;

    vosk_->reset();

    // Wire up Vosk partial callback to our callback
    vosk_->set_on_partial([this](const std::string& text) {
        if (on_partial_) on_partial_(text);
    });

    vosk_->set_on_final([this](const std::string& text) {
        vosk_text_ = text;
    });

    vosk_->start_streaming();
    LOG_INFO(TAG, "Recording started");
}

void TranscriptionOrchestrator::on_recording_stop(const std::vector<AudioSample>& audio) {
    vosk_->stop_streaming();

    // Get Vosk's final result
    std::string final_vosk = vosk_->final_result();
    if (!final_vosk.empty()) {
        vosk_text_ = final_vosk;
    }

    LOG_INFO(TAG, "Vosk result: " + vosk_text_);

#ifdef VERBAL_ENABLE_WHISPER
    if (config_.enable_whisper_refinement && whisper_ && whisper_->is_initialized() && !audio.empty()) {
        auto result = whisper_->refine(audio);
        if (result.is_ok()) {
            std::string whisper_text = result.value();
            double ratio = edit_distance_ratio(vosk_text_, whisper_text);

            LOG_INFO(TAG, "Whisper result: " + whisper_text +
                         " (edit distance ratio: " + std::to_string(ratio) + ")");

            if (ratio >= config_.refinement_threshold && !whisper_text.empty()) {
                was_refined_ = true;
                if (on_refined_) {
                    on_refined_(vosk_text_, whisper_text);
                }
                LOG_INFO(TAG, "Refinement applied");
                return;
            }
        } else {
            LOG_WARN(TAG, "Whisper refinement failed: " + result.error());
        }
    }
#else
    (void)audio;
#endif

    // No refinement needed or available
    was_refined_ = false;
    if (on_refined_) {
        on_refined_(vosk_text_, vosk_text_);
    }
}

double TranscriptionOrchestrator::edit_distance_ratio(const std::string& a, const std::string& b) {
    if (a.empty() && b.empty()) return 0.0;
    size_t max_len = std::max(a.size(), b.size());
    size_t dist = levenshtein(a, b);
    return static_cast<double>(dist) / static_cast<double>(max_len);
}

} // namespace verbal
