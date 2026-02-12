#pragma once

#include "i_recognition_service.hpp"
#include "ring_buffer.hpp"
#include "logger.hpp"

#include <vosk_api.h>

#include <atomic>
#include <memory>
#include <thread>
#include <string>

namespace verbal {

class VoskRecognitionService : public IRecognitionService {
public:
    // Construct with path to Vosk model directory
    explicit VoskRecognitionService(const std::string& model_path, int sample_rate = DEFAULT_SAMPLE_RATE);
    ~VoskRecognitionService() override;

    // IService
    Result<void> start() override;
    void stop() override;
    bool is_running() const override { return running_.load(std::memory_order_acquire); }

    // IRecognitionService
    void set_on_partial(TextCallback cb) override { on_partial_ = std::move(cb); }
    void set_on_final(TextCallback cb) override { on_final_ = std::move(cb); }
    void feed_audio(const AudioSample* data, size_t count) override;
    void reset() override;
    std::string final_result() override;

    // Set ring buffer to read from (alternative to feed_audio for streaming)
    void set_ring_buffer(RingBuffer<AudioSample>* buffer) { ring_buffer_ = buffer; }

    // Start/stop the reader thread that pulls from ring buffer
    void start_streaming();
    void stop_streaming();

private:
    void streaming_thread_func();
    void process_chunk(const AudioSample* data, size_t count);
    static std::string extract_text(const char* json_str);

    std::string model_path_;
    int sample_rate_;

    VoskModel* model_ = nullptr;
    VoskRecognizer* recognizer_ = nullptr;

    TextCallback on_partial_;
    TextCallback on_final_;

    RingBuffer<AudioSample>* ring_buffer_ = nullptr;
    std::thread stream_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> streaming_{false};
    std::string last_partial_;
};

} // namespace verbal
