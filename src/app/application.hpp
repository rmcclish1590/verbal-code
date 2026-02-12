#pragma once

#include "config.hpp"
#include "logger.hpp"
#include "ring_buffer.hpp"
#include "types.hpp"
#include "result.hpp"
#include "transcription_store.hpp"

#include "vosk_recognition_service.hpp"
#include "transcription_orchestrator.hpp"
#include "model_manager.hpp"

#ifdef VERBAL_ENABLE_WHISPER
#include "whisper_refinement_service.hpp"
#endif

#ifdef VERBAL_HAS_AUDIO
#include "pipewire_audio_service.hpp"
#endif

#ifdef VERBAL_HAS_HOTKEY
#include "xcb_hotkey_service.hpp"
#endif

#ifdef VERBAL_HAS_INJECTION
#include "xdo_injection_service.hpp"
#endif

#ifdef VERBAL_HAS_OVERLAY
#include "gtk_overlay_service.hpp"
#endif

#include <memory>
#include <string>

namespace verbal {

class Application {
public:
    Application();
    ~Application();

    Result<void> init(int argc, char* argv[]);
    int run();
    void quit();

private:
    void on_hotkey_press();
    void on_hotkey_release();
    void on_partial_text(const std::string& text);
    void on_refined_text(const std::string& vosk_text, const std::string& refined_text);

    Config config_;
    ModelManager model_manager_;
    std::unique_ptr<TranscriptionStore> transcription_store_;

    std::unique_ptr<RingBuffer<AudioSample>> ring_buffer_;
    std::unique_ptr<VoskRecognitionService> vosk_;
    std::unique_ptr<TranscriptionOrchestrator> orchestrator_;

#ifdef VERBAL_ENABLE_WHISPER
    std::unique_ptr<WhisperRefinementService> whisper_;
#endif

#ifdef VERBAL_HAS_AUDIO
    std::unique_ptr<PipeWireAudioService> audio_;
#endif

#ifdef VERBAL_HAS_HOTKEY
    std::unique_ptr<XcbHotkeyService> hotkey_;
#endif

#ifdef VERBAL_HAS_INJECTION
    std::unique_ptr<XdoInjectionService> injection_;
#endif

#ifdef VERBAL_HAS_OVERLAY
    std::unique_ptr<GtkOverlayService> overlay_;
#endif

    bool recording_ = false;
    std::string partial_text_; // currently displayed partial text
};

} // namespace verbal
