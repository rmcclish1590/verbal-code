# Pitfalls Research

**Domain:** Multi-engine voice-to-text desktop application (Linux, C++17/20)
**Researched:** 2026-03-07
**Confidence:** HIGH (based on codebase analysis, API documentation, and community experience)

## Critical Pitfalls

### Pitfall 1: IRecognitionService Interface Too Narrow for Cloud Engines

**What goes wrong:**
The current `IRecognitionService` interface assumes synchronous, local processing: `feed_audio()` pushes samples into a ring buffer, `final_result()` returns immediately. Cloud APIs (Google Cloud Speech, OpenAI Whisper API) are fundamentally asynchronous -- they require network round-trips, have per-request latency of 200ms-2s, and use different data flow patterns (HTTP POST with encoded audio vs. gRPC bidirectional streaming vs. WebSocket). Forcing cloud engines into the existing synchronous `feed_audio()` / `final_result()` contract creates brittle adapters that either block the calling thread or silently drop errors.

**Why it happens:**
The interface was designed around Vosk's synchronous C API where `feed_audio` processes samples in-place. Developers assume "just implement the interface" without recognizing that the contract implicitly requires sub-millisecond `feed_audio()` and deterministic `final_result()`.

**How to avoid:**
Extend the recognition interface with an async result model before adding any cloud engine. Specifically:
- Add an async completion callback or `std::future`-based `final_result_async()` alongside the synchronous one.
- Add error reporting to `feed_audio()` (currently returns void -- network failures are invisible).
- Add a `capabilities()` method so the orchestrator knows whether an engine supports streaming partials, batch-only, or both.
- Keep the existing synchronous path working for Vosk/Whisper.cpp -- do not break what works.

**Warning signs:**
- Cloud engine adapter has `std::this_thread::sleep_for` or busy-wait loops.
- `feed_audio()` implementations that buffer everything and only process on `final_result()`.
- Tests that mock network latency with sleep instead of testing actual async behavior.

**Phase to address:**
Multi-engine abstraction phase (should be the first phase -- interface refactoring before adding any new engine).

---

### Pitfall 2: Model Memory Explosion on Engine Switching

**What goes wrong:**
Whisper.cpp models consume 75MB-1.5GB of RAM depending on model size. Vosk models consume 50MB-1GB. Loading both simultaneously for "instant switching" doubles memory usage. Naive implementations load all configured engines at startup, causing 2-3GB resident memory for a desktop utility that should feel lightweight.

**Why it happens:**
Developers test with the small/tiny models (75MB) where dual-loading is fine, then users configure large-v3 (1.5GB) plus a large Vosk model and the app consumes 3GB+ at idle.

**How to avoid:**
Implement lazy loading with explicit lifecycle management:
- Only one local engine loaded at a time. Engine switch = unload current, load new.
- `ModelManager` needs `unload()` alongside its path resolution. Currently it only resolves paths -- it does not manage loaded model lifecycle.
- Add a loading state (UNLOADED / LOADING / READY / ERROR) to each engine so the UI can show progress.
- Cloud engines have near-zero memory overhead -- treat them differently from local engines.
- Set a memory budget in config and warn if selected model exceeds it.

**Warning signs:**
- `htop` shows verbal-code using 1GB+ at idle.
- Engine constructor calls `init()` or loads model in the constructor rather than deferring.
- No `shutdown()` or model unload path in recognition services.

**Phase to address:**
Multi-engine abstraction phase. Must be solved before adding engine switching UI.

---

### Pitfall 3: Cloud API Credentials Stored in Plain JSON Config

**What goes wrong:**
The current `Config` class stores everything in `~/.config/verbal-code/config.json` as plain JSON. Adding cloud API keys (Google Cloud service account JSON, OpenAI API key) to this same file means credentials are stored in plaintext, readable by any process running as the user, and trivially exfiltrated. Users will paste API keys into a settings UI expecting them to be handled securely.

**Why it happens:**
The existing config system works fine for non-sensitive settings (hotkey, overlay position). Developers extend it to store API keys because "it's just one more field" without considering that config files are often backed up, synced, or shared.

**How to avoid:**
Use the platform's secret storage:
- **Primary:** `libsecret` (GNOME Keyring / KDE Wallet integration) -- already available on most Linux desktops with GTK3. Store API keys in the user's keyring, not in config.json.
- **Fallback:** XDG-compliant file with restrictive permissions (`chmod 600`) in a separate `~/.config/verbal-code/credentials` file, distinct from the main config.
- Never write API keys to logs or debug output.
- Config.json stores a reference ("api_key_source": "keyring") not the key itself.

**Warning signs:**
- `config.json` contains fields like `"openai_api_key"` or `"google_credentials_path"`.
- API keys visible in debug log output.
- No dependency on `libsecret` or equivalent in CMakeLists.

**Phase to address:**
Cloud API integration phase. Must be solved before any cloud engine ships.

---

### Pitfall 4: gRPC/HTTP Streaming Fails Silently Under Network Instability

**What goes wrong:**
Google Cloud Speech-to-Text streaming has hard limits: 5-minute streaming duration, 10MB per request, and audio must arrive near real-time or the server returns an "Audio Timeout Error." On flaky networks, the gRPC stream silently dies, partials stop arriving, and the user is left speaking into a dead mic with no feedback. The app appears frozen rather than gracefully degrading.

**Why it happens:**
Developers test on localhost or stable connections. The gRPC C++ `ClientReaderWriter` cannot be reused after failure (throws "assertion failed: call_ == nullptr"), so naive retry logic creates new connections without proper cleanup. Keepalive pings are not configured by default.

**How to avoid:**
- Implement a connection health monitor that detects stalled streams (no response for N seconds) and triggers reconnection.
- Configure gRPC keepalive: `GRPC_ARG_KEEPALIVE_TIME_MS` (20s), `GRPC_ARG_KEEPALIVE_TIMEOUT_MS` (10s).
- Build automatic fallback: if cloud engine fails mid-utterance, switch to local Vosk for the remainder of that dictation session (degrade gracefully, do not lose user's speech).
- Surface connection state in the overlay widget (green = connected, yellow = reconnecting, red = offline/using local fallback).
- Buffer audio locally during reconnection so nothing is lost.

**Warning signs:**
- No timeout or deadline set on gRPC RPCs.
- No retry logic in the cloud recognition service.
- Overlay shows "recording" but no partials arrive for 10+ seconds.
- Tests only run against a mock server with zero latency.

**Phase to address:**
Cloud API integration phase. Requires integration testing with simulated network failures.

---

### Pitfall 5: TranscriptionOrchestrator Becomes a God Object

**What goes wrong:**
The current `TranscriptionOrchestrator` manages the Vosk+Whisper hybrid flow with hardcoded two-engine logic (Vosk for streaming, Whisper for refinement). Adding more engines (cloud APIs, different local models) leads developers to keep adding `if/else` branches: "if engine is Google, do X; if OpenAI, do Y; if Vosk+Whisper, do Z." The orchestrator grows to 500+ lines, becomes untestable, and every new engine requires modifying this central class.

**Why it happens:**
The orchestrator already works for the two-engine case. It feels natural to add "just one more condition." The coupling between engine selection, audio routing, and result merging is not separated.

**How to avoid:**
Refactor the orchestrator to use a strategy pattern:
- Define a `ITranscriptionStrategy` interface with methods like `on_start()`, `on_audio()`, `on_stop()` that encapsulate the full flow for a given engine configuration.
- Concrete strategies: `LocalVoskStrategy`, `HybridVoskWhisperStrategy`, `CloudGoogleStrategy`, `CloudOpenAIStrategy`.
- The orchestrator delegates to the active strategy -- it routes events but does not contain engine-specific logic.
- Engine switching = swap the strategy, not modify the orchestrator.

**Warning signs:**
- `TranscriptionOrchestrator` has `#include` for engine-specific headers (vosk, whisper, google cloud).
- Switch/case or if/else chains on engine type inside the orchestrator.
- Adding a new engine requires modifying orchestrator.cpp.

**Phase to address:**
Multi-engine abstraction phase. Refactor before adding third engine.

---

### Pitfall 6: Custom Vocabulary Implementation Diverges Per Engine

**What goes wrong:**
Each recognition engine handles custom vocabulary differently:
- **Vosk:** Supports grammar-based vocabulary restriction and custom language model replacement. You pass a JSON grammar list to the recognizer constructor.
- **Whisper.cpp:** Has no native custom vocabulary. Requires prompt-based biasing (initial_prompt parameter) which is fragile and unreliable.
- **Google Cloud STT:** Uses `SpeechAdaptation` with phrase hints and boost values.
- **OpenAI API:** Uses a `prompt` field for biasing, similar to Whisper.

Developers implement custom vocabulary separately for each engine with different UIs, different storage formats, and different behavior. Users add a custom word expecting it to work everywhere, but it only works with one engine.

**Why it happens:**
The underlying mechanisms genuinely differ. There is no abstraction that unifies "custom vocabulary" across engines, so each gets its own ad-hoc implementation.

**How to avoid:**
Define a unified vocabulary model at the application level:
- Store custom vocabulary as a flat list of `{word, pronunciation_hint, boost_weight}` in config.
- Each engine adapter translates this into its native format: Vosk grammar JSON, Whisper initial_prompt string, Google phrase hints, etc.
- Accept that fidelity varies -- Vosk grammar restriction is strict, Whisper prompting is best-effort. Document this clearly in the settings UI ("Custom words work best with Vosk and Google Cloud").
- The vocabulary editor UI is engine-agnostic; it writes to the unified model.

**Warning signs:**
- Multiple vocabulary storage locations or formats.
- Settings UI has engine-specific vocabulary sections.
- Users report "custom word works in Vosk but not Whisper."

**Phase to address:**
Custom vocabulary phase. Design the unified model before implementing any engine-specific adaptation.

---

### Pitfall 7: GTK Settings UI Blocks the Main Thread During Engine Operations

**What goes wrong:**
GTK3 is single-threaded -- all UI updates must happen on the GTK main loop thread. Engine operations (model loading, cloud API validation, audio device enumeration) take seconds. Running these on the GTK thread freezes the settings window. Running them on a background thread and then calling GTK functions from that thread causes crashes or undefined behavior.

**Why it happens:**
Developers test with fast operations (loading tiny models, localhost APIs) and do not notice the freeze. Or they spawn threads but call `gtk_label_set_text()` directly from the worker thread instead of using `g_idle_add()`.

**How to avoid:**
- All long operations (model loading, API key validation, audio device scan) run on `std::thread` or `g_task_run_in_thread()`.
- Results are marshalled back to GTK thread via `g_idle_add()` or `g_main_context_invoke()`.
- Settings UI shows spinner/progress for any operation that might take >200ms.
- Use GSettings `delay-apply` mode for the preferences dialog -- buffer changes locally, apply all at once when user clicks Save.
- Test with deliberately slow operations (large models, simulated 2s API latency).

**Warning signs:**
- Settings window freezes when changing engine selection.
- GTK critical warnings in stderr about thread safety.
- `gtk_*` calls outside the main loop in engine-related code.

**Phase to address:**
Settings UI phase. Establish the async-operation-to-GTK-thread pattern at the start.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Hardcoding audio format to 16kHz mono int16 | Simplifies audio pipeline, matches Vosk/Whisper expectations | Cloud APIs accept various formats (FLAC, OGG); re-encoding needed for each. Some engines prefer float32. | Acceptable now; add format conversion when cloud engines need it. |
| Storing all config in single JSON file | Simple to implement and debug | Credentials mixed with preferences; concurrent read/write from settings UI and running engine causes race conditions | Never acceptable for credentials. Split config vs. credentials immediately. |
| Synchronous model loading in service constructors | Simple initialization flow | Blocks app startup; prevents lazy loading; makes engine switching slow | Only acceptable in early prototyping. Move to async init before settings UI. |
| Single `IRecognitionService` interface for all engines | Clean abstraction | Forces async cloud engines into sync API; loses cloud-specific features (word-level timestamps, confidence scores, speaker diarization) | Acceptable as base interface. Add `ICloudRecognitionService` extending it for cloud-specific capabilities. |
| No audio format negotiation | Every engine gets raw int16 PCM | Cloud APIs need encoded audio (FLAC/OGG) to reduce bandwidth; sending raw PCM over the network wastes 4-8x bandwidth | Never acceptable for cloud engines. Add encoding before cloud API phase. |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Google Cloud Speech gRPC | Reusing `ClientReaderWriter` after stream failure (causes assertion crash) | Create fresh channel/context/stream for each reconnection attempt |
| Google Cloud Speech gRPC | Not setting deadlines on RPCs | Always set deadline; for streaming, implement per-message timeout logic since stream-level deadlines are impractical |
| OpenAI Whisper API | Sending raw PCM audio (API expects encoded files) | Encode audio as FLAC or WAV before upload; use libsndfile or raw WAV header construction |
| OpenAI Whisper API | Expecting streaming partials (API is batch-only for transcription endpoint) | Use batch POST for Whisper API; for streaming, use the Realtime API (WebSocket/WebRTC -- much more complex) |
| Vosk custom grammar | Passing grammar after recognizer construction | Grammar must be set at `VoskRecognizer` construction time; changing grammar requires destroying and recreating the recognizer |
| Whisper.cpp initial_prompt | Using initial_prompt for vocabulary (unreliable; model may ignore it) | Treat as best-effort biasing, not guaranteed vocabulary support; document limitation to users |
| libsecret (credential storage) | Assuming GNOME Keyring is always available | Check at runtime; fall back to encrypted file if no keyring daemon is running (common in minimal WMs) |
| GSettings schema | Not installing schema during build/install | Schema must be compiled with `glib-compile-schemas` and installed to the correct path, or use `g_settings_schema_source_new_from_directory()` for local schemas during development |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Loading multiple large models simultaneously | 2-3GB RAM for a "lightweight" desktop tool | Lazy load one local engine at a time; unload before switching | Immediately with large-v3 Whisper + large Vosk |
| Sending raw PCM to cloud APIs | High bandwidth usage, slow upload, API rejecting large payloads | Encode to FLAC (5-8x compression) before upload | Utterances longer than 10 seconds on slow connections |
| Blocking GTK main loop during cloud API calls | UI freeze, "not responding" in window manager | All network I/O on background threads with `g_idle_add()` for UI updates | First cloud API call on a slow connection |
| Whisper.cpp refinement on every utterance | 1-3 second delay after each dictation, even for short phrases | Only refine when Vosk confidence is below threshold; skip refinement for short utterances (<5 words) | Noticeable on first use; intolerable by day 2 |
| Recreating gRPC channel per request | 200-500ms connection establishment overhead per utterance | Maintain persistent channel; recreate only on failure | Every cloud API call |
| No audio ring buffer drain on engine switch | Old audio from previous engine leaks into new engine | Flush ring buffer on engine switch; discard buffered audio from before the switch point | First engine switch during active recording |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| API keys in config.json (plaintext) | Credential theft via backup sync, shared dotfiles, or malware reading config | Use `libsecret` for keyring storage; never write keys to JSON config |
| API keys in log output | Keys leaked to log files, crash reports, or terminal scrollback | Sanitize all log messages; never log request headers or auth tokens |
| No API key validation before use | Confusing errors when key is invalid, expired, or wrong project | Validate key on entry in settings UI with a test API call; surface clear error |
| Sending audio to cloud without user consent indicator | User may not realize audio is leaving their machine | Overlay must clearly indicate "cloud" mode (different icon/color); first-time cloud enable requires explicit confirmation dialog |
| No rate limiting on cloud API calls | Runaway costs from stuck recording or bug causing rapid-fire API calls | Implement per-minute request cap; alert user if approaching billing threshold |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Engine switch requires app restart | Disrupts workflow; users avoid switching engines | Hot-swap engines without restart; show brief "loading" state in overlay |
| No feedback during model loading | User thinks app is broken during 5-30 second model load | Show loading progress in overlay and settings UI; allow cancellation |
| Cloud/local engine differences invisible to user | User expects identical behavior, gets different latency/accuracy | Label engines clearly in UI: "Vosk (local, fast)" vs "Google Cloud (online, accurate)"; show latency indicator |
| Custom vocabulary silently ignored by some engines | User adds words, they do not work, no explanation | Per-engine vocabulary support indicator in settings: checkmark for supported, warning for best-effort |
| Settings changes apply to next recording, not current | User changes engine mid-recording, expects immediate effect | Either apply immediately (complex) or clearly indicate "changes apply to next recording session" |
| No undo/rollback for settings changes | User changes engine config, breaks their setup, cannot get back | Save previous config as backup before applying changes; offer "Restore Defaults" button |

## "Looks Done But Isn't" Checklist

- [ ] **Multi-engine support:** Often missing engine unload/cleanup -- verify that switching from Whisper to Vosk frees Whisper model memory completely
- [ ] **Cloud API integration:** Often missing offline fallback -- verify that app still works (with local engine) when network is unavailable
- [ ] **Custom vocabulary:** Often missing persistence across engine switches -- verify vocabulary survives engine change and app restart
- [ ] **Settings UI:** Often missing validation -- verify that invalid model paths, malformed API keys, and unreachable endpoints show clear errors instead of silent failure
- [ ] **Settings UI:** Often missing concurrent access safety -- verify that changing settings while a recording is active does not crash or corrupt state
- [ ] **Cloud streaming:** Often missing reconnection -- verify that a dropped network connection during dictation recovers automatically
- [ ] **Audio encoding for cloud:** Often missing sample rate conversion -- verify that if PipeWire delivers 48kHz audio, it is correctly resampled to 16kHz before cloud upload (or the cloud API sample rate is set correctly)
- [ ] **Engine switching:** Often missing ring buffer flush -- verify that switching engines does not feed stale audio from previous engine into the new one

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| God-object orchestrator | MEDIUM | Extract strategy pattern; can be done incrementally by wrapping existing logic in a strategy class first |
| Credentials in plaintext config | LOW | Add libsecret integration; migrate existing keys with one-time migration on startup; delete keys from config.json |
| Interface too narrow for cloud | HIGH | Requires touching all consumers of IRecognitionService; plan for breaking change with deprecation period for old API |
| Model memory explosion | LOW | Add unload() to ModelManager and recognition services; mostly additive change |
| GTK thread safety violations | MEDIUM | Audit all GTK calls; wrap in g_idle_add(); may require restructuring callback chains |
| Silent cloud failures | MEDIUM | Add health monitoring and fallback logic; requires testing infrastructure for network failure simulation |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Interface too narrow for cloud | Multi-engine abstraction (Phase 1) | Cloud engine adapter compiles and passes tests without sleep/busy-wait hacks |
| God-object orchestrator | Multi-engine abstraction (Phase 1) | New engine can be added by creating a strategy class without modifying orchestrator |
| Model memory explosion | Multi-engine abstraction (Phase 1) | `htop` shows <200MB when only one engine is active |
| Credentials in plaintext | Cloud API integration (Phase 2) | `grep -r "api_key" ~/.config/verbal-code/` returns nothing |
| gRPC/HTTP silent failures | Cloud API integration (Phase 2) | Simulated network drop during dictation triggers fallback and user notification |
| Audio encoding for cloud | Cloud API integration (Phase 2) | Cloud API receives FLAC-encoded audio; bandwidth is <25% of raw PCM |
| Custom vocabulary divergence | Custom vocabulary (Phase 3) | Single vocabulary list in config works across all enabled engines |
| GTK thread blocking | Settings UI (Phase 4) | Engine switch in settings UI shows spinner; no UI freeze measurable |
| No cloud consent indicator | Settings UI (Phase 4) | Enabling cloud engine shows confirmation dialog; overlay changes appearance in cloud mode |

## Sources

- [Google Cloud Speech-to-Text streaming documentation](https://docs.cloud.google.com/speech-to-text/docs/v1/transcribe-streaming-audio)
- [Google Cloud Speech C++ client library](https://docs.cloud.google.com/cpp/docs/reference/speech/latest)
- [gRPC C++ best practices](https://grpc.io/docs/languages/cpp/best_practices/)
- [gRPC C++ keepalive guide](https://grpc.github.io/grpc/cpp/md_doc_keepalive.html)
- [gRPC ClientReaderWriter reuse issue](https://github.com/GoogleCloudPlatform/cpp-samples/issues/47)
- [Vosk language model adaptation](https://alphacephei.com/vosk/lm)
- [Whisper custom vocabulary limitations](https://discuss.huggingface.co/t/adding-custom-vocabularies-on-whisper/29311)
- [Contextual biasing for Whisper](https://arxiv.org/html/2410.18363v1)
- [Custom language models with Vosk](https://arxiv.org/html/2503.21025v1)
- [OpenAI Whisper API limits](https://www.transcribetube.com/blog/openai-whisper-api-limits)
- [OpenAI Realtime transcription API](https://developers.openai.com/api/docs/guides/realtime-transcription/)
- [GSettings documentation](https://docs.gtk.org/gio/class.Settings.html)
- [Google Cloud API key management](https://docs.cloud.google.com/docs/authentication/api-keys)
- Codebase analysis: `IRecognitionService`, `TranscriptionOrchestrator`, `Config`, `ModelManager` interfaces

---
*Pitfalls research for: verbal-code multi-engine voice-to-text*
*Researched: 2026-03-07*
