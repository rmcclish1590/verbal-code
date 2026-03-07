#pragma once

#include "config.hpp"
#include "ring_buffer.hpp"
#include "session.hpp"
#include "types.hpp"
#include "result.hpp"
#include "transcription_store.hpp"
#include "model_manager.hpp"

#include "i_audio_service.hpp"
#include "i_recognition_service.hpp"
#include "i_refinement_service.hpp"
#include "i_hotkey_service.hpp"
#include "i_injection_service.hpp"
#include "i_overlay_service.hpp"

#include <memory>
#include <string>

namespace verbal {

class TranscriptionOrchestrator;

class Application {
public:
    Application();
    ~Application();

    Result<void> init(int argc, char* argv[]);
    int run();
    void quit();

private:
    // init() decomposition
    Result<void> init_config();
    Result<void> init_recognition();
    Result<void> init_audio();
    Result<void> init_hotkey(SessionType session);
    Result<void> init_injection(SessionType session);
    Result<void> init_overlay(int argc, char* argv[]);

    void on_hotkey_press();
    void on_hotkey_release();
    void on_partial_text(const std::string& text);
    void on_refined_text(const std::string& vosk_text, const std::string& refined_text);
    void wait_for_modifiers_released();
    void try_inject_text(const std::string& text);

    Config config_;
    ModelManager model_manager_;
    std::unique_ptr<TranscriptionStore> transcription_store_;

    std::unique_ptr<RingBuffer<AudioSample>> ring_buffer_;
    std::unique_ptr<IRecognitionService> vosk_;
    std::unique_ptr<TranscriptionOrchestrator> orchestrator_;
    std::unique_ptr<IRefinementService> whisper_;
    std::unique_ptr<IAudioService> audio_;

    std::unique_ptr<IHotkeyService> hotkey_;
    std::unique_ptr<IInjectionService> injection_;
    std::unique_ptr<IOverlayService> overlay_;

    bool recording_ = false;
};

} // namespace verbal
