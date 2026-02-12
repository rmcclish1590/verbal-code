#pragma once

#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace verbal {

using AudioSample = int16_t;

constexpr int DEFAULT_SAMPLE_RATE = 16000;
constexpr int DEFAULT_CHANNELS = 1;
constexpr int SAMPLES_PER_MS = DEFAULT_SAMPLE_RATE / 1000;

// Audio chunk: typically 20-30ms of audio
using AudioChunk = std::vector<AudioSample>;

// Callback types
using TextCallback = std::function<void(const std::string&)>;
using VoidCallback = std::function<void()>;

// Overlay states
enum class OverlayState {
    IDLE,
    RECORDING
};

// Transcription source
enum class TranscriptionSource {
    VOSK,
    WHISPER
};

} // namespace verbal
