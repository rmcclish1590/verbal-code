#include "application.hpp"
#include "session.hpp"
#include "transcription_orchestrator.hpp"

#include "vosk_recognition_service.hpp"

#ifdef VERBAL_ENABLE_WHISPER
#include "whisper_refinement_service.hpp"
#endif

#ifdef VERBAL_HAS_AUDIO
#include "pipewire_audio_service.hpp"
#endif

#ifdef VERBAL_HAS_EVDEV_HOTKEY
#include "evdev_hotkey_service.hpp"
#endif

#ifdef VERBAL_HAS_XCB_HOTKEY
#include "xcb_hotkey_service.hpp"
#endif

#ifdef VERBAL_HAS_PORTAL_HOTKEY
#include "portal_hotkey_service.hpp"
#endif

#ifdef VERBAL_HAS_XDO_INJECTION
#include "xdo_injection_service.hpp"
#endif

#ifdef VERBAL_HAS_WAYLAND_INJECTION
#include "wayland_injection_service.hpp"
#endif

#ifdef VERBAL_HAS_OVERLAY
#include "gtk_overlay_service.hpp"
#endif

#include <thread>
#include <vector>

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
    auto session = detect_session_type();
    LOG_INFO(TAG, std::string("Session type: ") + session_type_str(session));

    if (auto r = init_config();              r.is_err()) return r;
    if (auto r = init_recognition();         r.is_err()) return r;
    if (auto r = init_audio();               r.is_err()) return r;
    if (auto r = init_hotkey(session);       r.is_err()) return r;
    if (auto r = init_injection(session);    r.is_err()) return r;
    if (auto r = init_overlay(argc, argv);   r.is_err()) return r;

    LOG_INFO(TAG, "Application initialized successfully");
    return Result<void>::ok();
}

Result<void> Application::init_config() {
    config_.load();
    LOG_INFO(TAG, "Configuration loaded");

    if (!config_.save()) {
        LOG_WARN(TAG, "Config file is not writable — settings will NOT persist. "
                      "Check permissions on ~/.config/verbal-code/");
    }

    transcription_store_ = std::make_unique<TranscriptionStore>(
        config_.transcriptions_path(), config_.max_transcriptions());
    transcription_store_->load();

    ring_buffer_ = std::make_unique<RingBuffer<AudioSample>>(RING_BUFFER_SAMPLES);
    model_manager_ = ModelManager();

    return Result<void>::ok();
}

Result<void> Application::init_recognition() {
    // Vosk
    auto vosk_path = model_manager_.vosk_model_path(config_.vosk_model());
    if (vosk_path.is_err()) {
        LOG_ERROR(TAG, vosk_path.error());
        return Result<void>::err(vosk_path.error());
    }

    auto vosk = std::make_unique<VoskRecognitionService>(vosk_path.value(), config_.sample_rate());
    auto vosk_result = vosk->start();
    if (vosk_result.is_err()) {
        return Result<void>::err("Vosk init failed: " + vosk_result.error());
    }
    vosk->set_ring_buffer(ring_buffer_.get());
    vosk_ = std::move(vosk);

    // Whisper
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

    // Orchestrator
    TranscriptionOrchestrator::Config orch_config;
    orch_config.enable_whisper_refinement = config_.whisper_refinement_enabled();

    orchestrator_ = std::make_unique<TranscriptionOrchestrator>(
        vosk_.get(),
        whisper_.get(),
        orch_config
    );

    orchestrator_->set_on_partial([this](const std::string& text) {
        on_partial_text(text);
    });

    orchestrator_->set_on_refined([this](const std::string& vosk_text, const std::string& refined_text) {
        on_refined_text(vosk_text, refined_text);
    });

    return Result<void>::ok();
}

Result<void> Application::init_audio() {
#ifdef VERBAL_HAS_AUDIO
    audio_ = std::make_unique<PipeWireAudioService>(config_.sample_rate(), config_.channels());
    auto audio_result = audio_->start();
    if (audio_result.is_err()) {
        LOG_ERROR(TAG, "Audio service failed: " + audio_result.error());
        return Result<void>::err(audio_result.error());
    }
    audio_->set_ring_buffer(ring_buffer_.get());
#endif
    return Result<void>::ok();
}

Result<void> Application::init_hotkey(SessionType session) {
#ifdef VERBAL_HAS_EVDEV_HOTKEY
    if (session == SessionType::WAYLAND) {
        LOG_INFO(TAG, "Using evdev hotkey service for Wayland");
        hotkey_ = std::make_unique<EvdevHotkeyService>();
    }
#endif
#ifdef VERBAL_HAS_XCB_HOTKEY
    if (!hotkey_ && (session == SessionType::X11 || session == SessionType::UNKNOWN)) {
        LOG_INFO(TAG, "Using XCB hotkey service for X11");
        hotkey_ = std::make_unique<XcbHotkeyService>();
    }
#endif
#ifdef VERBAL_HAS_EVDEV_HOTKEY
    if (!hotkey_) {
        LOG_INFO(TAG, "Falling back to evdev hotkey service");
        hotkey_ = std::make_unique<EvdevHotkeyService>();
    }
#endif
#ifdef VERBAL_HAS_PORTAL_HOTKEY
    if (!hotkey_) {
        LOG_INFO(TAG, "Falling back to portal hotkey service");
        auto portal = std::make_unique<PortalHotkeyService>();
        portal->set_trigger_key(config_.hotkey_trigger_key());
        hotkey_ = std::move(portal);
    }
#endif

    if (hotkey_) {
        hotkey_->set_modifiers(config_.hotkey_modifiers());
        hotkey_->set_on_press([this]() { on_hotkey_press(); });
        hotkey_->set_on_release([this]() { on_hotkey_release(); });
        auto hk_result = hotkey_->start();
        if (hk_result.is_err()) {
            LOG_ERROR(TAG, "Hotkey service failed: " + hk_result.error());
            return Result<void>::err(hk_result.error());
        }
    } else {
        LOG_WARN(TAG, "No hotkey backend available");
    }

    return Result<void>::ok();
}

Result<void> Application::init_injection(SessionType session) {
#ifdef VERBAL_HAS_WAYLAND_INJECTION
    if (session == SessionType::WAYLAND) {
        LOG_INFO(TAG, "Using Wayland injection service");
        injection_ = std::make_unique<WaylandInjectionService>();
    }
#endif
#ifdef VERBAL_HAS_XDO_INJECTION
    if (!injection_ && (session == SessionType::X11 || session == SessionType::UNKNOWN)) {
        LOG_INFO(TAG, "Using Xdo injection service for X11");
        injection_ = std::make_unique<XdoInjectionService>();
    }
#endif
#ifdef VERBAL_HAS_WAYLAND_INJECTION
    if (!injection_) {
        LOG_INFO(TAG, "Falling back to Wayland injection service");
        injection_ = std::make_unique<WaylandInjectionService>();
    }
#endif

    if (injection_) {
        auto inj_result = injection_->start();
        if (inj_result.is_err()) {
            LOG_WARN(TAG, "Injection service failed: " + inj_result.error());
        }
    } else {
        LOG_WARN(TAG, "No injection backend available");
    }

    return Result<void>::ok();
}

Result<void> Application::init_overlay(int argc, char* argv[]) {
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
        if (hotkey_) {
            hotkey_->set_modifiers(modifiers);
        }
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
    if (hotkey_) hotkey_->stop();
    if (injection_) injection_->stop();
    if (audio_) audio_->stop();
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
        g_idle_add(+[](gpointer data) -> gboolean {
            auto* self = static_cast<Application*>(data);
            if (self->overlay_) self->overlay_->set_state(OverlayState::RECORDING);
            return G_SOURCE_REMOVE;
        }, this);
    }
#endif

    if (audio_) {
        audio_->start_capture();
    }

    orchestrator_->on_recording_start();
}

void Application::on_hotkey_release() {
    if (!recording_) return;
    recording_ = false;

    LOG_INFO(TAG, "Recording stopped");

#ifdef VERBAL_HAS_OVERLAY
    if (overlay_) {
        g_idle_add(+[](gpointer data) -> gboolean {
            auto* self = static_cast<Application*>(data);
            if (self->overlay_) self->overlay_->set_state(OverlayState::IDLE);
            return G_SOURCE_REMOVE;
        }, this);
    }
#endif

    // Extract audio on this thread (fast), then move heavy processing
    // (transcription + injection) to a worker thread so the evdev poll
    // thread returns immediately and can process remaining modifier
    // key-release events.  This prevents the deadlock where the
    // modifier-wait loop in on_refined_text() blocks the same thread
    // that updates held_keys_.
    std::vector<AudioSample> audio;
    if (audio_) {
        audio_->stop_capture();
        audio = audio_->recorded_audio();
    }
    std::thread([this, audio = std::move(audio)]() {
        orchestrator_->on_recording_stop(audio);
    }).detach();
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

    // Wait for all modifier keys to be physically released before injecting.
    // The hotkey release fires when the combination breaks (one key lifts),
    // but other modifiers may still be held — injecting while any modifier
    // is down produces garbage output like "4224".
    if (hotkey_) {
        auto start = std::chrono::steady_clock::now();
        constexpr auto MAX_WAIT = std::chrono::milliseconds(2000);
        while (hotkey_->any_modifiers_held() &&
               std::chrono::steady_clock::now() - start < MAX_WAIT) {
            std::this_thread::sleep_for(std::chrono::milliseconds(10));
        }
        auto waited = std::chrono::duration_cast<std::chrono::milliseconds>(
            std::chrono::steady_clock::now() - start).count();
        if (hotkey_->any_modifiers_held()) {
            LOG_WARN(TAG, "Modifier wait timed out after " + std::to_string(waited) +
                          "ms — modifiers still held, injection may produce garbage");
        } else {
            LOG_DEBUG(TAG, "Modifiers released after " + std::to_string(waited) + "ms");
        }
        // Extra settling time for OS to process the key-up events
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

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

    partial_text_.clear();
}

} // namespace verbal
