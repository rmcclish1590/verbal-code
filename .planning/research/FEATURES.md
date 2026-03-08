# Feature Landscape

**Domain:** Linux system-wide voice-to-text dictation
**Researched:** 2026-03-07

## Table Stakes

Features users expect. Missing = product feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Push-to-talk hotkey activation | Every dictation tool uses this as the primary interaction model. Users hold or toggle a hotkey to record. | Low | **Already built.** X11 (XCB) and Wayland (D-Bus GlobalShortcuts). |
| System-wide text injection | Dictated text must appear wherever the cursor is -- any app, any text field. This is the core promise. | Low | **Already built.** xdotool (X11), ydotool/wl-clipboard (Wayland). |
| Automatic punctuation | Users will not say "period" and "comma" manually. Modern dictation tools insert punctuation from context. Wispr Flow, Apple Dictation, Windows Voice Typing, and Google Gboard all do this automatically. Without it, output requires manual cleanup after every utterance. | Med | Whisper models handle this natively when using larger models (small+). Vosk does not. This is a model-quality concern more than a feature to build -- select models that punctuate. |
| Reasonable accuracy (>90% on clear speech) | If accuracy is below 90%, users spend more time correcting than they saved by dictating. The bar set by Wispr Flow and Apple Dictation is 95%+. | High | **Primary pain point per PROJECT.md.** Larger Whisper models (medium/large) or cloud APIs needed. |
| Visual recording indicator | Users must know when the mic is hot. Every tool shows some indicator -- floating widget, tray icon, or overlay. Without it, users dictate into the void or accidentally record. | Low | **Already built** (GTK3 overlay). Needs polish per PROJECT.md. |
| Offline/local operation | Linux power users strongly prefer local processing. Every major Linux dictation tool (nerd-dictation, VOXD, OpenWhispr, Vocalinux) emphasizes offline-first. Cloud-only is a dealbreaker for this audience. | Low | **Already built** with Whisper.cpp and Vosk. |
| Multi-language support | Whisper supports 99+ languages. Users expect to select their language. Single-language-only feels artificially limited. | Low | Whisper.cpp handles this via model selection. Expose a language setting in config. |
| Configurable hotkey | Users have different keyboard layouts and preferences. Hardcoded hotkeys conflict with other apps. | Med | Hotkey infrastructure exists. Need UI or config file to let users change the binding. |
| Audio device selection | Users with multiple mics (headset, USB, built-in) need to pick which one. PipeWire exposes multiple sources. | Med | PipeWire audio service exists. Add device enumeration and selection. |

## Differentiators

Features that set product apart. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Multiple recognition engine support | Different engines excel at different tasks: Whisper for accuracy, Vosk for speed/low-resource, cloud APIs (OpenAI Whisper API, Google Speech) for maximum accuracy. Letting users switch engines is rare in Linux tools -- only OpenWhispr offers local+cloud. | High | Service interface (`IRecognitionService`) already abstracts this. Vosk and Whisper backends exist. Add cloud API backends. Engine switching is the integration work. |
| LLM post-processing / AI text cleanup | VOXD and OpenWhispr use llama.cpp or cloud LLMs to reformat, correct grammar, and restructure dictated text. Transforms raw speech into polished prose. This is the single biggest differentiator in 2025-2026 dictation tools. | Med | `IRefinementService` interface already exists. Build an LLM refinement backend (local via llama.cpp or cloud API). |
| Custom vocabulary / prompt biasing | Technical users dictate jargon, code identifiers, project names. Whisper supports an `initial_prompt` parameter (up to 224 tokens) that biases recognition toward specific words. Users supply a word list; the app feeds it as context. | Med | Whisper.cpp supports prompt injection. Limited to 224 tokens per segment. Effective for small domain-specific word lists (names, acronyms, product names). |
| Streaming/incremental transcription | VOXD shows text appearing as you speak (3-second overlapping chunks). Provides immediate feedback vs waiting until recording stops. Makes long dictation sessions feel responsive. | High | Requires chunked audio processing pipeline. Whisper.cpp processes fixed segments; need overlapping window approach. Significant architecture change to audio pipeline. |
| Voice Activity Detection (VAD) | Hands-free continuous dictation -- no hotkey needed, app detects when you start/stop speaking. VOXD offers this in beta ("--flux" mode). Useful for accessibility and long-form dictation. | High | Silero VAD is the standard model. Requires always-on audio monitoring with low CPU overhead. Privacy implications (always listening). Best as opt-in mode alongside push-to-talk. |
| Settings UI (native GTK) | A GUI for configuring engine, hotkey, audio device, language, and preferences. Most Linux dictation tools are CLI-only (nerd-dictation) or Electron-based (OpenWhispr). A native GTK settings window is lightweight and fits the C++ stack. | Med | GTK3 already in use for overlay. Settings window is standard GTK form layout. Needs a config persistence layer (JSON or TOML file). |
| Polished floating widget | Compact, always-on-top indicator showing: listening state (idle/recording/processing), audio level meter, last transcription preview. Microsoft moved to a minimal in-keyboard indicator; Superwhisper offers mini/full modes. A well-designed widget makes the tool feel professional. | Med | GTK3 overlay exists. Refine to show state transitions, audio level visualization, and mini/expanded modes. |
| Auto-add to dictionary | Wispr Flow monitors corrections: if user edits a transcribed word, the correction is automatically saved to a personal dictionary for future sessions. Reduces friction of vocabulary management. | Med | Requires clipboard/text-field monitoring after injection. Complex on Linux (X11 selection tracking is fragile, Wayland has no equivalent). Consider simplified manual-add-only approach first. |
| Clipboard restoration | After injecting text via clipboard paste, restore the user's previous clipboard contents. Superwhisper and Wispr Flow both do this. Without it, dictation clobbers whatever the user had copied. | Low | Save clipboard before injection, restore after. Straightforward with xclip/wl-clipboard. |
| Model management UI | Download, select, and manage Whisper models (tiny/base/small/medium/large) from the settings UI. Show model size, expected accuracy, and resource requirements. | Med | `ModelManager` class already exists. Add download progress, model switching, and disk usage display to settings UI. |

## Anti-Features

Features to explicitly NOT build.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| Full transcription editor window | PROJECT.md explicitly scopes this out. A built-in text editor competes with the user's actual text field. The value is injecting into *their* app, not providing another app. | Keep the widget minimal. Show a brief preview of last transcription, not a full editing surface. |
| Voice commands for text editing | "Select all", "bold that", "delete last sentence" -- these require deep integration with the target application's editing model. Extremely complex on Linux where there is no universal accessibility API like macOS. Fragile and unreliable. | Focus on accurate transcription and injection. Let users edit in their target app with keyboard/mouse. |
| Speaker diarization | Identifying who is speaking is a transcription/meeting feature, not a dictation feature. Single-user dictation does not benefit from it. | Out of scope. Single speaker assumed. |
| Browser extension | System-level text injection already covers browser text fields. A browser extension adds maintenance burden across Chrome/Firefox/etc. for no additional capability. | Rely on system-wide injection via xdotool/ydotool. |
| Mobile companion app | Linux desktop only per PROJECT.md. Mobile adds a completely separate platform. | Stay focused on Linux desktop. |
| Always-on background transcription / meeting recording | Different product category (Otter, Granola). Requires continuous recording, storage, and a transcript viewer. Not dictation. | Keep the tool as an input method, not a recording tool. |
| Electron-based UI | OpenWhispr uses Electron. For a C++ application already using GTK3, adding Electron bloats memory and startup time. GTK3 is the right choice. | Use native GTK3 for all UI. |
| Fine-tuning Whisper models | Requires ML infrastructure, training data pipelines, GPU compute. Overkill for a desktop dictation tool. Prompt biasing and custom vocabulary cover the practical need. | Use `initial_prompt` for vocabulary biasing. Recommend users select larger models for better accuracy. |

## Feature Dependencies

```
Audio Device Selection --> Settings UI (needs UI to expose device list)
Engine Switching --> Multiple Recognition Engines (need engines before switching)
Engine Switching --> Settings UI (needs UI to select engine)
Custom Vocabulary --> Settings UI (needs UI to manage word list)
Custom Vocabulary --> Config Persistence (needs storage for word lists)
Model Management UI --> Settings UI (lives inside settings)
LLM Post-Processing --> Multiple Recognition Engines (refinement is post-engine)
LLM Post-Processing --> Config Persistence (API keys, model selection)
Settings UI --> Config Persistence (all settings need storage)
Streaming Transcription --> Audio Pipeline Changes (chunked processing)
VAD --> Streaming Transcription (VAD feeds continuous audio to recognition)
Polished Widget --> Visual Recording Indicator (refinement of existing)
Clipboard Restoration --> Text Injection (enhancement to injection pipeline)
```

## MVP Recommendation

For the next milestone (improving daily-driver reliability), prioritize:

1. **Accuracy improvement** (table stakes) -- Larger Whisper models, cloud API option. This is the stated primary pain point. Nothing else matters if transcription output is unreliable.
2. **Config persistence layer** (enabler) -- JSON/TOML config file for settings. Every subsequent feature depends on storing user preferences.
3. **Settings UI** (table stakes for non-CLI users) -- GTK3 window for engine selection, audio device, hotkey, language. Unlocks all configuration-dependent features.
4. **Multiple recognition engines with switching** (differentiator) -- Cloud API backend for users who want maximum accuracy. Engine selection in settings.
5. **Custom vocabulary / prompt biasing** (differentiator) -- Word list that feeds Whisper's `initial_prompt`. High impact for technical users with low implementation cost.
6. **Polished floating widget** (table stakes) -- State indicators, mini mode, audio level. Makes the tool feel production-ready.
7. **Clipboard restoration** (table stakes) -- Low effort, high polish. Users notice when their clipboard is clobbered.

Defer:
- **Streaming transcription**: High complexity, architecture changes. Current batch-on-release model is acceptable for most dictation (sentences/paragraphs). Revisit when core accuracy is solid.
- **VAD / hands-free mode**: Requires streaming as prerequisite, plus always-on audio monitoring. Niche use case. Ship as future enhancement.
- **LLM post-processing**: Valuable but depends on engine infrastructure being solid first. Add after multi-engine support is stable.
- **Auto-add to dictionary**: Clipboard monitoring on Linux is fragile. Manual vocabulary management is sufficient initially.

## Sources

- [OpenWhispr GitHub](https://github.com/OpenWhispr/openwhispr) -- Features, AI agent mode, multi-engine support
- [VOXD GitHub](https://github.com/jakovius/voxd) -- VAD mode, streaming transcription, llama.cpp post-processing
- [Nerd Dictation GitHub](https://github.com/ideasman42/nerd-dictation) -- CLI-first minimal approach, Vosk-based
- [Wispr Flow review](https://wisprflow.ai/post/wispr-flow-for-seamless-communication) -- Custom vocabulary, auto-dictionary, settings patterns
- [Superwhisper advanced settings](https://superwhisper.com/docs/get-started/settings-advanced) -- Settings UI reference (recording window, clipboard restore, mini mode)
- [Whisper prompt engineering](https://medium.com/axinc-ai/prompt-engineering-in-whisper-6bb18003562d) -- Custom vocabulary via initial_prompt, 224-token limit
- [Whisper.cpp custom vocabulary discussion](https://github.com/ggml-org/whisper.cpp/discussions/602) -- Community approaches to vocabulary biasing
- [Contextual biasing for Whisper](https://arxiv.org/html/2410.18363v1) -- Neural-symbolic prefix tree for vocabulary guidance
- [AssemblyAI: Real-time vs batch transcription](https://www.assemblyai.com/blog/real-time-vs-batch-transcription) -- Streaming UX tradeoffs
- [Zapier: Best dictation software 2026](https://zapier.com/blog/best-text-dictation-software/) -- Feature comparison across tools
- [TechCrunch: Best AI dictation apps 2025](https://techcrunch.com/2025/12/30/the-best-ai-powered-dictation-apps-of-2025/) -- Market landscape
