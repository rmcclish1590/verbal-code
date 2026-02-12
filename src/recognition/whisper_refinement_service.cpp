#include "whisper_refinement_service.hpp"
#include "logger.hpp"

#ifdef VERBAL_ENABLE_WHISPER
#include <whisper.h>
#endif

#include <algorithm>
#include <cmath>
#include <vector>

namespace verbal {

namespace {
constexpr const char* TAG = "Whisper";
} // namespace

WhisperRefinementService::WhisperRefinementService(const std::string& model_path)
    : model_path_(model_path)
{
}

WhisperRefinementService::~WhisperRefinementService() {
#ifdef VERBAL_ENABLE_WHISPER
    if (ctx_) {
        whisper_free(ctx_);
        ctx_ = nullptr;
    }
#endif
}

Result<void> WhisperRefinementService::init() {
#ifdef VERBAL_ENABLE_WHISPER
    if (ctx_) return Result<void>::ok();

    struct whisper_context_params cparams = whisper_context_default_params();
    ctx_ = whisper_init_from_file_with_params(model_path_.c_str(), cparams);
    if (!ctx_) {
        return Result<void>::err("Failed to load Whisper model from: " + model_path_);
    }

    LOG_INFO(TAG, "Whisper model loaded: " + model_path_);
    return Result<void>::ok();
#else
    return Result<void>::err("Whisper support not compiled in");
#endif
}

Result<std::string> WhisperRefinementService::refine(
    const std::vector<AudioSample>& audio, int sample_rate)
{
#ifdef VERBAL_ENABLE_WHISPER
    if (!ctx_) {
        return Result<std::string>::err("Whisper not initialized");
    }

    if (audio.empty()) {
        return Result<std::string>::ok("");
    }

    // Convert int16 PCM to float32 (whisper expects float in [-1, 1])
    std::vector<float> float_audio(audio.size());
    for (size_t i = 0; i < audio.size(); ++i) {
        float_audio[i] = static_cast<float>(audio[i]) / 32768.0f;
    }

    // Resample if needed (whisper.cpp expects 16kHz)
    // For now we assume input is already 16kHz
    (void)sample_rate;

    struct whisper_full_params wparams = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    wparams.print_realtime = false;
    wparams.print_progress = false;
    wparams.print_timestamps = false;
    wparams.single_segment = true;
    wparams.no_context = true;
    wparams.language = "en";
    wparams.n_threads = 4;

    int ret = whisper_full(ctx_, wparams, float_audio.data(), static_cast<int>(float_audio.size()));
    if (ret != 0) {
        return Result<std::string>::err("Whisper inference failed with code: " + std::to_string(ret));
    }

    int n_segments = whisper_full_n_segments(ctx_);
    std::string result;
    for (int i = 0; i < n_segments; ++i) {
        const char* text = whisper_full_get_segment_text(ctx_, i);
        if (text) {
            if (!result.empty()) result += " ";
            result += text;
        }
    }

    // Trim leading/trailing whitespace
    auto start = result.find_first_not_of(" \t\n\r");
    auto end = result.find_last_not_of(" \t\n\r");
    if (start != std::string::npos) {
        result = result.substr(start, end - start + 1);
    }

    LOG_INFO(TAG, "Refined transcription: " + result);
    return Result<std::string>::ok(std::move(result));
#else
    (void)audio;
    (void)sample_rate;
    return Result<std::string>::err("Whisper support not compiled in");
#endif
}

} // namespace verbal
