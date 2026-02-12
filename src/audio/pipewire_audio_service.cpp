#include "pipewire_audio_service.hpp"

#include <spa/param/audio/format-utils.h>
#include <spa/param/props.h>

#include <cstring>

namespace verbal {

namespace {
constexpr const char* TAG = "Audio";

struct pw_stream_events make_stream_events() {
    struct pw_stream_events events = {};
    events.version = PW_VERSION_STREAM_EVENTS;
    events.process = PipeWireAudioService::on_process;
    return events;
}

const struct pw_stream_events stream_events = make_stream_events();
} // namespace

PipeWireAudioService::PipeWireAudioService(int sample_rate, int channels)
    : sample_rate_(sample_rate)
    , channels_(channels)
{
    pw_init(nullptr, nullptr);
}

PipeWireAudioService::~PipeWireAudioService() {
    stop();
    pw_deinit();
}

Result<void> PipeWireAudioService::start() {
    if (running_.load()) {
        return Result<void>::ok();
    }

    pw_loop_ = pw_main_loop_new(nullptr);
    if (!pw_loop_) {
        return Result<void>::err("Failed to create PipeWire main loop");
    }

    auto props = pw_properties_new(
        PW_KEY_MEDIA_TYPE, "Audio",
        PW_KEY_MEDIA_CATEGORY, "Capture",
        PW_KEY_MEDIA_ROLE, "Communication",
        PW_KEY_NODE_NAME, "verbal-code",
        PW_KEY_APP_NAME, "verbal-code",
        nullptr
    );

    pw_stream_ = pw_stream_new_simple(
        pw_main_loop_get_loop(pw_loop_),
        "verbal-code-capture",
        props,
        &stream_events,
        this
    );

    if (!pw_stream_) {
        pw_main_loop_destroy(pw_loop_);
        pw_loop_ = nullptr;
        return Result<void>::err("Failed to create PipeWire stream");
    }

    // Configure audio format: 16-bit signed int, mono, 16kHz
    uint8_t buffer[1024];
    struct spa_pod_builder b = SPA_POD_BUILDER_INIT(buffer, sizeof(buffer));
    struct spa_audio_info_raw audio_info = {};
    audio_info.format = SPA_AUDIO_FORMAT_S16_LE;
    audio_info.rate = static_cast<uint32_t>(sample_rate_);
    audio_info.channels = static_cast<uint32_t>(channels_);

    const struct spa_pod* params[1];
    params[0] = spa_format_audio_raw_build(&b, SPA_PARAM_EnumFormat, &audio_info);

    auto flags = static_cast<pw_stream_flags>(
        PW_STREAM_FLAG_AUTOCONNECT | PW_STREAM_FLAG_MAP_BUFFERS);

    int ret = pw_stream_connect(
        pw_stream_,
        PW_DIRECTION_INPUT,
        PW_ID_ANY,
        flags,
        params, 1
    );

    if (ret < 0) {
        pw_stream_destroy(pw_stream_);
        pw_main_loop_destroy(pw_loop_);
        pw_stream_ = nullptr;
        pw_loop_ = nullptr;
        return Result<void>::err("Failed to connect PipeWire stream: " + std::string(strerror(-ret)));
    }

    running_.store(true, std::memory_order_release);

    // Run PipeWire loop in background thread
    pw_thread_ = std::thread(&PipeWireAudioService::pw_thread_func, this);

    LOG_INFO(TAG, "PipeWire audio service started");
    return Result<void>::ok();
}

void PipeWireAudioService::stop() {
    if (!running_.load()) return;

    capturing_.store(false, std::memory_order_release);
    running_.store(false, std::memory_order_release);

    if (pw_loop_) {
        pw_main_loop_quit(pw_loop_);
    }

    if (pw_thread_.joinable()) {
        pw_thread_.join();
    }

    if (pw_stream_) {
        pw_stream_destroy(pw_stream_);
        pw_stream_ = nullptr;
    }
    if (pw_loop_) {
        pw_main_loop_destroy(pw_loop_);
        pw_loop_ = nullptr;
    }

    LOG_INFO(TAG, "PipeWire audio service stopped");
}

Result<void> PipeWireAudioService::start_capture() {
    if (!running_.load()) {
        return Result<void>::err("Audio service not started");
    }
    audio_buffer_.clear();
    capturing_.store(true, std::memory_order_release);
    if (state_cb_) state_cb_(true);
    LOG_INFO(TAG, "Capture started");
    return Result<void>::ok();
}

void PipeWireAudioService::stop_capture() {
    capturing_.store(false, std::memory_order_release);
    recorded_ = audio_buffer_.get_samples();
    if (state_cb_) state_cb_(false);
    LOG_INFO(TAG, "Capture stopped, recorded " +
             std::to_string(recorded_.size()) + " samples (" +
             std::to_string(recorded_.size() / SAMPLES_PER_MS) + " ms)");
}

void PipeWireAudioService::on_process(void* userdata) {
    auto* self = static_cast<PipeWireAudioService*>(userdata);
    self->process_audio();
}

void PipeWireAudioService::process_audio() {
    if (!capturing_.load(std::memory_order_acquire)) return;

    struct pw_buffer* buf = pw_stream_dequeue_buffer(pw_stream_);
    if (!buf) return;

    struct spa_buffer* spa_buf = buf->buffer;
    if (!spa_buf->datas[0].data) {
        pw_stream_queue_buffer(pw_stream_, buf);
        return;
    }

    auto* samples = static_cast<AudioSample*>(spa_buf->datas[0].data);
    uint32_t n_samples = spa_buf->datas[0].chunk->size / sizeof(AudioSample);

    // Write to ring buffer for real-time STT
    if (ring_buffer_) {
        ring_buffer_->write(samples, n_samples);
    }

    // Also accumulate for Whisper post-processing
    audio_buffer_.append(samples, n_samples);

    pw_stream_queue_buffer(pw_stream_, buf);
}

void PipeWireAudioService::pw_thread_func() {
    pw_main_loop_run(pw_loop_);
}

} // namespace verbal
