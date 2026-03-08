# Technology Stack

**Project:** verbal-code (subsequent milestone: multi-engine, custom vocabulary, settings UI)
**Researched:** 2026-03-07

## Existing Stack (Not Re-Researched)

Already in use and validated: C++17/20, CMake 3.22+, GTK3 (overlay), PipeWire (audio), Whisper.cpp v1.7.3 (refinement), Vosk 0.3.45 (recognition), nlohmann/json v3.11.3 (JSON), GoogleTest v1.14.0, xdotool/ydotool (injection), XCB (X11 hotkeys), GIO/D-Bus (Wayland hotkeys).

## New Stack Additions

### Cloud Speech API HTTP Client

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| CPR (C++ Requests) | 1.14.1 | HTTP client for cloud speech APIs | C++17 native, FetchContent-ready, wraps libcurl with clean API. Handles multipart form upload (audio files), JSON responses, async requests, and TLS out of the box. Already matches the project's FetchContent dependency pattern. |

**Confidence:** HIGH (verified version from GitHub releases, Nov 2024; C++17 requirement matches project)

**Integration:**
```cmake
FetchContent_Declare(cpr
    GIT_REPOSITORY https://github.com/libcpr/cpr.git
    GIT_TAG        1.14.1
    GIT_SHALLOW    TRUE
)
FetchContent_MakeAvailable(cpr)
target_link_libraries(verbal_recognition PRIVATE cpr::cpr)
```

CPR pulls in libcurl automatically -- no manual curl dependency management needed.

### Cloud Speech Recognition Engines

The project should access all cloud APIs via their REST/HTTP endpoints using CPR, NOT via vendor-specific C++ client libraries. This is a critical architectural decision.

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| OpenAI Audio API (REST) | gpt-4o-mini-transcribe | Primary cloud engine | Best accuracy (lower WER than whisper-1), supports prompt-based custom vocabulary, simple REST endpoint (POST multipart to /v1/audio/transcriptions). $0.006/min. |
| Google Cloud Speech-to-Text V2 (REST) | v2 | Secondary cloud engine | Strong accuracy, supports phrase boost for custom vocabulary via API params. REST API avoids the massive google-cloud-cpp dependency (which pulls gRPC, protobuf, abseil -- hundreds of MB of build deps). |
| Deepgram (REST) | Nova-3 | Optional tertiary engine | Lowest latency (~300ms), good accuracy (7.6% WER), keyword boosting API parameter. $0.0077/min pay-as-you-go. |

**Confidence:** MEDIUM-HIGH (API endpoints verified via official docs; pricing current as of early 2026)

**Why REST over vendor SDKs:**
- google-cloud-cpp pulls gRPC + protobuf + abseil + dozens of transitive deps. Build time goes from minutes to 30+ minutes. Binary size bloats. Not worth it for a single API call.
- OpenAI has no official C++ SDK at all.
- Deepgram has no official C++ SDK.
- All three services have simple REST APIs: POST audio file, receive JSON transcription. CPR handles this trivially.

### Custom Vocabulary Support

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Whisper.cpp initial_prompt | v1.8.3 (upgrade from v1.7.3) | Local prompt-based vocabulary boosting | Whisper accepts initial_prompt that primes the decoder with domain terms. Limited to 224 tokens and primarily affects first 30s segment, but effective for short dictation. Free, no network. |
| Vosk custom language model | 0.3.45 | Local vocabulary customization | Vosk supports custom phonetic dictionaries and domain-specific n-gram language models. More powerful than Whisper prompts but requires offline model compilation (Kaldi + SRILM toolchain, ~15 min build). |
| OpenAI prompt parameter | API | Cloud prompt-based vocabulary | gpt-4o-mini-transcribe accepts prompt parameter for custom vocabulary hints. Same mechanism as Whisper but with larger model capacity. |
| Google phrase boost | API v2 | Cloud keyword boosting | SpeechAdaptation API allows phrase sets with boost values (0-20 scale) to bias recognition toward specific terms. Most structured approach to custom vocabulary. |

**Confidence:** HIGH for Whisper/Vosk (verified via official docs), MEDIUM for cloud APIs (verified via API docs, but real-world effectiveness varies)

**Recommended approach:** Store user vocabulary as a JSON file. Each engine adapter reads it and translates to the engine's native format (initial_prompt for Whisper, phrase boost for Google, prompt for OpenAI).

### Whisper.cpp Upgrade

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| whisper.cpp | v1.8.3 | Upgrade from v1.7.3 | Adds Vulkan iGPU support (12x perf boost on integrated graphics), initial_prompt parameter support, minor accuracy improvements. Released Jan 2025. |

**Confidence:** HIGH (verified from GitHub releases)

Note: whisper.cpp moved from `ggerganov/whisper.cpp` to `ggml-org/whisper.cpp`. Update the FetchContent URL.

### Configuration Persistence

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| nlohmann/json (existing) | 3.11.3 | Settings file format | Already a dependency. JSON config file at XDG_CONFIG_HOME/verbal-code/config.json. Simple, human-editable, no additional dependencies. |

**Confidence:** HIGH

**Why NOT GSettings:**
- GSettings requires a compiled XML schema installed system-wide, a dconf backend, and ties you to GNOME ecosystem assumptions.
- This app targets all Linux desktops (KDE, XFCE, Sway, etc.), not just GNOME.
- JSON file at `$XDG_CONFIG_HOME/verbal-code/config.json` (fallback `~/.config/verbal-code/config.json`) is universally portable.
- nlohmann/json is already in the dependency tree. Zero new deps.

### Settings UI

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| GTK3 (existing) | 3.24.x | Settings dialog window | Already linked for overlay. Use GtkDialog/GtkWindow with GtkNotebook for tabbed settings. GtkComboBoxText for engine selection, GtkSwitch for toggles, GtkEntry/GtkFileChooserButton for paths. |

**Confidence:** HIGH

**Why NOT GTK4:**
- Project already uses GTK3 for the overlay. Mixing GTK3 and GTK4 in one process is not supported.
- Migrating overlay to GTK4 is a separate effort with no accuracy benefit. GTK3 is stable and maintained through at least 2027.
- Settings UI is a simple form -- GTK3 is perfectly adequate.

**Settings UI components needed (all GTK3 built-in):**
- `GtkNotebook` -- tabbed interface (General, Recognition, Audio, Hotkeys)
- `GtkComboBoxText` -- engine selection dropdown
- `GtkSwitch` -- boolean toggles (auto-start, cloud API enable)
- `GtkEntry` -- API key entry, custom vocabulary terms
- `GtkTextView` -- vocabulary list editing
- `GtkScale` -- sensitivity/threshold sliders
- `GtkFileChooserButton` -- model file paths
- `GtkSpinButton` -- numeric settings

### API Key Management

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| libsecret | 0.21+ | Secure API key storage | Integrates with system keyring (GNOME Keyring, KWallet). Stores cloud API keys securely instead of plaintext in config. Available via pkg_check_modules on all major distros. |

**Confidence:** MEDIUM (standard Linux practice, but adds a new system dependency -- fallback to file-based storage with restrictive permissions is acceptable for v1)

**Fallback:** If libsecret is not available, store API keys in `$XDG_CONFIG_HOME/verbal-code/credentials.json` with `chmod 600`. Warn user in settings UI.

### Async Task Management

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| std::async / std::future | C++17 stdlib | Cloud API calls | Cloud API calls must be async to avoid blocking the audio pipeline. std::async with std::future is sufficient -- no need for a full async framework. The recognition service already has a streaming thread; cloud calls happen at utterance end (batch mode). |

**Confidence:** HIGH

**Why NOT boost::asio or similar:**
- Cloud API calls are infrequent (once per utterance, not streaming).
- std::async + CPR's built-in async support is sufficient.
- Adding boost would be massive overkill.

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| HTTP client | CPR 1.14.1 | Raw libcurl | libcurl C API is verbose and error-prone. CPR provides type-safe C++ wrapper with identical performance. |
| HTTP client | CPR 1.14.1 | google-cloud-cpp | Pulls gRPC + protobuf + abseil. 30+ min build time increase. Only covers Google, not OpenAI/Deepgram. |
| HTTP client | CPR 1.14.1 | curlcpp | Less maintained, smaller community. CPR has 6k+ GitHub stars and active development. |
| Config storage | JSON file (nlohmann) | GSettings/dconf | GNOME-specific, requires schema compilation, not portable to non-GNOME desktops. |
| Config storage | JSON file (nlohmann) | SQLite | Overkill for key-value settings. Not human-editable. |
| Config storage | JSON file (nlohmann) | TOML (toml++) | Would add a new dependency for marginal benefit over JSON. |
| Settings UI | GTK3 | GTK4 | Cannot mix GTK3/GTK4 in one process. Migration is a separate effort. |
| Settings UI | GTK3 | Qt | Would add massive dependency. GTK3 already linked. |
| Cloud STT | REST via CPR | gRPC streaming | Batch transcription (POST audio file) is simpler, more reliable, and sufficient for dictation use case. Streaming cloud STT adds complexity with marginal latency benefit for short utterances. |
| Key storage | libsecret | plaintext file | Insecure for API keys. libsecret is standard on Linux desktops. |
| Async | std::async | boost::asio | Overkill for infrequent batch HTTP calls. |

## Installation

```bash
# New system dependencies (for libsecret, optional)
sudo apt install libsecret-1-dev

# CPR is pulled via FetchContent -- no system install needed
# All other new deps are fetched at build time or already present
```

## Dependency Summary (New Only)

| Dependency | Type | Required | Notes |
|------------|------|----------|-------|
| CPR 1.14.1 | FetchContent | Yes | HTTP client for cloud APIs |
| whisper.cpp v1.8.3 | FetchContent (upgrade) | Yes | Replaces v1.7.3, new repo URL |
| libsecret | System (pkg-config) | Optional | API key security. Graceful fallback if absent. |

Total new required dependencies: **1** (CPR). Everything else is an upgrade or optional.

## Sources

- [CPR GitHub releases](https://github.com/libcpr/cpr/releases) - v1.14.1 verified
- [whisper.cpp GitHub releases](https://github.com/ggml-org/whisper.cpp/releases) - v1.8.3 verified
- [OpenAI Speech-to-Text API](https://platform.openai.com/docs/guides/speech-to-text) - gpt-4o-mini-transcribe docs
- [Google Cloud Speech-to-Text REST API](https://docs.cloud.google.com/speech-to-text/docs/reference/rest) - REST vs client library
- [Deepgram API](https://deepgram.com/pricing) - Nova-3 pricing
- [Vosk language model adaptation](https://alphacephei.com/vosk/lm) - custom vocabulary docs
- [Whisper prompting guide](https://cookbook.openai.com/examples/whisper_prompting_guide) - initial_prompt usage
- [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/basedir-spec-latest.html) - config path standard
- [Deepgram STT comparison 2026](https://deepgram.com/learn/best-speech-to-text-apis-2026) - accuracy benchmarks
