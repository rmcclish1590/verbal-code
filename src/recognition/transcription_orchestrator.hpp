#pragma once

#include "i_recognition_service.hpp"
#include "i_refinement_service.hpp"
#include "types.hpp"
#include "result.hpp"

#include <functional>
#include <string>
#include <vector>

namespace verbal {

// Orchestrates the Vosk + Whisper hybrid STT flow.
// During recording: feeds Vosk, emits partial results.
// After recording: optionally runs Whisper refinement.
class TranscriptionOrchestrator {
public:
    struct Config {
        bool enable_whisper_refinement;
        // Minimum Levenshtein edit distance ratio (0.0–1.0) between Vosk and
        // Whisper outputs required to prefer Whisper. 0.0 = always prefer Whisper,
        // 1.0 = never use Whisper.
        double refinement_threshold;

        Config() : enable_whisper_refinement(true), refinement_threshold(0.2) {}
        Config(bool refinement, double threshold)
            : enable_whisper_refinement(refinement), refinement_threshold(threshold) {}
    };

    explicit TranscriptionOrchestrator(
        IRecognitionService* recognition,
        IRefinementService* refinement = nullptr,
        Config config = Config{});

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

    // Check if refinement produced a different result
    bool was_refined() const { return was_refined_; }

    // Compute simple edit distance ratio between two strings
    static double edit_distance_ratio(const std::string& a, const std::string& b);

private:
    IRecognitionService* recognition_;
    IRefinementService* refinement_;
    Config config_;

    PartialCallback on_partial_;
    RefinedCallback on_refined_;

    std::string vosk_text_;
    bool was_refined_ = false;
};

} // namespace verbal
