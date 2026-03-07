# Technology Stack

**Analysis Date:** 2026-03-07

## Languages

**Primary:**
- C++17 (minimum, C++20 features used where supported) - All application code

**Secondary:**
- Bash - Install/setup scripts (`scripts/install.sh`, `scripts/install_deps.sh`, `scripts/download_models.sh`, `scripts/uninstall.sh`)
- CMake 3.22+ - Build system (`CMakeLists.txt`, `cmake/Dependencies.cmake`)

## Runtime

**Environment:**
- Linux desktop (X11 and Wayland sessions supported)
- Runtime session detection via `XDG_SESSION_TYPE` env var (`src/core/session.hpp`)

**Package Manager:**
- System packages via `apt` (Debian/Ubuntu assumed in install scripts)
- C++ dependencies via CMake FetchContent and pre-built downloads

## Frameworks

**Core:**
- No application framework - custom service-oriented architecture
- GTK3 - Used only for overlay/status window (`src/overlay/gtk_overlay_service.cpp`)
- GIO/GLib (gio-2.0) - D-Bus communication for Wayland portal hotkeys (`src/hotkey/portal_hotkey_service.cpp`)

**Testing:**
- GoogleTest v1.14.0 - Unit test framework (FetchContent)
- GoogleMock (GMock) - Mocking framework, bundled with GoogleTest

**Build/Dev:**
- CMake 3.22+ - Build system generator
- g++ 11+ or clang++ 14+ - Compilers
- pkg-config - System dependency detection
- AddressSanitizer + UndefinedBehaviorSanitizer - Debug builds (`-fsanitize=address,undefined`)

## Key Dependencies

**Critical (FetchContent - downloaded at build time):**
- whisper.cpp v1.7.3 - Whisper speech-to-text inference engine (optional, controlled by `ENABLE_WHISPER` CMake option)
  - Source: `https://github.com/ggerganov/whisper.cpp.git`
  - Linked in: `src/recognition/CMakeLists.txt`
- nlohmann/json v3.11.3 - JSON parsing for configuration
  - Source: `https://github.com/nlohmann/json.git`
  - Linked in: `src/core/CMakeLists.txt` (PUBLIC dependency of `verbal_core`)

**Critical (Pre-built download):**
- Vosk v0.3.45 - Real-time speech recognition (Kaldi-based)
  - Downloaded as pre-built shared library from GitHub releases
  - Supports: linux-x86_64, linux-aarch64
  - Download logic: `cmake/Dependencies.cmake` (lines 44-89)
  - Creates INTERFACE IMPORTED target with `libvosk.so`

**System dependencies (pkg-config):**
- PipeWire (libpipewire-0.3) - Audio capture from microphone
  - Package: `libpipewire-0.3-dev`
  - Used by: `src/audio/pipewire_audio_service.cpp`
- XCB + XInput2 (xcb, xcb-xinput) - X11 global hotkey capture
  - Packages: `libxcb1-dev`, `libxcb-xinput-dev`
  - Used by: `src/hotkey/xcb_hotkey_service.cpp`
- xkbcommon + xkbcommon-x11 - Keyboard layout handling
  - Packages: `libxkbcommon-dev`, `libxkbcommon-x11-dev`
  - Used by: `src/hotkey/xcb_hotkey_service.cpp`
- GTK3 (gtk+-3.0) - Overlay UI window
  - Package: `libgtk-3-dev`
  - Used by: `src/overlay/gtk_overlay_service.cpp`
- GIO (gio-2.0) - D-Bus for Wayland portal shortcuts
  - Comes with GTK3/GLib
  - Used by: `src/hotkey/portal_hotkey_service.cpp`
- libxdo - X11 text injection (simulates keyboard input)
  - Package: `libxdo-dev`
  - Used by: `src/injection/xdo_injection_service.cpp`

**Wayland runtime tools (not compile-time deps):**
- `wtype` - Direct Wayland virtual keyboard text injection
- `wl-clipboard` (`wl-copy`, `wl-paste`) - Clipboard access on Wayland
- `ydotool` - Fallback keystroke simulation on Wayland

**Infrastructure:**
- Linux evdev (`/dev/input/event*`) - Kernel-level hotkey capture (no external deps, just kernel headers)
  - Used by: `src/hotkey/evdev_hotkey_service.cpp`

## Configuration

**Application Config:**
- Config file: `~/.config/verbal-code/config.json`
- Default config template: `config/default_config.json`
- Config class: `src/core/config.hpp` / `src/core/config.cpp`
- JSON-based, loaded via nlohmann/json
- Key settings: hotkey bindings, audio sample rate/channels, model names, overlay position, transcription storage

**Model Storage:**
- Models directory: `~/.local/share/verbal-code/models/` (follows XDG_DATA_HOME)
- Vosk model: `vosk-model-small-en-us-0.15/` (directory with model files)
- Whisper model: `ggml-base.en.bin` (single GGML file)
- Model manager: `src/recognition/model_manager.hpp` / `src/recognition/model_manager.cpp`
- Download script: `scripts/download_models.sh`
  - Vosk models from: `https://alphacephei.com/vosk/models/`
  - Whisper models from: `https://huggingface.co/ggerganov/whisper.cpp/`

**Transcription Storage:**
- Path: `~/.config/verbal-code/transcriptions.json`
- Max entries: 1000 (configurable)
- Managed by: `src/app/transcription_store.cpp`

**Build Configuration:**
- CMake options:
  - `BUILD_TESTS` (default: ON) - Build unit tests
  - `ENABLE_WHISPER` (default: ON) - Enable whisper.cpp refinement
  - `CMAKE_BUILD_TYPE` (default: Release) - Build type
- Compile definitions (conditional):
  - `VERBAL_HAS_AUDIO`, `VERBAL_HAS_HOTKEY`, `VERBAL_HAS_XCB_HOTKEY`, `VERBAL_HAS_EVDEV_HOTKEY`
  - `VERBAL_HAS_PORTAL_HOTKEY`, `VERBAL_HAS_INJECTION`, `VERBAL_HAS_XDO_INJECTION`
  - `VERBAL_HAS_WAYLAND_INJECTION`, `VERBAL_HAS_OVERLAY`, `VERBAL_ENABLE_WHISPER`

## Build Commands

```bash
# Install system dependencies (Debian/Ubuntu)
./scripts/install_deps.sh

# Download speech recognition models
./scripts/download_models.sh

# Full install (deps + models + build + install binary)
./scripts/install.sh

# Configure
cmake -B build -DCMAKE_BUILD_TYPE=Release

# Build
cmake --build build -j$(nproc)

# Debug build (with ASan/UBSan)
cmake -B build -DCMAKE_BUILD_TYPE=Debug && cmake --build build -j$(nproc)

# Run all tests
cd build && ctest --output-on-failure

# Run single test
./build/tests/<test_binary_name>
```

## Platform Requirements

**Development:**
- Linux (Debian/Ubuntu recommended)
- g++ 11+ or clang++ 14+
- CMake 3.22+
- pkg-config
- System dev packages: libpipewire-0.3-dev, libxcb1-dev, libxcb-xinput-dev, libxkbcommon-dev, libxkbcommon-x11-dev, libgtk-3-dev, libxdo-dev

**Production:**
- Linux desktop with X11 or Wayland session
- PipeWire audio server running
- For Wayland: user must be in `input` group (for evdev hotkeys)
- Speech models downloaded to `~/.local/share/verbal-code/models/`
- Binary installed to `/usr/local/bin/verbal-code`

**Supported Architectures:**
- x86_64 / amd64
- aarch64 / arm64

---

*Stack analysis: 2026-03-07*
