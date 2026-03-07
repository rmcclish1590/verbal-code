# External Integrations

**Analysis Date:** 2026-03-07

## APIs & External Services

**Speech Recognition - Vosk:**
- Vosk API - Real-time streaming speech-to-text (runs locally, no network calls at runtime)
  - SDK/Client: Pre-built `libvosk.so` (C API via `vosk_api.h`)
  - Version: 0.3.45
  - Download: `https://github.com/alphacep/vosk-api/releases/`
  - Integration: `src/recognition/vosk_recognition_service.cpp`
  - Model download: `https://alphacephei.com/vosk/models/` (via `scripts/download_models.sh`)

**Speech Recognition - Whisper.cpp:**
- whisper.cpp - Offline speech-to-text refinement (runs locally, no network calls at runtime)
  - SDK/Client: whisper.cpp C++ library (compiled from source via FetchContent)
  - Version: v1.7.3
  - Integration: `src/recognition/whisper_refinement_service.cpp`
  - Model download: `https://huggingface.co/ggerganov/whisper.cpp/` (via `scripts/download_models.sh`)
  - Optional: controlled by `ENABLE_WHISPER` CMake flag

**D-Bus - XDG Desktop Portal (Wayland only):**
- org.freedesktop.portal.GlobalShortcuts - System-wide hotkey registration on Wayland
  - Bus: Session bus (`G_BUS_TYPE_SESSION`)
  - Bus name: `org.freedesktop.portal.Desktop`
  - Object path: `/org/freedesktop/portal/desktop`
  - Interface: `org.freedesktop.portal.GlobalShortcuts`
  - Methods used: `CreateSession`, `BindShortcuts`
  - Signals consumed: `Activated`, `Deactivated`
  - Client: GIO/GLib D-Bus API (`g_dbus_connection_call_sync`, `g_dbus_connection_signal_subscribe`)
  - Integration: `src/hotkey/portal_hotkey_service.cpp`

## Data Storage

**Databases:**
- None - No database used

**File Storage:**
- Local filesystem only
  - Config: `~/.config/verbal-code/config.json` (JSON, managed by `src/core/config.cpp`)
  - Transcription history: `~/.config/verbal-code/transcriptions.json` (JSON, managed by `src/app/transcription_store.cpp`)
  - ML models: `~/.local/share/verbal-code/models/` (managed by `src/recognition/model_manager.cpp`)
  - Model metadata: `~/.local/share/verbal-code/models/.meta/` (version tracking for update detection)

**Caching:**
- None

## Authentication & Identity

**Auth Provider:**
- Not applicable - Desktop application with no authentication

## Monitoring & Observability

**Error Tracking:**
- None - No external error tracking service

**Logs:**
- Custom singleton logger: `src/core/logger.hpp` / `src/core/logger.cpp`
- Outputs to stdout/stderr with level, tag, and message
- Levels: DEBUG, INFO, WARN, ERROR
- Convenience macros: `LOG_DEBUG(tag, msg)`, `LOG_INFO(tag, msg)`, `LOG_WARN(tag, msg)`, `LOG_ERROR(tag, msg)`
- No log file rotation or persistence

## CI/CD & Deployment

**Hosting:**
- Local Linux desktop installation
- Binary: `/usr/local/bin/verbal-code`
- Desktop entry: `~/.local/share/applications/verbal-code.desktop`
- Icon: `~/.local/share/icons/hicolor/scalable/apps/verbal-code.svg`

**CI Pipeline:**
- No CI/CD pipeline detected (no `.github/workflows/` directory)

**Install/Uninstall:**
- One-click install: `scripts/install.sh` (installs deps, downloads models, builds, installs binary + desktop entry)
- Uninstall: `scripts/uninstall.sh`

## OS-Level Integrations

**Audio Capture (PipeWire):**
- PipeWire audio server for microphone input
  - API: PipeWire C API (libpipewire-0.3)
  - Integration: `src/audio/pipewire_audio_service.cpp`
  - Audio format: 16-bit PCM, 16kHz, mono (configured in `config/default_config.json`)
  - Data flow: PipeWire stream -> lock-free ring buffer (`src/core/ring_buffer.hpp`) -> recognition service

**Keyboard Input - X11 (XCB):**
- XCB + XInput2 for global hotkey capture on X11
  - API: XCB C API, xkbcommon for keycode translation
  - Integration: `src/hotkey/xcb_hotkey_service.cpp`

**Keyboard Input - Linux evdev:**
- Direct `/dev/input/event*` device reading for hotkey capture
  - API: Linux kernel evdev interface (no external library)
  - Integration: `src/hotkey/evdev_hotkey_service.cpp`
  - Requires: user in `input` group

**Text Injection - X11 (libxdo):**
- libxdo (xdotool library) for typing text into focused X11 windows
  - API: xdo C API
  - Integration: `src/injection/xdo_injection_service.cpp`

**Text Injection - Wayland:**
- External CLI tools for text injection on Wayland (no compile-time deps)
  - Primary: `wtype` (virtual keyboard protocol)
  - Fallback: `wl-copy` + `ydotool` (clipboard paste simulation)
  - Integration: `src/injection/wayland_injection_service.cpp`
  - Tool detection: runtime `which`-style checks for available tools

**Display - GTK3 Overlay:**
- GTK3 overlay window showing recording state
  - API: GTK3 C API
  - Integration: `src/overlay/gtk_overlay_service.cpp`
  - Wayland-aware: skips `gtk_window_move`, uses `begin_move_drag` for drag

## Environment Configuration

**Required env vars:**
- None strictly required (XDG defaults are used)

**Influential env vars:**
- `XDG_SESSION_TYPE` - Detected at runtime to choose X11 vs Wayland backends (`src/core/session.hpp`)
- `XDG_DATA_HOME` - Base for model storage (defaults to `~/.local/share`)
- `XDG_CONFIG_HOME` - Base for config storage (defaults to `~/.config`)
- `HOME` - Fallback for XDG paths

**Secrets location:**
- No secrets required - all processing is local

## Webhooks & Callbacks

**Incoming:**
- None

**Outgoing:**
- None

## Network Usage Summary

This application is fully offline at runtime. Network access occurs only during setup:
1. CMake FetchContent downloads (build time): whisper.cpp, nlohmann/json, GoogleTest from GitHub
2. Vosk pre-built library download (build time): from GitHub releases
3. Model downloads (setup time via `scripts/download_models.sh`): from alphacephei.com and huggingface.co

No network calls are made during normal application operation.

---

*Integration audit: 2026-03-07*
