#pragma once

#include "i_audio_service.hpp"
#include "audio_buffer.hpp"
#include "logger.hpp"

#include <pipewire/pipewire.h>
#include <spa/param/audio/format-utils.h>

#include <atomic>
#include <thread>

namespace verbal {

class PipeWireAudioService : public IAudioService {
public:
    PipeWireAudioService(int sample_rate = DEFAULT_SAMPLE_RATE, int channels = DEFAULT_CHANNELS);
    ~PipeWireAudioService() override;

    // IService
    Result<void> start() override;
    void stop() override;
    bool is_running() const override { return running_.load(std::memory_order_acquire); }

    // IAudioService
    void set_ring_buffer(RingBuffer<AudioSample>* buffer) override { ring_buffer_ = buffer; }
    Result<void> start_capture() override;
    void stop_capture() override;
    bool is_capturing() const override { return capturing_.load(std::memory_order_acquire); }
    const std::vector<AudioSample>& recorded_audio() const override { return recorded_; }
    void set_on_state_change(StateCallback cb) override { state_cb_ = std::move(cb); }

    static void on_process(void* userdata);

private:
    void process_audio();
    void pw_thread_func();

    int sample_rate_;
    int channels_;
    RingBuffer<AudioSample>* ring_buffer_ = nullptr;
    AudioBuffer audio_buffer_;
    std::vector<AudioSample> recorded_; // snapshot on stop
    StateCallback state_cb_;

    // PipeWire objects
    struct pw_main_loop* pw_loop_ = nullptr;
    struct pw_stream* pw_stream_ = nullptr;

    std::thread pw_thread_;
    std::atomic<bool> running_{false};
    std::atomic<bool> capturing_{false};
};

} // namespace verbal
