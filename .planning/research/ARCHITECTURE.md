# Architecture Patterns

**Domain:** Multi-engine speech recognition with plugin architecture, settings UI, and custom vocabulary for a Linux voice-to-text desktop application
**Researched:** 2026-03-07

## Current Architecture Assessment

The existing codebase already follows a clean service-oriented architecture with abstract interfaces (`IRecognitionService`, `IRefinementService`, `IOverlayService`, etc.), compile-time backend selection via `#ifdef`, and a `TranscriptionOrchestrator` that coordinates Vosk (streaming) + Whisper (batch refinement). This is a strong foundation. The architecture recommendations below extend it rather than replace it.

## Recommended Architecture

### High-Level Component Map

```
+------------------+     +---------------------+     +-------------------+
|   Settings UI    |     |    Overlay Widget    |     |   Hotkey Service   |
|   (GTK3 Window)  |     |   (GTK3 Floating)   |     |   (X11/Wayland)    |
+--------+---------+     +---------+-----------+     +--------+----------+
         |                         |                           |
         v                         v                           v
+--------+-------------------------+---------------------------+----------+
|                          Application                                     |
|  (Owns all services, wires callbacks, manages lifecycle)                 |
+-----+------------+----------------+-----------------+-------------------+
      |            |                |                 |
      v            v                v                 v
+-----+----+ +-----+------+ +------+-------+ +-------+--------+
|  Config   | | Engine     | | Vocabulary   | | Audio Service  |
| (JSON)    | | Registry   | | Manager      | | (PipeWire)     |
+-----------+ +-----+------+ +------+-------+ +----------------+
                    |                |
          +---------+---------+     |
          |         |         |     |
          v         v         v     v
      +---+--+ +---+---+ +---+---+---+
      | Vosk | |Whisper| | Cloud API |
      |Engine| |Engine | | Engine    |
      +------+ +-------+ +-----------+
```

### Component Boundaries

| Component | Responsibility | Communicates With | Owns |
|-----------|---------------|-------------------|------|
| **Application** | Service lifecycle, callback wiring, GTK main loop | All components | All service unique_ptrs |
| **EngineRegistry** | Discovers, instantiates, and switches recognition engines | Application, Config, VocabularyManager | Engine instances |
| **IRecognitionEngine** | Unified interface wrapping both streaming + batch recognition | EngineRegistry, TranscriptionOrchestrator | Engine-specific resources (models, contexts) |
| **VocabularyManager** | Loads/saves user word lists, applies them to engines | Config, EngineRegistry | Vocabulary files |
| **TranscriptionOrchestrator** | Coordinates recording flow: streaming partials, batch refinement, engine selection | Active engine(s), Application | Recording state |
| **SettingsWindow** | GTK3 preferences window for engine, audio, hotkey, vocabulary configuration | Config, Application (via callbacks) | GTK widgets |
| **OverlayWidget** | Floating status indicator (existing, refined) | Application | GTK window |
| **Config** | JSON-based persistent settings | All components that need preferences | JSON data, file I/O |

## Key Architectural Changes from Current State

### 1. Unify IRecognitionService and IRefinementService into IRecognitionEngine

**Problem:** The current split between `IRecognitionService` (streaming, used by Vosk) and `IRefinementService` (batch, used by Whisper) creates an asymmetry. Adding a cloud API that supports both modes would require implementing two interfaces.

**Solution:** A single `IRecognitionEngine` interface that declares capabilities:

```cpp
// Confidence: HIGH — based on existing codebase patterns

enum class EngineCapability {
    STREAMING,       // Can produce partial results in real-time
    BATCH,           // Can process a complete audio buffer
    CUSTOM_VOCAB,    // Supports vocabulary customization
    CLOUD            // Requires network access
};

struct EngineInfo {
    std::string id;           // "vosk", "whisper", "google-cloud"
    std::string display_name; // "Vosk (Offline)", "Whisper (Offline)", "Google Cloud STT"
    std::vector<EngineCapability> capabilities;
};

class IRecognitionEngine {
public:
    virtual ~IRecognitionEngine() = default;

    virtual EngineInfo info() const = 0;

    // Lifecycle
    virtual Result<void> init(const nlohmann::json& engine_config) = 0;
    virtual void shutdown() = 0;
    virtual bool is_initialized() const = 0;

    // Capability query
    virtual bool supports(EngineCapability cap) const = 0;

    // Streaming (only if STREAMING capability)
    virtual void set_on_partial(TextCallback cb) = 0;
    virtual void start_streaming() = 0;
    virtual void feed_audio(const AudioSample* data, size_t count) = 0;
    virtual void stop_streaming() = 0;
    virtual std::string final_result() = 0;
    virtual void reset() = 0;

    // Batch (only if BATCH capability)
    virtual Result<std::string> transcribe(const std::vector<AudioSample>& audio,
                                           int sample_rate = DEFAULT_SAMPLE_RATE) = 0;

    // Vocabulary (only if CUSTOM_VOCAB capability)
    virtual void set_vocabulary(const std::vector<std::string>& words) = 0;
};
```

**Why this over a plugin/shared-library approach:** The project has a small, known set of engines (Vosk, Whisper, 1-2 cloud APIs). Dynamic `.so` loading adds complexity (ABI stability, symbol resolution, packaging) without real benefit. Compile-time registration with `#ifdef` guards (already used for backends) is the right pattern here. A factory + registry gives runtime switching without dynamic loading.

### 2. EngineRegistry: Factory + Runtime Switching

```cpp
// Confidence: HIGH — straightforward factory pattern matching existing codebase style

class EngineRegistry {
public:
    // Register available engines at startup (compile-time gated)
    void register_engine(std::unique_ptr<IRecognitionEngine> engine);

    // List what's available
    std::vector<EngineInfo> available_engines() const;

    // Get engine by id
    IRecognitionEngine* get_engine(const std::string& id) const;

    // Convenience: get all engines with a capability
    std::vector<IRecognitionEngine*> engines_with(EngineCapability cap) const;

private:
    std::vector<std::unique_ptr<IRecognitionEngine>> engines_;
};
```

Application startup registers engines:

```cpp
Result<void> Application::init_engines() {
    engine_registry_ = std::make_unique<EngineRegistry>();

#ifdef VERBAL_HAS_VOSK
    engine_registry_->register_engine(
        std::make_unique<VoskEngine>(model_manager_));
#endif
#ifdef VERBAL_ENABLE_WHISPER
    engine_registry_->register_engine(
        std::make_unique<WhisperEngine>(model_manager_));
#endif
#ifdef VERBAL_ENABLE_GOOGLE_STT
    engine_registry_->register_engine(
        std::make_unique<GoogleCloudEngine>());
#endif
    // Init engines based on config
    // ...
}
```

### 3. Revised TranscriptionOrchestrator

The orchestrator currently hard-codes the Vosk+Whisper pipeline. Generalize it to work with any engine combination:

```cpp
// Confidence: HIGH — extends existing orchestrator pattern

class TranscriptionOrchestrator {
public:
    struct Config {
        std::string streaming_engine_id;    // Engine for real-time partials (e.g., "vosk")
        std::string refinement_engine_id;   // Engine for batch refinement (e.g., "whisper")
        bool enable_refinement;
        double refinement_threshold;
    };

    TranscriptionOrchestrator(EngineRegistry* registry, Config config);

    // Same callbacks as today
    void set_on_partial(PartialCallback cb);
    void set_on_refined(RefinedCallback cb);

    void on_recording_start();
    void on_recording_stop(const std::vector<AudioSample>& audio);

    // Switch engines at runtime (from settings)
    void reconfigure(Config new_config);
};
```

**Key design point:** The orchestrator does NOT own engines. It borrows pointers from the registry. This allows the settings UI to trigger `reconfigure()` without destroying/recreating engines.

### 4. VocabularyManager

```cpp
// Confidence: MEDIUM — vocabulary support varies significantly by engine

struct VocabularyEntry {
    std::string word;          // The word or phrase
    std::string sounds_like;   // Optional pronunciation hint
    float boost;               // Priority weight (1.0 = normal)
};

class VocabularyManager {
public:
    explicit VocabularyManager(const std::string& vocab_dir);

    Result<void> load();
    Result<void> save() const;

    // User-facing operations
    void add_word(const std::string& word, float boost = 1.0f);
    void remove_word(const std::string& word);
    std::vector<VocabularyEntry> entries() const;

    // Apply vocabulary to an engine (engine-specific adaptation)
    void apply_to(IRecognitionEngine* engine);

private:
    std::string vocab_path_;
    std::vector<VocabularyEntry> entries_;
};
```

**How vocabulary works per engine:**

| Engine | Mechanism | Confidence |
|--------|-----------|------------|
| **Vosk** | `vosk_recognizer_set_words()` or grammar-based recognizer with restricted word list. Requires dynamic-graph models (small/medium). Large static models do NOT support runtime vocabulary changes. | HIGH |
| **Whisper** | `initial_prompt` parameter containing vocabulary words as a prompt prefix. Not true vocabulary injection, but practically effective (reported 90-95% accuracy improvement for domain terms). | MEDIUM |
| **Google Cloud STT** | `SpeechAdaptation` API with `PhraseSet` for boosting specific words/phrases. Proper built-in support. | HIGH |

**Storage format:** JSON file at `~/.config/verbal-code/vocabulary.json`:
```json
{
  "words": [
    {"word": "Kubernetes", "boost": 2.0},
    {"word": "kubectl", "sounds_like": "kube-cuttle", "boost": 2.0}
  ]
}
```

### 5. Settings UI (GTK3)

**Pattern:** A separate `GtkWindow` (not a dialog parented to the overlay) managed by the Application. Opened from the overlay's context menu. Communicates changes back to Application via callbacks, which updates Config and notifies affected services.

```
Overlay Context Menu
    |
    +--> "Settings" menu item
            |
            v
    Application::on_settings_requested()
            |
            v
    SettingsWindow::present()  (creates or shows existing window)
            |
            v
    User changes settings
            |
            v
    SettingsWindow callback --> Application
            |
            v
    Application updates Config, reconfigures services
```

**Settings Window Tabs/Sections:**

| Section | Controls | Affects |
|---------|----------|---------|
| **Recognition** | Engine dropdown (streaming), Engine dropdown (refinement), Enable refinement toggle | EngineRegistry, TranscriptionOrchestrator |
| **Vocabulary** | Word list with add/remove, boost slider | VocabularyManager |
| **Audio** | Input device selector, sample rate | AudioService |
| **Hotkeys** | Modifier checkboxes, trigger key | HotkeyService |
| **Appearance** | Overlay size, always-on-top toggle | OverlayService |

```cpp
// Confidence: HIGH — follows existing GTK3 callback pattern in the codebase

class SettingsWindow {
public:
    explicit SettingsWindow(const Config& config);
    ~SettingsWindow();

    void present();  // Show or raise the window
    void hide();

    // Callbacks for when user changes settings
    using EngineChangeCallback = std::function<void(const std::string& streaming_id,
                                                     const std::string& refinement_id)>;
    using VocabChangeCallback = std::function<void()>;

    void set_on_engine_change(EngineChangeCallback cb);
    void set_on_vocab_change(VocabChangeCallback cb);
    void set_on_hotkey_change(HotkeyChangeCallback cb);

    // Populate dropdowns with available engines
    void set_available_engines(const std::vector<EngineInfo>& engines);

private:
    GtkWidget* window_ = nullptr;
    // ... GTK widgets
};
```

**Why not GSettings:** The project already uses nlohmann/json for config storage. GSettings requires a compiled schema, gsettings-desktop-schemas installation, and D-Bus. The JSON approach is simpler, already works, and is more portable. Keep it.

### 6. Refined Overlay Widget

The existing `IOverlayService` interface is adequate. Refinements are implementation-level, not architectural:

- Add `OverlayState::PROCESSING` for the Whisper refinement phase (between recording stop and text injection)
- Add `set_status_text(const std::string&)` for showing brief status messages ("Whisper refining...", "Injected 42 chars")
- Add `set_active_engine(const std::string& name)` for displaying which engine is active

```cpp
enum class OverlayState {
    IDLE,
    RECORDING,
    PROCESSING,   // NEW: post-recording, running refinement
    ERROR         // NEW: transient error display
};
```

## Data Flow

### Recording Flow (Primary Path)

```
1. User presses hotkey
   HotkeyService --[on_press]--> Application

2. Application starts recording
   Application --> AudioService::start_capture()
   Application --> Orchestrator::on_recording_start()
   Application --> Overlay::set_state(RECORDING)

3. Audio flows through ring buffer
   PipeWire --> RingBuffer --> StreamingEngine::feed_audio()
   StreamingEngine --[on_partial]--> Orchestrator --[on_partial]--> Application
   Application --> Overlay (optional partial display)

4. User releases hotkey
   HotkeyService --[on_release]--> Application

5. Application stops recording, triggers refinement
   Application --> AudioService::stop_capture()
   Application --> Orchestrator::on_recording_stop(audio)
   Application --> Overlay::set_state(PROCESSING)

6. Orchestrator runs refinement (if enabled)
   Orchestrator --> RefinementEngine::transcribe(audio)
   Orchestrator compares results, picks best
   Orchestrator --[on_refined]--> Application

7. Application injects text
   Application --> wait_for_modifiers_released()
   Application --> InjectionService::inject_text(final_text)
   Application --> Overlay::set_state(IDLE)
```

### Settings Change Flow

```
1. User opens settings from overlay context menu
   Overlay --[on_settings_requested]--> Application
   Application --> SettingsWindow::present()

2. User changes streaming engine
   SettingsWindow --[on_engine_change]--> Application

3. Application reconfigures
   Application --> Config::set("streaming_engine", new_id)
   Application --> Config::save()
   Application --> Orchestrator::reconfigure(new_config)
   Application --> Overlay::set_active_engine(new_name)
```

### Vocabulary Change Flow

```
1. User adds word in settings
   SettingsWindow --[on_vocab_change]--> Application

2. Application updates vocabulary
   Application --> VocabularyManager::add_word(word)
   Application --> VocabularyManager::save()
   Application --> VocabularyManager::apply_to(streaming_engine)
   Application --> VocabularyManager::apply_to(refinement_engine)
```

## Patterns to Follow

### Pattern 1: Capability-Based Interface

**What:** Engines declare capabilities rather than throwing "not supported" errors. Callers check `supports(cap)` before invoking capability-specific methods.

**When:** Any interface where implementations vary in what they support.

**Why:** Avoids runtime errors from calling unsupported methods. The orchestrator can intelligently select engines based on what they can do. The settings UI can disable controls for unsupported features.

### Pattern 2: Config-Driven Initialization

**What:** Engine-specific configuration lives in a JSON sub-object keyed by engine id. Each engine receives its own config blob during `init()`.

**When:** Adding any new engine.

```json
{
  "engines": {
    "vosk": {"model": "vosk-model-en-us-0.22"},
    "whisper": {"model": "ggml-base.en.bin"},
    "google-cloud": {"credentials_path": "~/.config/verbal-code/google-creds.json"}
  },
  "streaming_engine": "vosk",
  "refinement_engine": "whisper",
  "enable_refinement": true
}
```

### Pattern 3: Callback-Based UI Communication

**What:** UI components communicate with the Application exclusively through typed callbacks (std::function). No direct service references in UI code.

**When:** Any UI component that triggers behavior changes.

**Why:** The existing codebase already follows this pattern (overlay callbacks). It keeps GTK code decoupled from service logic, makes testing possible without GTK, and avoids threading issues (GTK must run on the main thread; services may run on worker threads).

## Anti-Patterns to Avoid

### Anti-Pattern 1: Dynamic Plugin Loading (.so/.dll)

**What:** Loading recognition engines as shared libraries at runtime.

**Why bad:** ABI stability across C++ boundaries is fragile. Packaging becomes complex. The engine set is small and known at compile time. The `#ifdef` conditional compilation pattern already works well in the codebase.

**Instead:** Compile-time registration with `#ifdef` guards + factory pattern for runtime switching.

### Anti-Pattern 2: Engine Singletons

**What:** Making recognition engines globally accessible singletons.

**Why bad:** Prevents testing, makes lifecycle management opaque, creates hidden dependencies.

**Instead:** Engines owned by EngineRegistry, accessed via Application. Already the pattern used for other services.

### Anti-Pattern 3: Settings UI Directly Mutating Services

**What:** Having the settings window hold pointers to services and call methods on them directly.

**Why bad:** Threading issues (GTK main thread vs. service threads), tight coupling, hard to test.

**Instead:** Settings window fires callbacks to Application, which coordinates the changes on appropriate threads.

### Anti-Pattern 4: Blocking Cloud API Calls on GTK Thread

**What:** Making synchronous HTTP requests to cloud STT APIs from the main thread.

**Why bad:** Freezes the UI during network calls.

**Instead:** Cloud engines must run transcription on a worker thread (the orchestrator already does this by calling `on_recording_stop` from a detached thread).

## Build Order (Dependencies Between Components)

Components should be built in this order, reflecting dependency chains:

```
Phase 1: IRecognitionEngine interface + EngineRegistry
    Depends on: core/ (existing)
    Why first: Everything else builds on this abstraction

Phase 2: Migrate existing Vosk and Whisper to IRecognitionEngine
    Depends on: Phase 1
    Why second: Validates the interface against real implementations
    Note: Keep backward compat during migration by having both old and new interfaces temporarily

Phase 3: Revised TranscriptionOrchestrator
    Depends on: Phase 2 (needs engines implementing new interface)
    Why third: Core data flow must work before adding features on top

Phase 4: VocabularyManager
    Depends on: Phase 1 (IRecognitionEngine::set_vocabulary)
    Can parallel with: Phase 3
    Why here: Independent of orchestrator, but needs engine interface

Phase 5: SettingsWindow
    Depends on: Phase 3 (engine switching), Phase 4 (vocabulary UI)
    Why later: Needs all backend components to be stable before wiring UI

Phase 6: Cloud engine integration (Google/OpenAI)
    Depends on: Phase 1 (interface), Phase 3 (orchestrator handles it)
    Can parallel with: Phase 5
    Why last: Adds new engine implementations against stable interface

Phase 7: Overlay refinement
    Depends on: Phase 3 (new OverlayState values)
    Can parallel with: Phase 5, 6
    Why flexible: Mostly visual polish, minimal architectural dependencies
```

## Scalability Considerations

| Concern | Current (1 engine pair) | Multi-engine (3-4 engines) | With cloud APIs |
|---------|------------------------|---------------------------|-----------------|
| Memory | Vosk + Whisper models loaded (~1-2GB) | Only active engines loaded; lazy init | Minimal (no local model) |
| Latency | Ring buffer streaming, Whisper batch | Same pattern, engine selection adds negligible overhead | Network round-trip (200-2000ms) |
| Config complexity | 10 settings | ~25 settings (engine-specific sub-configs) | Add API key management |
| Thread safety | Orchestrator on worker thread | Same; EngineRegistry is read-mostly after init | Cloud calls already async |

## Sources

- Existing verbal-code codebase (HIGH confidence) -- all interface designs derived from actual code
- [Vosk API documentation](https://alphacephei.com/vosk/) -- vocabulary/grammar support (HIGH confidence)
- [Vosk language model adaptation](https://alphacephei.com/vosk/lm) -- custom vocabulary mechanisms (HIGH confidence)
- [whisper.cpp initial_prompt discussion](https://github.com/ggml-org/whisper.cpp/discussions/348) -- vocabulary via prompt (MEDIUM confidence)
- [whisper.cpp hotwords discussion](https://github.com/ggml-org/whisper.cpp/issues/1979) -- vocabulary boosting limitations (MEDIUM confidence)
- [Google Cloud Speech-to-Text custom vocabulary](https://cloud.google.com/speech-to-text) -- PhraseSet API (HIGH confidence)
- [GTK3 Building Applications](https://docs.gtk.org/gtk3/getting_started.html) -- preferences window patterns (HIGH confidence)
