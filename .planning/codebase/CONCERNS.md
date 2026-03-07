# Codebase Concerns

**Analysis Date:** 2026-03-07

## Tech Debt

**Detached thread in on_hotkey_release:**
- Issue: `std::thread(...).detach()` in `on_hotkey_release()` creates a fire-and-forget thread for transcription processing. If the Application object is destroyed while this thread is still running, it accesses dangling `this` pointer (captured by lambda). The destructor calls `quit()` but does not wait for detached threads to finish.
- Files: `src/app/application.cpp` (line 370-372)
- Impact: Potential use-after-free crash on rapid quit after recording stops. Race condition between detached thread calling `on_refined_text()` (which accesses `transcription_store_`, `hotkey_`, `injection_`) and `quit()` destroying those members.
- Fix approach: Replace detached thread with a member `std::thread` or `std::future` that is joined in `quit()`. Add a `std::atomic<bool> shutting_down_` flag checked before accessing members in the detached thread.

**`recording_` flag is not atomic:**
- Issue: `recording_` is a plain `bool` accessed from multiple threads (GTK main loop thread, hotkey callback thread) without synchronization. `on_hotkey_press()` and `on_hotkey_release()` are called from the evdev poll thread while `recording_` could be read from other contexts.
- Files: `src/app/application.hpp` (line 64), `src/app/application.cpp` (lines 321, 343)
- Impact: Data race (undefined behavior per C++ standard). Practically unlikely to cause issues on x86 due to strong memory ordering, but a correctness violation.
- Fix approach: Change `bool recording_` to `std::atomic<bool> recording_{false}`.

**Shell command execution via `std::system()` and `popen()`:**
- Issue: Both injection services shell out to external commands (`xdotool`, `xclip`, `wl-copy`, `ydotool`, `wtype`) using `std::system()` and `popen()`. The `injection::run_cmd()` utility in `injection_utils.hpp` passes strings directly to `std::system()`. While current call sites construct commands from hardcoded strings and validated integers, this pattern is fragile and difficult to audit.
- Files: `src/injection/injection_utils.hpp`, `src/injection/xdo_injection_service.cpp`, `src/injection/wayland_injection_service.cpp`
- Impact: Any future change that interpolates user-controlled data into command strings risks shell injection. Process forking overhead on every injection.
- Fix approach: Replace `std::system()`/`popen()` with direct `fork()`/`exec()` calls that bypass the shell entirely. Create a utility function that takes argv-style arguments.

**TranscriptionStore::entries() returns reference without lock:**
- Issue: `entries()` returns `const std::vector<TranscriptionEntry>&` without acquiring the mutex, while `append()`, `load()`, `save()`, and `clear()` all lock. If the caller iterates the returned reference while another thread calls `append()`, this is a data race.
- Files: `src/app/transcription_store.hpp` (line 28)
- Impact: Data race when `on_refined_text()` calls `append()` on the detached thread while the GTK thread calls `entries()` via `on_history_requested_`. Could crash or produce garbage.
- Fix approach: Either return a copy (already done by `get_samples()` in AudioBuffer) or lock internally and return by value. Given the small data size, returning a copy is safest.

**Hardcoded Whisper thread count:**
- Issue: `WHISPER_THREAD_COUNT` is hardcoded to 4, regardless of available CPU cores.
- Files: `src/recognition/whisper_refinement_service.cpp` (line 15)
- Impact: Suboptimal performance on machines with fewer or more cores. On 2-core machines, over-subscribes CPU during inference.
- Fix approach: Use `std::thread::hardware_concurrency()` with a sensible cap, or make configurable via `Config`.

**Whisper sample rate assumption:**
- Issue: `WhisperRefinementService::refine()` accepts a `sample_rate` parameter but ignores it (`(void)sample_rate`), assuming input is always 16kHz.
- Files: `src/recognition/whisper_refinement_service.cpp` (lines 68-69)
- Impact: If sample rate ever changes, Whisper will produce garbage output with no error. Silent failure.
- Fix approach: Add a runtime check that `sample_rate == 16000` and return an error if it differs, or implement resampling.

## Security Considerations

**Shell injection surface in injection utilities:**
- Risk: `injection::run_cmd()` passes a `std::string` to `std::system()`, which invokes `/bin/sh -c`. The `command_exists()` function concatenates an external name into a shell command. Current callers use hardcoded strings, but the API accepts arbitrary strings.
- Files: `src/injection/injection_utils.hpp` (lines 12-14, 18-21)
- Current mitigation: Call sites use hardcoded command names. `xdo_injection_service.cpp` validates window ID is digits-only before interpolation (line 68-69).
- Recommendations: Replace `std::system()` with `execvp()` in a fork. Mark `run_cmd()` as deprecated or remove the shell layer. The `command_exists()` function should use `access()` + PATH lookup instead of `which` via shell.

**Transcription data stored in plaintext:**
- Risk: Voice transcriptions may contain sensitive information (passwords dictated, personal data). They are stored as plaintext JSON.
- Files: `src/app/transcription_store.cpp`
- Current mitigation: File permissions set to owner-only (0600) after save (line 75-77). Good.
- Recommendations: Consider adding an option to disable transcription history, or encrypt at rest. The 1000-entry default is a large amount of potentially sensitive data.

**evdev requires input group membership:**
- Risk: The evdev hotkey service reads raw keyboard input from `/dev/input/event*`. This requires the user to be in the `input` group, which grants access to ALL input devices (including reading keystrokes from other applications - effectively a keylogger capability).
- Files: `src/hotkey/evdev_hotkey_service.cpp` (lines 131-137)
- Current mitigation: None. This is inherent to the evdev approach on Wayland.
- Recommendations: Document this security implication clearly. Prefer the Portal hotkey service on Wayland when available (currently Portal is last fallback, should be promoted).

## Performance Bottlenecks

**AudioBuffer mutex contention in hot path:**
- Problem: `AudioBuffer::append()` acquires a mutex on every PipeWire callback (~every 10ms for 480-sample chunks). The PipeWire audio callback is a realtime context where blocking is undesirable.
- Files: `src/audio/audio_buffer.hpp` (line 20), `src/audio/pipewire_audio_service.cpp` (line 178)
- Cause: The mutex protects concurrent access between the PipeWire thread (writing) and the main thread (reading via `get_samples()`).
- Improvement path: Use a lock-free approach similar to `RingBuffer`, or use a double-buffer swap pattern. Alternatively, since `get_samples()` is only called after `stop_capture()`, the mutex may be over-conservative - verify that no concurrent reads happen during capture.

**XCB hotkey polling at 60Hz:**
- Problem: `XcbHotkeyService::poll_thread_func()` calls `xcb_query_pointer()` every 16ms to check modifier state. This is wasteful CPU usage (constant polling even when idle).
- Files: `src/hotkey/xcb_hotkey_service.cpp` (lines 99-118)
- Cause: Polling approach instead of event-driven XCB key monitoring via `XInput2` or `XRecord`.
- Improvement path: Use XCB xinput events to get key press/release events directly (the header `xcb/xinput.h` is already included in `xcb_hotkey_service.hpp`). This would eliminate polling entirely.

**Full audio copy on recording stop:**
- Problem: `audio_->recorded_audio()` returns a `const std::vector<AudioSample>&` to `recorded_`, which was populated by copying the entire `AudioBuffer` contents in `stop_capture()`. For a 30-second recording at 16kHz, this is ~960KB of data copied, then moved into the detached thread lambda.
- Files: `src/audio/pipewire_audio_service.cpp` (line 145), `src/app/application.cpp` (lines 365-372)
- Cause: The audio data needs to reach the Whisper refinement thread.
- Improvement path: Use `std::move` semantics more aggressively. `recorded_audio()` could return by move, and the detached thread already moves it. The initial copy in `stop_capture()` from `audio_buffer_.get_samples()` is the real bottleneck.

## Fragile Areas

**Application initialization order:**
- Files: `src/app/application.cpp` (lines 59-68)
- Why fragile: Services are initialized in a strict sequence (`init_config` -> `init_recognition` -> `init_audio` -> `init_hotkey` -> `init_injection` -> `init_overlay`). Several services depend on `config_` being loaded and `ring_buffer_` being created. Re-ordering causes null pointer dereferences. The dependencies are implicit (no compile-time enforcement).
- Safe modification: Keep the initialization order. When adding new services, add them at the end. Document dependencies in comments.
- Test coverage: No integration test covers the full init sequence. Each service is tested in isolation.

**Conditional compilation maze:**
- Files: `src/app/application.cpp` (lines 8-38, and scattered `#ifdef` blocks throughout)
- Why fragile: 8 different `#ifdef` guards (`VERBAL_HAS_AUDIO`, `VERBAL_HAS_EVDEV_HOTKEY`, `VERBAL_HAS_XCB_HOTKEY`, `VERBAL_HAS_PORTAL_HOTKEY`, `VERBAL_HAS_XDO_INJECTION`, `VERBAL_HAS_WAYLAND_INJECTION`, `VERBAL_HAS_OVERLAY`, `VERBAL_ENABLE_WHISPER`) create a combinatorial explosion of build configurations. Testing all combinations is impractical.
- Safe modification: When adding new conditional features, follow the existing pattern: check the flag, create the service, fall through to the next option. Always handle the case where no backend is available.
- Test coverage: Tests compile without most optional dependencies and test only the interfaces/logic, not the conditional wiring.

**Hotkey callback thread safety:**
- Files: `src/app/application.cpp` (lines 320-373)
- Why fragile: `on_hotkey_press()` and `on_hotkey_release()` are called from the evdev/xcb poll thread. They access `recording_` (non-atomic), `audio_` (unique_ptr), `orchestrator_` (unique_ptr), and `overlay_` (unique_ptr via `g_idle_add`). If `quit()` is called concurrently (e.g., from signal handler or GTK quit), these pointers may be invalidated mid-use.
- Safe modification: Always check pointer validity before use (already partially done). Make `recording_` atomic. Add a shutdown guard.
- Test coverage: No concurrency tests exist for the Application class.

## Scaling Limits

**Ring buffer fixed at 10 seconds:**
- Current capacity: `16000 * 10 = 160,000` samples (10 seconds at 16kHz)
- Limit: If the ring buffer fills before Vosk consumes data, audio samples are silently dropped (the `write()` method returns less than requested).
- Scaling path: Make the ring buffer size configurable, or implement an overwrite policy for the oldest data. Currently the 10-second buffer is adequate for the streaming use case since Vosk processes in near-real-time.
- Files: `src/app/application.cpp` (line 47)

**Transcription store in-memory with JSON file:**
- Current capacity: Up to 1000 entries loaded entirely into memory and written as a single JSON file.
- Limit: At 1000 entries with average 100-char transcriptions, the JSON file is ~200KB. Acceptable, but `save()` rewrites the entire file on every transcription.
- Scaling path: Consider appending to a log file instead of rewriting JSON, or use SQLite. Current approach causes brief I/O stalls on save.
- Files: `src/app/transcription_store.cpp`

## Dependencies at Risk

**Vosk pre-built binary dependency:**
- Risk: Vosk is downloaded as a pre-built shared library from GitHub releases. No source build. If the release is removed or the API changes, the build breaks with no fallback.
- Impact: Build failure, no speech recognition.
- Migration plan: Consider building Vosk from source via FetchContent, or pin to a specific known-good release with a local cache.

**GTK3 deprecation:**
- Risk: GTK3 is in maintenance mode. GTK4 is the current version. New Linux distributions may eventually drop GTK3 packages.
- Impact: Overlay service would need a rewrite for GTK4 (significantly different API for window management, drawing).
- Migration plan: The overlay is isolated behind `IOverlayService` interface, so a GTK4 or Qt implementation can be swapped in.

## Test Coverage Gaps

**No tests for Application class:**
- What's not tested: The entire `Application` class (init sequence, hotkey callbacks, recording lifecycle, quit/shutdown). This is the main orchestration point.
- Files: `src/app/application.cpp`, `src/app/application.hpp`
- Risk: Regressions in service wiring, callback plumbing, or initialization order go undetected.
- Priority: High

**Injection services only test static helpers:**
- What's not tested: `inject_text()`, `inject_via_clipboard_paste()`, `inject_via_wtype()`, `replace_last_injection()` - all the actual injection logic requires running X11/Wayland and external tools.
- Files: `tests/injection/test_wayland_injection.cpp`, `tests/injection/test_xdo_injection.cpp`
- Risk: Injection regressions (the most user-visible feature) are only caught manually.
- Priority: Medium - difficult to unit test due to system dependencies, but integration tests with mocked subprocess execution would help.

**No tests for PipeWireAudioService:**
- What's not tested: Audio capture, ring buffer feeding, PipeWire stream lifecycle. The `test_audio_buffer.cpp` only tests the `AudioBuffer` accumulator, not the service.
- Files: `src/audio/pipewire_audio_service.cpp`
- Risk: Audio pipeline regressions undetected. Low practical risk since PipeWire APIs are stable.
- Priority: Medium

**No tests for VoskRecognitionService or WhisperRefinementService:**
- What's not tested: Actual recognition/refinement with real models. Only the `TranscriptionOrchestrator` is tested with mocks.
- Files: `src/recognition/vosk_recognition_service.cpp`, `src/recognition/whisper_refinement_service.cpp`
- Risk: Model loading, JSON parsing of Vosk results, audio format conversion for Whisper - all untested.
- Priority: Medium

**Portal hotkey service untested D-Bus flow:**
- What's not tested: `tests/hotkey/test_portal_hotkey_service.cpp` exists but only tests `build_shortcut_string()`. The actual D-Bus session creation, signal subscription, and callback flow are untested.
- Files: `src/hotkey/portal_hotkey_service.cpp`
- Risk: D-Bus API changes or portal behavior differences across compositors go undetected.
- Priority: Low - Portal is currently a fallback, and D-Bus testing requires a running session bus.

**Overlay service tests are trivial:**
- What's not tested: Drawing, context menu, hotkey dialog, history dialog, drag behavior. Tests only verify that setters don't crash.
- Files: `tests/overlay/test_gtk_overlay.cpp`
- Risk: UI regressions undetected. Low priority since overlay is a simple status indicator.
- Priority: Low

---

*Concerns audit: 2026-03-07*
