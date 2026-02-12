# verbal-code

System-wide push-to-talk voice-to-text for Linux. Hold a hotkey, speak, and text appears in real-time in whatever input field is focused — terminal, browser, IDE, etc.

Uses **Vosk** for real-time streaming transcription (words appear as you speak) with optional **whisper.cpp** post-processing for accuracy refinement.

## How it works

1. Hold **Ctrl+Super+Alt** (configurable) — a small overlay dot turns green
2. Speak — text is typed into the focused window in real-time via Vosk
3. Release the hotkey — whisper.cpp refines the transcription and corrects if needed
4. If no input field is focused, the transcription is saved to `~/.config/verbal-code/transcriptions.json`

## Dependencies

### System libraries

```bash
sudo apt install \
    build-essential cmake pkg-config \
    libpipewire-0.3-dev \
    libxcb1-dev libxcb-xinput-dev \
    libxkbcommon-dev libxkbcommon-x11-dev \
    libgtk-3-dev \
    libxdo-dev
```

Or run the install script:

```bash
./scripts/install_deps.sh
```

### Speech models

Download the Vosk and Whisper models (~200MB total):

```bash
./scripts/download_models.sh
```

Models are stored in `~/.local/share/verbal-code/models/`.

## Build

```bash
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j$(nproc)
```

The build system gracefully handles missing optional dependencies — modules that require unavailable system libraries are skipped automatically.

## Run

```bash
./build/src/app/verbal-code
```

## Test

```bash
cd build && ctest --output-on-failure
```

## Configuration

Config lives at `~/.config/verbal-code/config.json`. A default is created on first run.

```json
{
    "hotkey": {
        "modifiers": ["ctrl", "super", "alt"]
    },
    "audio": {
        "sample_rate": 16000,
        "channels": 1
    },
    "recognition": {
        "vosk_model": "vosk-model-small-en-us-0.15",
        "whisper_model": "base.en",
        "enable_whisper_refinement": true
    },
    "overlay": {
        "position": { "x": -1, "y": -1 },
        "size": 20
    },
    "storage": {
        "transcriptions_path": "~/.config/verbal-code/transcriptions.json",
        "max_transcriptions": 1000
    }
}
```

## Architecture

```
src/
  core/           Shared types, ring buffer, config, logging
  audio/          PipeWire audio capture
  recognition/    Vosk streaming STT + whisper.cpp refinement
  hotkey/         XCB global hotkey detection
  injection/      libxdo text injection
  overlay/        GTK3 status dot overlay
  app/            Service orchestration and entry point
```

Each module is an isolated service with an abstract interface (`I`-prefixed), enabling dependency injection and mock-based testing.

## Tech stack

| Component | Library |
|-----------|---------|
| Audio capture | PipeWire |
| Real-time STT | Vosk |
| Accuracy refinement | whisper.cpp |
| Global hotkeys | XCB + libxkbcommon |
| Overlay UI | GTK3 |
| Text injection | libxdo |
| JSON | nlohmann/json |
| Testing | GoogleTest |
