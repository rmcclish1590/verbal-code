#include "application.hpp"

namespace verbal {

namespace {
constexpr const char* TAG = "App";
constexpr size_t RING_BUFFER_SAMPLES = 16000 * 10; // 10 seconds of audio
} // namespace

Application::Application() = default;

Application::~Application() {
    quit();
}

Result<void> Application::init(int argc, char* argv[]) {
    // Load config
    config_.load();
    LOG_INFO(TAG, "Configuration loaded");

    // Warn early if config is not writable (permissions, disk full, etc.)
    if (!config_.save()) {
        LOG_WARN(TAG, "Config file is not writable — settings will NOT persist. "
                      "Check permissions on ~/.config/verbal-code/");
    }

    // Create transcription store
    transcription_store_ = std::make_unique<TranscriptionStore>(
        config_.transcriptions_path(), config_.max_transcriptions());
    transcription_store_->load();

    // Create ring buffer
    ring_buffer_ = std::make_unique<RingBuffer<AudioSample>>(RING_BUFFER_SAMPLES);

    // Initialize model manager
    model_manager_ = ModelManager();

    // ── Vosk ─────────────────────────────────────────────
    auto vosk_path = model_manager_.vosk_model_path(config_.vosk_model());
    if (vosk_path.is_err()) {
        LOG_ERROR(TAG, vosk_path.error());
        return Result<void>::err(vosk_path.error());
    }

    vosk_ = std::make_unique<VoskRecognitionService>(vosk_path.value(), config_.sample_rate());
    auto vosk_result = vosk_->start();
    if (vosk_result.is_err()) {
        return Result<void>::err("Vosk init failed: " + vosk_result.error());
    }
    vosk_->set_ring_buffer(ring_buffer_.get());

    // ── Whisper ──────────────────────────────────────────
#ifdef VERBAL_ENABLE_WHISPER
    if (config_.whisper_refinement_enabled()) {
        auto whisper_path = model_manager_.whisper_model_path(config_.whisper_model());
        if (whisper_path.is_ok()) {
            whisper_ = std::make_unique<WhisperRefinementService>(whisper_path.value());
            auto wr = whisper_->init();
            if (wr.is_err()) {
                LOG_WARN(TAG, "Whisper init failed: " + wr.error() + ". Refinement disabled.");
                whisper_.reset();
            }
        } else {
            LOG_WARN(TAG, whisper_path.error());
        }
    }
#endif

    // ── Orchestrator ─────────────────────────────────────
    TranscriptionOrchestrator::Config orch_config;
    orch_config.enable_whisper_refinement = config_.whisper_refinement_enabled();

    orchestrator_ = std::make_unique<TranscriptionOrchestrator>(
        vosk_.get(),
#ifdef VERBAL_ENABLE_WHISPER
        whisper_.get(),
#endif
        orch_config
    );

    orchestrator_->set_on_partial([this](const std::string& text) {
        on_partial_text(text);
    });

    orchestrator_->set_on_refined([this](const std::string& vosk_text, const std::string& refined_text) {
        on_refined_text(vosk_text, refined_text);
    });

    // ── Audio ────────────────────────────────────────────
#ifdef VERBAL_HAS_AUDIO
    audio_ = std::make_unique<PipeWireAudioService>(config_.sample_rate(), config_.channels());
    auto audio_result = audio_->start();
    if (audio_result.is_err()) {
        LOG_ERROR(TAG, "Audio service failed: " + audio_result.error());
        return Result<void>::err(audio_result.error());
    }
    audio_->set_ring_buffer(ring_buffer_.get());
#endif

    // ── Hotkey ───────────────────────────────────────────
#ifdef VERBAL_HAS_HOTKEY
    hotkey_ = std::make_unique<XcbHotkeyService>();
    hotkey_->set_modifiers(config_.hotkey_modifiers());
    hotkey_->set_on_press([this]() { on_hotkey_press(); });
    hotkey_->set_on_release([this]() { on_hotkey_release(); });
    auto hk_result = hotkey_->start();
    if (hk_result.is_err()) {
        LOG_ERROR(TAG, "Hotkey service failed: " + hk_result.error());
        return Result<void>::err(hk_result.error());
    }
#endif

    // ── Injection ────────────────────────────────────────
#ifdef VERBAL_HAS_INJECTION
    injection_ = std::make_unique<XdoInjectionService>();
    auto inj_result = injection_->start();
    if (inj_result.is_err()) {
        LOG_WARN(TAG, "Injection service failed: " + inj_result.error());
    }
#endif

    // ── Overlay ──────────────────────────────────────────
#ifdef VERBAL_HAS_OVERLAY
    gtk_init(&argc, &argv);

    overlay_ = std::make_unique<GtkOverlayService>(config_.overlay_size());
    if (config_.overlay_x() >= 0 && config_.overlay_y() >= 0) {
        overlay_->set_position(config_.overlay_x(), config_.overlay_y());
    }
    overlay_->set_on_position_changed([this](int x, int y) {
        config_.set_overlay_position(x, y);
        if (!config_.save()) {
            LOG_WARN(TAG, "Failed to save config after overlay position change");
        }
    });
    overlay_->set_on_quit_requested([this]() {
        quit();
    });
    overlay_->set_on_hotkey_change([this](const std::vector<std::string>& modifiers) {
        config_.set_hotkey_modifiers(modifiers);
        if (!config_.save()) {
            LOG_WARN(TAG, "Failed to save config after hotkey change");
        }
#ifdef VERBAL_HAS_HOTKEY
        if (hotkey_) {
            hotkey_->set_modifiers(modifiers);
        }
#endif
        overlay_->set_current_modifiers(modifiers);
    });
    overlay_->set_on_history_requested([this]() {
        if (transcription_store_) {
            std::vector<std::string> texts;
            const auto& entries = transcription_store_->entries();
            texts.reserve(entries.size());
            for (const auto& entry : entries) {
                texts.push_back(entry.text);
            }
            overlay_->show_history_dialog(texts);
        }
    });
    overlay_->set_current_modifiers(config_.hotkey_modifiers());
    auto ov_result = overlay_->start();
    if (ov_result.is_err()) {
        LOG_WARN(TAG, "Overlay failed: " + ov_result.error());
    } else {
        overlay_->show();
    }
#else
    (void)argc;
    (void)argv;
#endif

    LOG_INFO(TAG, "Application initialized successfully");
    return Result<void>::ok();
}

int Application::run() {
#ifdef VERBAL_HAS_OVERLAY
    LOG_INFO(TAG, "Starting GTK main loop");
    gtk_main();
#else
    LOG_INFO(TAG, "No overlay available, running in headless mode. Press Ctrl+C to quit.");
    while (true) {
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }
#endif
    return 0;
}

void Application::quit() {
#ifdef VERBAL_HAS_OVERLAY
    if (overlay_) overlay_->stop();
    gtk_main_quit();
#endif
#ifdef VERBAL_HAS_HOTKEY
    if (hotkey_) hotkey_->stop();
#endif
#ifdef VERBAL_HAS_INJECTION
    if (injection_) injection_->stop();
#endif
#ifdef VERBAL_HAS_AUDIO
    if (audio_) audio_->stop();
#endif
    if (vosk_) vosk_->stop();

    if (!config_.save()) {
        LOG_WARN(TAG, "Failed to save config on shutdown");
    }
    if (transcription_store_) transcription_store_->save();

    LOG_INFO(TAG, "Application shut down");
}

void Application::on_hotkey_press() {
    if (recording_) return;
    recording_ = true;
    partial_text_.clear();

    LOG_INFO(TAG, "Recording started");

#ifdef VERBAL_HAS_OVERLAY
    if (overlay_) {
        g_idle_add([](gpointer data) -> gboolean {
            auto* self = static_cast<Application*>(data);
            self->overlay_->set_state(OverlayState::RECORDING);
            return G_SOURCE_REMOVE;
        }, this);
    }
#endif

#ifdef VERBAL_HAS_AUDIO
    if (audio_) {
        audio_->start_capture();
    }
#endif

    orchestrator_->on_recording_start();
}

void Application::on_hotkey_release() {
    if (!recording_) return;
    recording_ = false;

    LOG_INFO(TAG, "Recording stopped");

#ifdef VERBAL_HAS_OVERLAY
    if (overlay_) {
        g_idle_add([](gpointer data) -> gboolean {
            auto* self = static_cast<Application*>(data);
            self->overlay_->set_state(OverlayState::IDLE);
            return G_SOURCE_REMOVE;
        }, this);
    }
#endif

#ifdef VERBAL_HAS_AUDIO
    std::vector<AudioSample> audio;
    if (audio_) {
        audio_->stop_capture();
        audio = audio_->recorded_audio();
    }
    orchestrator_->on_recording_stop(audio);
#else
    orchestrator_->on_recording_stop({});
#endif
}

void Application::on_partial_text(const std::string& text) {
    // Don't inject partials during recording — modifier keys (Ctrl+Super+Alt)
    // are still held, so xdotool keystrokes combine with them and produce nothing.
    // We track the partial text for logging; final injection happens on release.
    LOG_DEBUG(TAG, "Partial: " + text);
    partial_text_ = text;
}

void Application::on_refined_text(const std::string& vosk_text, const std::string& refined_text) {
    TranscriptionSource source = (vosk_text != refined_text)
        ? TranscriptionSource::WHISPER
        : TranscriptionSource::VOSK;
    std::string final_text = (source == TranscriptionSource::WHISPER) ? refined_text : vosk_text;

    if (final_text.empty()) return;

    LOG_INFO(TAG, "Final text (" + std::string(source == TranscriptionSource::WHISPER ? "whisper" : "vosk") + "): " + final_text);

    // Always store transcription for history
    transcription_store_->append(final_text, source);
    transcription_store_->save();

#ifdef VERBAL_HAS_INJECTION
    if (injection_ && injection_->is_running()) {
        if (injection_->has_focused_input()) {
            auto result = injection_->inject_text(final_text);
            if (result.is_err()) {
                LOG_WARN(TAG, "Injection failed: " + result.error());
            }
        } else {
            LOG_INFO(TAG, "No focused input, transcription saved to store");
        }
    }
#endif

    partial_text_.clear();
}

} // namespace verbal
