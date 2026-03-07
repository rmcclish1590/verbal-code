# Codebase Structure

**Analysis Date:** 2026-03-07

## Directory Layout

```
verbal-code/
├── assets/                # Application icons and visual assets
├── cmake/                 # CMake helper modules
│   └── Dependencies.cmake # FetchContent + pkg-config dependency setup
├── config/                # Default configuration files
│   └── default_config.json
├── scripts/               # Build/install helper scripts
├── src/                   # All production source code
│   ├── CMakeLists.txt     # Adds all module subdirectories
│   ├── app/               # Application orchestrator + entry point
│   ├── audio/             # Audio capture module
│   ├── core/              # Shared types, utilities, error handling
│   ├── hotkey/            # Global hotkey detection module
│   ├── injection/         # Text injection module
│   ├── overlay/           # GTK overlay UI module
│   └── recognition/       # Speech recognition module
├── tests/                 # All test code (mirrors src/ layout)
│   ├── CMakeLists.txt     # Top-level test config
│   ├── app/               # Application/store tests
│   ├── audio/             # Audio buffer tests
│   ├── core/              # Config, result, ring buffer, session tests
│   ├── hotkey/            # Hotkey service tests
│   ├── injection/         # Injection service tests
│   ├── mocks/             # Shared mock implementations
│   ├── overlay/           # Overlay tests
│   └── recognition/       # Orchestrator tests
├── build/                 # Out-of-source build directory (gitignored)
├── CMakeLists.txt         # Root CMake config
├── CLAUDE.md              # Development conventions
└── README.md              # Project documentation
```

## Directory Purposes

**`src/core/`:**
- Purpose: Foundation layer used by all modules
- Contains: Interfaces, types, utilities
- Key files:
  - `i_service.hpp`: Base service interface (start/stop/is_running)
  - `result.hpp`: `Result<T, E>` error type
  - `ring_buffer.hpp`: Lock-free SPSC ring buffer
  - `config.hpp` / `config.cpp`: JSON-backed configuration
  - `logger.hpp` / `logger.cpp`: Singleton logger with macros
  - `types.hpp`: Shared type aliases (`AudioSample`, `TextCallback`, `VoidCallback`, enums)
  - `session.hpp`: `SessionType` enum and `detect_session_type()` function

**`src/app/`:**
- Purpose: Application entry point and service composition
- Contains: Main orchestrator, transcription history store
- Key files:
  - `main.cpp`: Entry point, signal handling
  - `application.hpp` / `application.cpp`: Service wiring and lifecycle
  - `transcription_store.hpp` / `transcription_store.cpp`: JSON-backed transcription history

**`src/audio/`:**
- Purpose: Microphone audio capture
- Contains: PipeWire-based audio service
- Key files:
  - `i_audio_service.hpp`: Audio service interface
  - `pipewire_audio_service.hpp` / `.cpp`: PipeWire implementation
  - `audio_buffer.hpp`: Audio buffer helper

**`src/recognition/`:**
- Purpose: Speech-to-text engines and orchestration
- Contains: Vosk streaming recognizer, Whisper batch refiner, orchestrator, model manager
- Key files:
  - `i_recognition_service.hpp`: Streaming recognition interface
  - `i_refinement_service.hpp`: Batch refinement interface
  - `vosk_recognition_service.hpp` / `.cpp`: Vosk implementation
  - `whisper_refinement_service.hpp` / `.cpp`: Whisper implementation
  - `transcription_orchestrator.hpp` / `.cpp`: Two-stage STT coordinator
  - `model_manager.hpp` / `.cpp`: Model file path resolution

**`src/hotkey/`:**
- Purpose: Global keyboard shortcut detection
- Contains: Three platform backends
- Key files:
  - `i_hotkey_service.hpp`: Hotkey service interface
  - `modifier_state.hpp`: Modifier key state struct and matching logic
  - `evdev_hotkey_service.hpp` / `.cpp`: Linux evdev backend (Wayland primary)
  - `xcb_hotkey_service.hpp` / `.cpp`: XCB/XInput2 backend (X11 primary)
  - `portal_hotkey_service.hpp` / `.cpp`: D-Bus GlobalShortcuts portal backend

**`src/injection/`:**
- Purpose: Typing text into focused applications
- Contains: Two platform backends
- Key files:
  - `i_injection_service.hpp`: Injection service interface
  - `injection_utils.hpp`: Shell command helpers (`run_cmd`, `command_exists`)
  - `xdo_injection_service.hpp` / `.cpp`: X11 backend (libxdo + clipboard fallbacks)
  - `wayland_injection_service.hpp` / `.cpp`: Wayland backend (wtype + wl-clipboard fallbacks)

**`src/overlay/`:**
- Purpose: Visual status indicator and settings UI
- Contains: GTK3 overlay window
- Key files:
  - `i_overlay_service.hpp`: Overlay service interface
  - `gtk_overlay_service.hpp` / `.cpp`: GTK3 implementation (draggable dot, context menu, dialogs)

**`tests/mocks/`:**
- Purpose: Shared mock implementations for testing
- Contains: `mock_services.hpp` with `MockRecognitionService` and `MockRefinementService`

## Key File Locations

**Entry Points:**
- `src/app/main.cpp`: Application entry point
- `CMakeLists.txt`: Root build configuration
- `cmake/Dependencies.cmake`: All external dependency declarations

**Configuration:**
- `config/default_config.json`: Default config values (hotkey, audio, recognition, overlay, storage)
- `src/core/config.hpp`: Config class (runtime path: `~/.config/verbal-code/config.json`)

**Core Logic:**
- `src/app/application.cpp`: Service composition and event wiring
- `src/recognition/transcription_orchestrator.cpp`: STT pipeline coordination
- `src/core/ring_buffer.hpp`: Lock-free audio pipeline

**Service Interfaces (the contract each module implements):**
- `src/core/i_service.hpp`
- `src/audio/i_audio_service.hpp`
- `src/recognition/i_recognition_service.hpp`
- `src/recognition/i_refinement_service.hpp`
- `src/hotkey/i_hotkey_service.hpp`
- `src/injection/i_injection_service.hpp`
- `src/overlay/i_overlay_service.hpp`

**Testing:**
- `tests/mocks/mock_services.hpp`: Shared mocks
- Test files follow pattern: `tests/<module>/test_<component>.cpp`

## Naming Conventions

**Files:**
- `snake_case.hpp` / `snake_case.cpp` for all source files
- Interface headers: `i_<service_name>.hpp` (e.g., `i_audio_service.hpp`)
- Implementation headers: `<platform>_<service_name>.hpp` (e.g., `pipewire_audio_service.hpp`)
- Test files: `test_<component>.cpp` (e.g., `test_ring_buffer.cpp`)
- CMake modules: `PascalCase.cmake` (e.g., `Dependencies.cmake`)

**Directories:**
- `snake_case` for all source directories
- Test directory structure mirrors `src/` exactly

**CMake Targets:**
- Library targets: `verbal_<module>` (e.g., `verbal_core`, `verbal_recognition`)
- Platform-specific targets: `verbal_<variant>` (e.g., `verbal_evdev_hotkey`, `verbal_wayland_injection`)
- Executable: `verbal-code`

## Where to Add New Code

**New Service Module:**
1. Create directory: `src/<module>/`
2. Create interface: `src/<module>/i_<module>_service.hpp` extending `IService`
3. Create implementation: `src/<module>/<platform>_<module>_service.hpp` / `.cpp`
4. Create `src/<module>/CMakeLists.txt` — define `verbal_<module>` target, link `verbal_core`
5. Add `add_subdirectory(<module>)` to `src/CMakeLists.txt`
6. Wire into `Application` in `src/app/application.hpp` / `.cpp` (add `std::unique_ptr<IModuleService>` member, add `init_<module>()` method)
7. Add compile definition in `src/app/CMakeLists.txt`: `VERBAL_HAS_<MODULE>=1`

**New Platform Backend for Existing Service:**
1. Create `src/<module>/<platform>_<module>_service.hpp` / `.cpp` implementing the existing interface
2. Add CMake target in `src/<module>/CMakeLists.txt` (conditionally, based on system deps)
3. Add `#ifdef VERBAL_HAS_<BACKEND>` block in `Application::init_<module>()` in `src/app/application.cpp`
4. Add compile definition and link in `src/app/CMakeLists.txt`

**New Test:**
1. Create `tests/<module>/test_<component>.cpp`
2. Add test target in `tests/<module>/CMakeLists.txt`
3. Use GoogleTest (`TEST()` or `TEST_F()` macros)
4. Use mocks from `tests/mocks/mock_services.hpp` or create new ones there

**New Core Utility:**
- Add header/source to `src/core/`
- Add source to `src/core/CMakeLists.txt` target `verbal_core`
- All modules automatically have access (they link `verbal_core`)

**New Configuration Option:**
1. Add default value to `config/default_config.json`
2. Add typed accessor (and setter if mutable) to `src/core/config.hpp` / `config.cpp`
3. Wire into the appropriate `Application::init_*()` method

## Special Directories

**`build/`:**
- Purpose: Out-of-source CMake build output
- Generated: Yes
- Committed: No (gitignored)
- Contains `_deps/vosk/` (downloaded pre-built Vosk library), FetchContent deps, compiled objects

**`cmake/`:**
- Purpose: CMake helper modules
- Generated: No
- Committed: Yes
- Key file: `Dependencies.cmake` — all FetchContent and pkg-config dependency declarations

**`config/`:**
- Purpose: Default configuration shipped with the application
- Generated: No
- Committed: Yes
- Copied to `~/.config/verbal-code/config.json` on first run

**`assets/`:**
- Purpose: Application icons and desktop integration files
- Generated: No
- Committed: Yes

**`scripts/`:**
- Purpose: Build and install automation scripts
- Generated: No
- Committed: Yes

**`.claude/`:**
- Purpose: Claude Code agent configuration and memory
- Generated: Partially
- Committed: Yes

---

*Structure analysis: 2026-03-07*
