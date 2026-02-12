#include "vosk_recognition_service.hpp"

#include <nlohmann/json.hpp>

#include <chrono>
#include <cstring>
#include <vector>

namespace verbal {

namespace {
constexpr const char* TAG = "Vosk";
constexpr size_t CHUNK_SAMPLES = 480; // 30ms at 16kHz
} // namespace

VoskRecognitionService::VoskRecognitionService(const std::string& model_path, int sample_rate)
    : model_path_(model_path)
    , sample_rate_(sample_rate)
{
}

VoskRecognitionService::~VoskRecognitionService() {
    stop();
}

Result<void> VoskRecognitionService::start() {
    if (running_.load()) return Result<void>::ok();

    vosk_set_log_level(-1); // Suppress Vosk internal logging

    model_ = vosk_model_new(model_path_.c_str());
    if (!model_) {
        return Result<void>::err("Failed to load Vosk model from: " + model_path_);
    }

    recognizer_ = vosk_recognizer_new(model_, static_cast<float>(sample_rate_));
    if (!recognizer_) {
        vosk_model_free(model_);
        model_ = nullptr;
        return Result<void>::err("Failed to create Vosk recognizer");
    }

    vosk_recognizer_set_partial_words(recognizer_, 0);

    running_.store(true, std::memory_order_release);
    LOG_INFO(TAG, "Vosk recognition service started with model: " + model_path_);
    return Result<void>::ok();
}

void VoskRecognitionService::stop() {
    stop_streaming();

    running_.store(false, std::memory_order_release);

    if (recognizer_) {
        vosk_recognizer_free(recognizer_);
        recognizer_ = nullptr;
    }
    if (model_) {
        vosk_model_free(model_);
        model_ = nullptr;
    }

    LOG_INFO(TAG, "Vosk recognition service stopped");
}

void VoskRecognitionService::feed_audio(const AudioSample* data, size_t count) {
    if (!recognizer_ || !running_.load()) return;
    process_chunk(data, count);
}

void VoskRecognitionService::reset() {
    if (recognizer_) {
        vosk_recognizer_reset(recognizer_);
    }
    last_partial_.clear();
}

std::string VoskRecognitionService::final_result() {
    if (!recognizer_) return "";
    const char* result = vosk_recognizer_final_result(recognizer_);
    return extract_text(result);
}

void VoskRecognitionService::start_streaming() {
    if (!ring_buffer_ || streaming_.load()) return;

    streaming_.store(true, std::memory_order_release);
    stream_thread_ = std::thread(&VoskRecognitionService::streaming_thread_func, this);
    LOG_INFO(TAG, "Streaming from ring buffer started");
}

void VoskRecognitionService::stop_streaming() {
    streaming_.store(false, std::memory_order_release);
    if (stream_thread_.joinable()) {
        stream_thread_.join();
    }
}

void VoskRecognitionService::streaming_thread_func() {
    std::vector<AudioSample> chunk(CHUNK_SAMPLES);

    while (streaming_.load(std::memory_order_acquire)) {
        if (!ring_buffer_) break;

        size_t available = ring_buffer_->available_read();
        if (available >= CHUNK_SAMPLES) {
            size_t n = ring_buffer_->read(chunk.data(), CHUNK_SAMPLES);
            if (n > 0) {
                process_chunk(chunk.data(), n);
            }
        } else {
            std::this_thread::sleep_for(std::chrono::milliseconds(5));
        }
    }
}

void VoskRecognitionService::process_chunk(const AudioSample* data, size_t count) {
    if (!recognizer_) return;

    int result = vosk_recognizer_accept_waveform_s(
        recognizer_,
        data,
        static_cast<int>(count)
    );

    if (result > 0) {
        // Final result for this utterance segment
        const char* final_json = vosk_recognizer_result(recognizer_);
        std::string text = extract_text(final_json);
        if (!text.empty() && on_final_) {
            on_final_(text);
        }
    } else {
        // Partial result
        const char* partial_json = vosk_recognizer_partial_result(recognizer_);
        std::string text = extract_text(partial_json);
        if (text != last_partial_ && !text.empty()) {
            last_partial_ = text;
            if (on_partial_) {
                on_partial_(text);
            }
        }
    }
}

std::string VoskRecognitionService::extract_text(const char* json_str) {
    if (!json_str) return "";
    try {
        auto j = nlohmann::json::parse(json_str);
        // Vosk returns {"text": "..."} or {"partial": "..."}
        if (j.contains("text") && !j["text"].get<std::string>().empty()) {
            return j["text"].get<std::string>();
        }
        if (j.contains("partial") && !j["partial"].get<std::string>().empty()) {
            return j["partial"].get<std::string>();
        }
    } catch (...) {}
    return "";
}

} // namespace verbal
