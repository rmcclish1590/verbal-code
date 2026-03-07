# Architecture

**Analysis Date:** 2026-03-07

## Pattern Overview

**Overall:** Modular service architecture with interface-based dependency injection

**Key Characteristics:**
- Each concern (audio, recognition, hotkey, injection, overlay) is an isolated service behind an abstract interface (`I`-prefixed)
- Services are owned by a central `Application` orchestrator via `std::unique_ptr<IServiceInterface>`
- Platform backends (X11 vs Wayland) are selected at runtime based on `XDG_SESSION_TYPE`, using the same interface
- Conditional compilation (`#ifdef VERBAL_HAS_*`) gates platform-specific backends; the app gracefully degrades when a backend is unavailable
- Communication between services is callback-based (`std::function`), not event-bus or message-queue

## Layers

**Core Layer:**
- Purpose: Shared types, utilities, error handling, configuration, logging
- Location: `src/core/`
- Contains: `Result<T>` error type, `RingBuffer<T>` lock-free SPSC buffer, `Config` (JSON-backed), `Logger` (singleton), `IService` base interface, `SessionType` detection, shared type aliases (`AudioSample`, `TextCallback`, `VoidCallback`)
- Depends on: nlohmann/json (for Config)
- Used by: All other layers

**Audio Layer:**
- Purpose: Microphone capture via PipeWire
- Location: `src/audio/`
- Contains: `IAudioService` interface, `PipeWireAudioService` implementation, `AudioBuffer` helper
- Depends on: Core layer, PipeWire system library
- Used by: Application (writes samples into shared `RingBuffer`)

**Recognition Layer:**
- Purpose: Speech-to-text processing (streaming + batch refinement)
- Location: `src/recognition/`
- Contains: `IRecognitionService` (streaming STT), `IRefinementService` (batch post-processing), `VoskRecognitionService`, `WhisperRefinementService`, `TranscriptionOrchestrator`, `ModelManager`
- Depends on: Core layer, Vosk pre-built library, whisper.cpp (optional)
- Used by: Application (via orchestrator callbacks)

**Hotkey Layer:**
- Purpose: Global hotkey detection (push-to-talk trigger)
- Location: `src/hotkey/`
- Contains: `IHotkeyService` interface, three backend implementations:
  - `EvdevHotkeyService` - Direct Linux evdev input (Wayland primary, universal fallback)
  - `XcbHotkeyService` - XCB/XInput2 (X11 primary)
  - `PortalHotkeyService` - D-Bus GlobalShortcuts portal (last-resort fallback)
- Depends on: Core layer, platform libs (linux/input.h, xcb, xkbcommon, gio)
- Used by: Application

**Injection Layer:**
- Purpose: Typing transcribed text into the focused application
- Location: `src/injection/`
- Contains: `IInjectionService` interface, two backend implementations:
  - `XdoInjectionService` - X11 (libxdo with clipboard-paste and xdotool fallbacks)
  - `WaylandInjectionService` - Wayland (wtype primary, wl-clipboard+ydotool fallback)
- Depends on: Core layer, libxdo (X11), external CLI tools (wtype, wl-copy, ydotool)
- Used by: Application

**Overlay Layer:**
- Purpose: Visual indicator dot (GTK3 window) with context menu for settings/history
- Location: `src/overlay/`
- Contains: `IOverlayService` interface, `GtkOverlayService` implementation
- Depends on: Core layer, GTK3
- Used by: Application (drives the GTK main loop)

**Application Layer:**
- Purpose: Service orchestration, lifecycle management, event wiring
- Location: `src/app/`
- Contains: `Application` class (composes all services), `TranscriptionStore` (JSON-backed history), `main.cpp` entry point
- Depends on: All other layers (through interfaces)
- Used by: `main.cpp`

## Data Flow

**Push-to-Talk Recording Flow:**

1. User holds hotkey combination (detected by `IHotkeyService` backend on its poll thread)
2. `IHotkeyService` fires `on_press_` callback into `Application::on_hotkey_press()`
3. `Application` sets `recording_ = true`, tells `IAudioService::start_capture()` to begin writing to `RingBuffer`
4. `PipeWireAudioService` captures mic samples, writes them into shared `RingBuffer<AudioSample>` AND accumulates a full copy in `recorded_audio_`
5. `VoskRecognitionService` reads from `RingBuffer` on its streaming thread, emits partial text via callback (currently logged, not injected during recording due to modifier interference)
6. User releases hotkey; `on_release_` fires `Application::on_hotkey_release()`
7. `Application` calls `audio_->stop_capture()`, extracts `recorded_audio()`, spawns a **detached worker thread** for transcription
8. Worker thread calls `TranscriptionOrchestrator::on_recording_stop(audio)`
9. Orchestrator gets Vosk's `final_result()`, optionally runs Whisper refinement on the full audio buffer
10. Orchestrator computes edit-distance ratio between Vosk and Whisper outputs; if difference exceeds threshold (0.2), prefers Whisper
11. Orchestrator fires `on_refined_` callback back into `Application::on_refined_text()`
12. `Application` saves to `TranscriptionStore`, waits for physical modifier keys to be released (polls `any_modifiers_held()`), then calls `IInjectionService::inject_text()`

**Audio Pipeline (Lock-Free):**

```
PipeWire callback thread → RingBuffer<int16_t> → Vosk streaming thread
                         (SPSC, acquire/release)
```

- `RingBuffer` is 10 seconds capacity (160,000 samples at 16kHz)
- Cache-line aligned atomics (`alignas(64)`) prevent false sharing
- No allocations in the hot path

**State Management:**
- `Config` persists to `~/.config/verbal-code/config.json` (JSON via nlohmann/json)
- `TranscriptionStore` persists to `~/.config/verbal-code/transcriptions.json`
- `recording_` boolean in `Application` tracks push-to-talk state
- Overlay position saved to config on drag

## Key Abstractions

**IService (base interface):**
- Purpose: Uniform lifecycle for all services
- Location: `src/core/i_service.hpp`
- Pattern: `start() -> Result<void>`, `stop()`, `is_running() -> bool`
- All service interfaces except `IRefinementService` extend this

**Result<T, E>:**
- Purpose: Error handling at service boundaries without exceptions
- Location: `src/core/result.hpp`
- Pattern: Static factory methods `Result::ok(val)` / `Result::err(msg)`, checked access via `is_ok()`/`is_err()`, `value()`, `error()`
- Void specialization `Result<void>` for operations with no return value
- Uses bool tag + separate fields (not `std::variant`) to avoid same-type issue when T==E

**RingBuffer<T>:**
- Purpose: Zero-copy audio transfer between producer (PipeWire) and consumer (Vosk) threads
- Location: `src/core/ring_buffer.hpp`
- Pattern: Lock-free SPSC with `std::atomic` positions, `memcpy`-based bulk read/write

**TranscriptionOrchestrator:**
- Purpose: Coordinates the two-stage STT pipeline (Vosk streaming + Whisper batch refinement)
- Location: `src/recognition/transcription_orchestrator.hpp`
- Pattern: Takes raw pointers to `IRecognitionService` and `IRefinementService`, wires callbacks, manages the Vosk→Whisper handoff
- Uses edit-distance ratio to decide whether Whisper output is meaningfully different from Vosk

**ModifierState:**
- Purpose: Uniform representation of modifier key state across hotkey backends
- Location: `src/hotkey/modifier_state.hpp`
- Pattern: Simple struct with bool fields (`ctrl`, `super`, `alt`, `shift`) plus a free function `check_modifiers_match()` that maps config strings to fields

## Entry Points

**Main executable:**
- Location: `src/app/main.cpp`
- Triggers: User launches `verbal-code` binary
- Responsibilities: Creates `Application`, registers signal handlers (SIGINT/SIGTERM), calls `init()` then `run()`

**Application::init():**
- Location: `src/app/application.cpp` (line 59)
- Triggers: Called from `main()`
- Responsibilities: Detects session type, initializes all services in order: config → recognition → audio → hotkey → injection → overlay

**Application::run():**
- Location: `src/app/application.cpp` (line 289)
- Triggers: Called from `main()` after successful init
- Responsibilities: Enters GTK main loop (or infinite sleep in headless mode). All further activity is event-driven via callbacks.

## Error Handling

**Strategy:** `Result<T>` for expected errors at service boundaries; exceptions reserved for programming errors (accessing `.value()` on error Result)

**Patterns:**
- Service `start()` methods return `Result<void>` — caller decides whether failure is fatal
- `Application::init()` chains sub-init calls, propagating first error upward
- Non-critical service failures (overlay, injection) log warnings and continue; critical failures (Vosk, audio) abort init
- Whisper init failure gracefully degrades to Vosk-only mode

## Cross-Cutting Concerns

**Logging:** Singleton `Logger` class with macro wrappers (`LOG_INFO(tag, msg)`). Tag-based (each module uses a `constexpr const char* TAG`). Levels: DEBUG, INFO, WARN, ERROR. Thread-safe via mutex. Location: `src/core/logger.hpp`, `src/core/logger.cpp`.

**Validation:** Config applies defaults for missing fields. Model paths validated at init time via `ModelManager`. No formal input validation framework.

**Authentication:** Not applicable (local desktop application).

**Session Detection:** `detect_session_type()` in `src/core/session.hpp` reads `XDG_SESSION_TYPE` env var. Used once at init to select platform backends.

**Conditional Compilation:** Build system sets `VERBAL_HAS_*` and `VERBAL_ENABLE_*` compile definitions based on available system libraries. `Application::init_*` methods use `#ifdef` guards. Service targets in CMake conditionally link via `if(TARGET verbal_*)`.

---

*Architecture analysis: 2026-03-07*
