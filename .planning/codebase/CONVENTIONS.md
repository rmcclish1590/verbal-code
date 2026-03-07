# Coding Conventions

**Analysis Date:** 2026-03-07

## Naming Patterns

**Files:**
- Headers: `snake_case.hpp` (e.g., `src/core/ring_buffer.hpp`, `src/hotkey/evdev_hotkey_service.hpp`)
- Sources: `snake_case.cpp` (e.g., `src/core/config.cpp`, `src/injection/xdo_injection_service.cpp`)
- Interface headers: `i_snake_case.hpp` with `I` prefix (e.g., `src/core/i_service.hpp`, `src/hotkey/i_hotkey_service.hpp`)
- Test files: `test_snake_case.cpp` (e.g., `tests/core/test_ring_buffer.cpp`)
- Mock files: `mock_snake_case.hpp` (e.g., `tests/mocks/mock_services.hpp`)

**Classes/Structs:**
- PascalCase: `RingBuffer`, `AudioBuffer`, `TranscriptionOrchestrator`, `EvdevHotkeyService`
- Interface classes: `I`-prefixed PascalCase: `IService`, `IAudioService`, `IHotkeyService`, `IInjectionService`, `IRecognitionService`, `IRefinementService`, `IOverlayService`
- Mock classes: `Mock`-prefixed PascalCase in `verbal::testing` namespace: `MockRecognitionService`, `MockRefinementService`

**Functions/Methods:**
- snake_case: `start_capture()`, `stop_streaming()`, `set_on_press()`, `is_running()`, `inject_text()`
- Predicate methods use `is_`/`has_` prefix: `is_running()`, `is_pressed()`, `is_ok()`, `has_focused_input()`
- Callback setters use `set_on_` prefix: `set_on_press()`, `set_on_release()`, `set_on_partial()`, `set_on_refined()`

**Variables:**
- snake_case: `sample_rate`, `ring_buffer`, `device_fds`
- Member variables: trailing underscore: `running_`, `pressed_`, `config_`, `on_press_`, `held_keys_`
- Constants: `UPPER_SNAKE_CASE` in anonymous namespaces: `TAG`, `RING_BUFFER_SAMPLES`, `MODIFIER_WAIT_TIMEOUT_MS`
- Global constants: `constexpr` with UPPER_SNAKE_CASE: `DEFAULT_SAMPLE_RATE`, `DEFAULT_CHANNELS`, `SAMPLES_PER_MS`

**Type Aliases:**
- PascalCase: `AudioSample`, `TextCallback`, `VoidCallback`, `PositionCallback`, `QuitCallback`

**Enums:**
- Enum class with PascalCase name, UPPER_SNAKE_CASE values: `OverlayState::IDLE`, `LogLevel::DEBUG`, `SessionType::WAYLAND`, `TranscriptionSource::VOSK`

**Namespaces:**
- lowercase: `verbal` (primary), `verbal::testing` (mocks), `verbal::injection` (utilities)

## Code Style

**Formatting:**
- No `.clang-format` or `.clang-tidy` configuration file detected
- 4-space indentation observed throughout
- Opening brace on same line for functions, classes, control structures
- Single blank line between function definitions
- Closing namespace comments: `} // namespace verbal`

**Header Guards:**
- Use `#pragma once` exclusively (no `#ifndef` guards)

**Compiler Warnings:**
- `-Wall -Wextra -Wpedantic` enabled in `CMakeLists.txt`
- Debug builds add `-fsanitize=address,undefined`

## Import Organization

**Order (observed in implementation files):**
1. Own header (e.g., `#include "application.hpp"` in `application.cpp`)
2. Other project headers (e.g., `#include "logger.hpp"`, `#include "session.hpp"`)
3. Conditional project headers under `#ifdef` guards (e.g., `#ifdef VERBAL_HAS_XCB_HOTKEY`)
4. System/third-party headers (e.g., `<thread>`, `<vector>`, `<linux/input.h>`)

**Path Style:**
- Project headers use quotes: `#include "logger.hpp"`
- System/third-party headers use angle brackets: `#include <gtest/gtest.h>`, `#include <nlohmann/json.hpp>`
- No path prefixes in includes; CMake `target_include_directories` handles resolution

**Conditional Compilation:**
- Feature macros defined by CMake: `VERBAL_ENABLE_WHISPER`, `VERBAL_HAS_AUDIO`, `VERBAL_HAS_EVDEV_HOTKEY`, `VERBAL_HAS_XCB_HOTKEY`, `VERBAL_HAS_PORTAL_HOTKEY`, `VERBAL_HAS_XDO_INJECTION`, `VERBAL_HAS_WAYLAND_INJECTION`, `VERBAL_HAS_OVERLAY`
- Used with `#ifdef` / `#endif` to conditionally include headers and compile code blocks

## Error Handling

**Result Type:**
- Use `Result<T, E>` (defined in `src/core/result.hpp`) at service boundaries
- Default error type is `std::string`: `Result<void>`, `Result<std::string>`
- Construct with static factory methods: `Result<void>::ok()`, `Result<void>::err("message")`
- Check with `is_ok()` / `is_err()` or `explicit operator bool()`
- Access with `.value()` / `.error()` (throws `std::runtime_error` if wrong state)
- Supports `.map()` for chaining and `.value_or()` for defaults
- Void specialization `Result<void, E>` for operations that succeed or fail without a value

**Error Propagation Pattern:**
```cpp
if (auto r = init_config(); r.is_err()) return r;
if (auto r = init_recognition(); r.is_err()) return r;
```

**Result Construction in Init Methods:**
```cpp
auto vosk_result = vosk->start();
if (vosk_result.is_err()) {
    return Result<void>::err("Vosk init failed: " + vosk_result.error());
}
```

**Non-Critical Failures:**
- Log warnings and continue: `LOG_WARN(TAG, "Injection service failed: " + inj_result.error())`
- Reset optional components: `whisper_.reset()` when whisper init fails
- Return `Result<void>::ok()` even when optional services fail

**Exceptions:**
- Reserved for truly unrecoverable situations (per CLAUDE.md)
- Only thrown internally by `Result::value()` / `Result::error()` on misuse
- `nlohmann::json::exception` caught in config loading

## Logging

**Framework:** Custom singleton `Logger` class in `src/core/logger.hpp`

**Patterns:**
- Use convenience macros: `LOG_DEBUG(tag, msg)`, `LOG_INFO(tag, msg)`, `LOG_WARN(tag, msg)`, `LOG_ERROR(tag, msg)`
- Each file/class defines a `TAG` constant in an anonymous namespace:
```cpp
namespace {
constexpr const char* TAG = "App";
} // namespace
```
- Messages are plain strings; use `std::to_string()` and string concatenation for dynamic values:
```cpp
LOG_INFO(TAG, "Evdev hotkey service started (" + std::to_string(device_fds_.size()) + " keyboards)");
```
- Output goes to `std::cerr` with format: `HH:MM:SS.mmm [LEVEL] [Tag] message`
- Thread-safe via `std::mutex`

**When to Log:**
- `INFO`: Service start/stop, major state changes (recording started/stopped)
- `DEBUG`: Key events, partial results, internal state transitions
- `WARN`: Non-fatal failures (optional service init failure, config save failure)
- `ERROR`: Fatal failures that prevent functionality

## Comments

**When to Comment:**
- Interface method documentation: brief comment above pure virtual methods
- Class-level documentation: 1-2 line comment explaining purpose above class declaration
- Inline comments for non-obvious logic (e.g., memory ordering, wraparound math)
- Section separators in test files: `// -- edit_distance_ratio tests (existing) -----`

**Style:**
- Single-line `//` comments (no `/* */` blocks observed)
- No JSDoc/Doxygen annotations
- Comments explain "why" not "what": `// Peek doesn't consume data`, `// Wake up poll thread`

## Function Design

**Size:** Functions are generally compact (10-40 lines). Larger init methods are decomposed into helper methods (see `Application::init()` calling `init_config()`, `init_recognition()`, etc.).

**Parameters:**
- `const std::string&` for string input
- Raw pointers for non-owning references: `IRecognitionService* recognition`
- `std::vector<std::string>` by const ref for collections
- Callbacks by value with `std::move`: `void set_on_press(VoidCallback cb) { on_press_ = std::move(cb); }`

**Return Values:**
- `Result<T>` for fallible operations at service boundaries
- `bool` for simple success/failure (e.g., `Config::load()`, `Config::save()`)
- `const T&` for accessors returning owned data
- Plain types for simple getters: `int x() const`, `size_t last_injection_length() const`

## Module Design

**Exports:**
- Each module has a public interface header (`i_*.hpp`) defining the abstract base class
- Implementation classes are in separate `.hpp`/`.cpp` pairs
- No barrel files; consumers include specific headers

**Library Structure:**
- Each module compiles as a CMake library target (e.g., `verbal_core`, `verbal_hotkey`, `verbal_recognition`)
- Conditional compilation via `if(TARGET ...)` checks in CMake
- Modules link only to their direct dependencies

## Ownership and Resource Management

**Smart Pointers:**
- `std::unique_ptr` for owned services and resources: `std::unique_ptr<IHotkeyService> hotkey_`
- Raw pointers for non-owning references: `IRecognitionService* recognition_`
- `std::make_unique` for construction

**RAII:**
- Destructors call `stop()` on services: `~EvdevHotkeyService() { stop(); }`
- File descriptors closed in `stop()` methods
- Self-pipe pattern for clean thread shutdown

**Atomics:**
- `std::atomic<bool>` for cross-thread state flags: `running_`, `pressed_`
- Use explicit memory ordering: `std::memory_order_acquire` for loads, `std::memory_order_release` for stores
- `alignas(64)` on atomic members in `RingBuffer` to prevent false sharing

**Threading:**
- `std::mutex` with `std::lock_guard<std::mutex>` for critical sections
- Background threads via `std::thread` with join in destructor/stop
- Detached threads for non-blocking post-processing: `std::thread([this, audio = std::move(audio)]() { ... }).detach()`

## Callback Registration

**Pattern:** Set callbacks before calling `start()`. Use typed aliases for clarity:
```cpp
using TextCallback = std::function<void(const std::string&)>;
using VoidCallback = std::function<void()>;

virtual void set_on_press(VoidCallback cb) = 0;
virtual void set_on_release(VoidCallback cb) = 0;
```

**Implementation:** Store callback, invoke with null check:
```cpp
if (on_press_) on_press_();
```

## Conditional Backend Selection

**Pattern:** Runtime session detection + compile-time feature guards:
```cpp
#ifdef VERBAL_HAS_EVDEV_HOTKEY
if (session == SessionType::WAYLAND) {
    hotkey_ = std::make_unique<EvdevHotkeyService>();
}
#endif
#ifdef VERBAL_HAS_XCB_HOTKEY
if (!hotkey_ && (session == SessionType::X11 || session == SessionType::UNKNOWN)) {
    hotkey_ = std::make_unique<XcbHotkeyService>();
}
#endif
```
- Check `!ptr` before each fallback to form a priority chain
- Log which backend was selected

## Static Methods for Testability

**Pattern:** Make pure logic `static` so tests can exercise it without starting the full service:
- `WaylandInjectionService::build_paste_command(bool)` -- tested in `tests/injection/test_wayland_injection.cpp`
- `WaylandInjectionService::build_backspace_command(size_t)` -- tested similarly
- `PortalHotkeyService::build_shortcut_string(mods, key)` -- tested in `tests/hotkey/test_portal_hotkey_service.cpp`
- `TranscriptionOrchestrator::edit_distance_ratio(a, b)` -- tested in `tests/recognition/test_transcription_orchestrator.cpp`
- `EvdevHotkeyService::process_key_event(code, value)` -- public method for testing without hardware

---

*Convention analysis: 2026-03-07*
