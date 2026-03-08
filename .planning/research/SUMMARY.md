# Project Research Summary

**Project:** verbal-code
**Domain:** Linux system-wide voice-to-text dictation desktop application
**Researched:** 2026-03-07
**Confidence:** HIGH

## Executive Summary

verbal-code is a C++17 Linux desktop application that captures microphone input and injects transcribed text into any active text field system-wide. The codebase already has a working foundation: PipeWire audio capture, Vosk streaming recognition, Whisper.cpp batch refinement, X11/Wayland hotkey and injection backends, and a GTK3 overlay widget. The next milestone focuses on making this a reliable daily-driver by adding multi-engine support (including cloud APIs), custom vocabulary, a settings UI, and configuration persistence.

The recommended approach is to first refactor the recognition abstraction layer -- unifying `IRecognitionService` and `IRefinementService` into a single `IRecognitionEngine` interface with capability declarations -- before adding any new engine. This interface refactoring is the critical path: every subsequent feature (engine switching, cloud APIs, vocabulary, settings UI) depends on it. The only new required dependency is CPR (C++ HTTP client) for cloud API access via REST endpoints; the research strongly recommends REST over vendor SDKs (Google's gRPC client library alone would add 30+ minutes to build time). Whisper.cpp should be upgraded from v1.7.3 to v1.8.3 for Vulkan iGPU acceleration and prompt-based vocabulary support.

The primary risks are: (1) model memory explosion when multiple engines are loaded simultaneously -- solved by lazy loading one local engine at a time; (2) cloud API credentials stored in plaintext config -- solved by using libsecret for keyring integration with a chmod-600 file fallback; (3) the TranscriptionOrchestrator becoming a god object as engines multiply -- solved by extracting a strategy pattern early; and (4) GTK thread blocking during engine operations -- solved by running all long operations on worker threads with `g_idle_add()` for UI updates.

## Key Findings

### Recommended Stack

The existing stack (C++17/20, CMake, GTK3, PipeWire, Whisper.cpp, Vosk, nlohmann/json, GoogleTest) is validated and stays. New additions are minimal. See [STACK.md](STACK.md) for full details.

**New/upgraded technologies:**
- **CPR 1.14.1** (FetchContent): HTTP client for cloud speech APIs -- wraps libcurl with clean C++17 API, handles multipart upload and TLS
- **whisper.cpp v1.8.3** (upgrade from v1.7.3): Vulkan iGPU support (12x perf on integrated graphics), initial_prompt for vocabulary biasing. Note: repo moved to `ggml-org/whisper.cpp`
- **Cloud APIs via REST** (OpenAI gpt-4o-mini-transcribe, Google Cloud STT v2, Deepgram Nova-3): All accessed via simple HTTP POST, no vendor SDKs
- **libsecret** (optional system dep): Secure API key storage in system keyring, with file-based fallback
- **JSON config at XDG_CONFIG_HOME** (using existing nlohmann/json): Settings persistence without new dependencies

### Expected Features

See [FEATURES.md](FEATURES.md) for full analysis.

**Must have (table stakes):**
- Automatic punctuation (model-quality concern -- use Whisper small+ models)
- Accuracy above 90% on clear speech (larger models or cloud APIs)
- Configurable hotkey (infrastructure exists, needs UI exposure)
- Audio device selection (PipeWire enumeration, needs UI)
- Multi-language support (Whisper handles natively, expose in settings)

**Should have (differentiators):**
- Multiple recognition engines with runtime switching (Vosk, Whisper, cloud)
- Custom vocabulary / prompt biasing (unified word list adapted per engine)
- Settings UI (native GTK3 tabbed window)
- Clipboard restoration after injection (low effort, high polish)
- Polished floating widget with state indicators

**Defer (v2+):**
- Streaming/incremental transcription (high complexity, architecture changes)
- Voice Activity Detection / hands-free mode (requires streaming prerequisite)
- LLM post-processing (depends on stable multi-engine infrastructure)
- Auto-add to dictionary (clipboard monitoring fragile on Linux)

### Architecture Approach

The architecture extends the existing service-oriented pattern with three new major components: an EngineRegistry (factory + runtime switching), a VocabularyManager (unified word list with per-engine adaptation), and a SettingsWindow (GTK3 preferences with callback-based communication). The key structural change is unifying IRecognitionService and IRefinementService into a single IRecognitionEngine interface that declares capabilities (STREAMING, BATCH, CUSTOM_VOCAB, CLOUD). Engines are compile-time registered with `#ifdef` guards and runtime-switchable via the registry -- no dynamic plugin loading. See [ARCHITECTURE.md](ARCHITECTURE.md) for full component map and data flows.

**Major components:**
1. **EngineRegistry** -- discovers, instantiates, and switches recognition engines at runtime
2. **IRecognitionEngine** -- unified interface with capability declarations replacing the split IRecognitionService/IRefinementService
3. **TranscriptionOrchestrator** (refactored) -- delegates to engine-specific strategies instead of hardcoding Vosk+Whisper flow
4. **VocabularyManager** -- loads/saves user word lists, translates to engine-native formats
5. **SettingsWindow** -- GTK3 tabbed preferences, communicates via callbacks to Application
6. **Config** -- JSON-based persistent settings at XDG_CONFIG_HOME

### Critical Pitfalls

See [PITFALLS.md](PITFALLS.md) for full analysis with warning signs and recovery strategies.

1. **Interface too narrow for cloud engines** -- Current sync `feed_audio()`/`final_result()` contract breaks with async cloud APIs. Solve by adding capability declarations and async result paths before adding any cloud engine.
2. **Model memory explosion** -- Loading Whisper large-v3 + Vosk large simultaneously consumes 3GB+. Solve by lazy loading one local engine at a time with explicit unload on switch.
3. **Credentials in plaintext config** -- API keys in config.json are trivially exfiltrated. Solve by using libsecret keyring storage with file fallback, never storing keys in config.json.
4. **TranscriptionOrchestrator god object** -- Adding engines as if/else branches creates an untestable monolith. Solve by extracting strategy pattern before adding third engine.
5. **GTK thread blocking** -- Engine loading and cloud API calls freeze the settings UI. Solve by running all long operations on worker threads with `g_idle_add()` for UI updates.

## Implications for Roadmap

Based on research, suggested phase structure:

### Phase 1: Engine Abstraction and Registry

**Rationale:** Every subsequent feature depends on the unified engine interface. Architecture research and pitfalls research both identify this as the critical first step. The current IRecognitionService/IRefinementService split cannot accommodate cloud engines or runtime switching.
**Delivers:** IRecognitionEngine interface with capability declarations, EngineRegistry with factory pattern, migrated Vosk and Whisper implementations, refactored TranscriptionOrchestrator with strategy pattern.
**Addresses:** Multi-engine support foundation, accuracy improvement path (by enabling engine switching)
**Avoids:** Interface-too-narrow pitfall, god-object orchestrator pitfall, model memory explosion pitfall (by implementing lazy loading)

### Phase 2: Configuration and Persistence

**Rationale:** Settings UI and cloud APIs both depend on config persistence. Config must be split into settings vs. credentials before any cloud integration.
**Delivers:** JSON config file at XDG_CONFIG_HOME, config load/save with schema validation, separate credentials storage, XDG path resolution.
**Addresses:** Config persistence (enabler for all subsequent features), configurable hotkey, audio device selection storage
**Avoids:** Credentials-in-plaintext pitfall (by establishing credential separation from the start)

### Phase 3: Cloud Engine Integration

**Rationale:** Cloud engines deliver the biggest accuracy improvement -- the stated primary pain point. With the engine abstraction in place, adding cloud backends is straightforward implementation against a stable interface.
**Delivers:** CPR HTTP client integration, OpenAI gpt-4o-mini-transcribe engine, Google Cloud STT v2 engine, audio encoding (WAV/FLAC for upload), async cloud calls with error handling, network failure fallback to local engine.
**Uses:** CPR 1.14.1, std::async/std::future, libsecret (optional)
**Avoids:** Silent cloud failure pitfall (by implementing health monitoring and local fallback), raw PCM upload pitfall (by adding FLAC encoding)

### Phase 4: Custom Vocabulary

**Rationale:** High-value differentiator with manageable complexity. Depends on engine abstraction (set_vocabulary interface) and config persistence (vocabulary storage). Can be built independently of cloud engines.
**Delivers:** VocabularyManager with unified word list, per-engine adaptation (Whisper initial_prompt, Vosk grammar, Google phrase boost), vocabulary JSON storage, vocabulary CRUD operations.
**Addresses:** Custom vocabulary / prompt biasing differentiator
**Avoids:** Vocabulary divergence pitfall (by designing unified model before any engine-specific adaptation)

### Phase 5: Settings UI

**Rationale:** All backend components must be stable before wiring a UI to them. Settings UI is the user-facing integration point for engine switching, vocabulary management, audio device selection, and hotkey configuration.
**Delivers:** GTK3 tabbed settings window (Recognition, Vocabulary, Audio, Hotkeys, Appearance tabs), engine selection dropdowns, vocabulary editor, audio device selector, hotkey configuration.
**Addresses:** Settings UI (table stakes for non-CLI users), configurable hotkey, audio device selection, model management
**Avoids:** GTK thread blocking pitfall (by establishing async-operation-to-GTK-thread pattern), settings-mutating-services pitfall (by using callback-based communication)

### Phase 6: Widget Polish and Clipboard Restoration

**Rationale:** Final polish phase. Minimal architectural dependencies, mostly visual and UX refinements.
**Delivers:** Overlay state machine (IDLE/RECORDING/PROCESSING/ERROR), active engine display, audio level visualization, clipboard save/restore around injection, cloud mode visual indicator.
**Addresses:** Polished floating widget, clipboard restoration, cloud consent indicator
**Avoids:** No cloud consent indicator pitfall

### Phase Ordering Rationale

- **Phase 1 before everything:** The engine abstraction is the foundation. Architecture, features, and pitfalls research all converge on this. Without it, cloud engines require hacks and the orchestrator becomes unmaintainable.
- **Phase 2 before 3:** Cloud engines need credential storage. Config persistence is a prerequisite, not something to bolt on after.
- **Phase 3 before 5:** Cloud engines should work before building UI to configure them. Avoids building UI against unstable backends.
- **Phase 4 parallel-capable with 3:** Vocabulary depends on Phase 1 (engine interface) and Phase 2 (config), not on cloud engines. Could be developed in parallel with Phase 3.
- **Phase 5 after 3 and 4:** Settings UI integrates all backend features. Building it last means fewer UI rework cycles.
- **Phase 6 last:** Pure polish. No other phase depends on it.

### Research Flags

Phases likely needing deeper research during planning:
- **Phase 1:** Needs research-phase -- the IRecognitionEngine interface design is architecturally critical and the Vosk/Whisper migration has subtle compatibility concerns (Vosk grammar must be set at construction time, Whisper prompt injection is limited to 224 tokens)
- **Phase 3:** Needs research-phase -- cloud API integration involves audio encoding formats, error handling patterns, rate limiting, and credential management that benefit from targeted API documentation review

Phases with standard patterns (skip research-phase):
- **Phase 2:** Well-documented -- JSON config with nlohmann/json, XDG paths, file permissions. Standard Linux desktop patterns.
- **Phase 4:** Moderate -- vocabulary model is well-defined in architecture research. Engine-specific adaptation has known limitations documented in pitfalls.
- **Phase 5:** Well-documented -- GTK3 settings window is a standard pattern. The async-to-GTK-thread pattern is well-established.
- **Phase 6:** Well-documented -- overlay refinement and clipboard operations are straightforward GTK3/xclip work.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Minimal new dependencies (only CPR). Existing stack validated by working codebase. Cloud API endpoints verified against official docs. |
| Features | HIGH | Feature landscape well-mapped against 6+ competing tools. Clear table-stakes vs. differentiator separation. Anti-features explicitly defined. |
| Architecture | HIGH | Designs derived directly from existing codebase patterns. Interface proposals extend proven abstractions. Build order accounts for dependencies. |
| Pitfalls | HIGH | Pitfalls grounded in codebase analysis and API documentation. Warning signs and recovery strategies are specific and actionable. |

**Overall confidence:** HIGH

### Gaps to Address

- **Whisper.cpp v1.8.3 migration risk:** The repo URL changed (`ggerganov` to `ggml-org`). Verify API compatibility with existing WhisperRecognitionService during Phase 1.
- **Audio encoding for cloud APIs:** The project currently only handles raw PCM int16. FLAC or WAV encoding is needed for cloud upload. Evaluate whether to use libsndfile or construct WAV headers manually -- decide during Phase 3 planning.
- **libsecret availability on minimal WMs:** Tiling WM users (Sway, i3) may not have a keyring daemon running. The fallback path (chmod 600 credentials file) needs explicit testing.
- **Vosk grammar reconstruction cost:** Vosk requires destroying and recreating the recognizer to change vocabulary. Measure the latency impact during Phase 4 to determine if vocabulary changes should be deferred until next recording session.
- **OpenAI API rate limits and costs:** gpt-4o-mini-transcribe at $0.006/min is cheap, but rapid-fire short utterances could accumulate. Implement per-minute request caps during Phase 3.

## Sources

### Primary (HIGH confidence)
- Existing verbal-code codebase -- all architecture designs derived from actual code
- [Vosk API documentation](https://alphacephei.com/vosk/) -- vocabulary/grammar support
- [whisper.cpp GitHub releases](https://github.com/ggml-org/whisper.cpp/releases) -- v1.8.3 features
- [CPR GitHub releases](https://github.com/libcpr/cpr/releases) -- v1.14.1 compatibility
- [GTK3 documentation](https://docs.gtk.org/gtk3/) -- settings window patterns
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/basedir-spec-latest.html) -- config paths

### Secondary (MEDIUM confidence)
- [OpenAI Speech-to-Text API](https://platform.openai.com/docs/guides/speech-to-text) -- gpt-4o-mini-transcribe endpoint and pricing
- [Google Cloud Speech-to-Text REST API](https://docs.cloud.google.com/speech-to-text/docs/reference/rest) -- REST vs client library tradeoffs
- [Deepgram API](https://deepgram.com/pricing) -- Nova-3 pricing and accuracy benchmarks
- [Whisper prompt engineering](https://medium.com/axinc-ai/prompt-engineering-in-whisper-6bb18003562d) -- initial_prompt vocabulary biasing effectiveness

### Tertiary (LOW confidence)
- [Contextual biasing for Whisper](https://arxiv.org/html/2410.18363v1) -- neural-symbolic prefix tree approach (academic, not yet practical)
- Cloud API pricing -- subject to change; verify before implementation

---
*Research completed: 2026-03-07*
*Ready for roadmap: yes*
