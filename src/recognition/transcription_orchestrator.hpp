#pragma once

#include "vosk_recognition_service.hpp"
#include "types.hpp"
#include "result.hpp"

#ifdef VERBAL_ENABLE_WHISPER
#include "whisper_refinement_service.hpp"
#endif

#include <functional>
#include <memory>
#include <string>
#include <vector>

namespace verbal {

// Orchestrates the Vosk + Whisper hybrid STT flow.
// During recording: feeds Vosk, emits partial results.
// After recording: optionally runs Whisper refinement.
class TranscriptionOrchestrator {
public:
    struct Config {
        bool enable_whisper_refinement = true;
        double refinement_threshold = 0.2;
    };

    TranscriptionOrchestrator(
        VoskRecognitionService* vosk,
#ifdef VERBAL_ENABLE_WHISPER
        WhisperRefinementService* whisper,
#endif
        Config config);

    // Convenience: default config
    TranscriptionOrchestrator(
        VoskRecognitionService* vosk
#ifdef VERBAL_ENABLE_WHISPER
        , WhisperRefinementService* whisper
#endif
    );

    // Callbacks
    using PartialCallback = std::function<void(const std::string& text)>;
    using RefinedCallback = std::function<void(const std::string& vosk_text, const std::string& refined_text)>;

    void set_on_partial(PartialCallback cb) { on_partial_ = std::move(cb); }
    void set_on_refined(RefinedCallback cb) { on_refined_ = std::move(cb); }

    // Called when recording starts
    void on_recording_start();

    // Called when recording stops. Triggers refinement if enabled.
    // audio: the full recording for Whisper processing
    void on_recording_stop(const std::vector<AudioSample>& audio);

    // Get the last Vosk result
    const std::string& vosk_result() const { return vosk_text_; }

    // Check if refinement produced a different result
    bool was_refined() const { return was_refined_; }

    // Compute simple edit distance ratio between two strings
    static double edit_distance_ratio(const std::string& a, const std::string& b);

private:
    VoskRecognitionService* vosk_;
#ifdef VERBAL_ENABLE_WHISPER
    WhisperRefinementService* whisper_;
#endif
    Config config_;

    PartialCallback on_partial_;
    RefinedCallback on_refined_;

    std::string vosk_text_;
    bool was_refined_ = false;
};

} // namespace verbal
