# Requirements: Verbal Code

**Defined:** 2026-03-07
**Core Value:** Accurate, reliable speech recognition that makes voice input a viable daily replacement for typing

## v1 Requirements

Requirements for this refinement milestone. Each maps to roadmap phases.

### Recognition

- [x] **RECG-01**: Upgrade whisper.cpp to v1.8.3 with Vulkan iGPU acceleration and initial_prompt support
- [x] **RECG-02**: Validate recognition accuracy improvement with upgraded model

### Vocabulary

- [ ] **VOCB-01**: User can define a custom word list (names, acronyms, domain terms) stored as JSON
- [ ] **VOCB-02**: Word list is translated to each engine's native format (Whisper initial_prompt, Vosk grammar)

### Configuration

- [ ] **CONF-01**: Application settings persisted as JSON at XDG_CONFIG_HOME/verbal-code/
- [ ] **CONF-02**: GTK3 settings window with tabs for engine, audio device, hotkey, and vocabulary config
- [ ] **CONF-03**: Settings changes take effect without restarting the application

### Overlay

- [ ] **OVRL-01**: Floating widget clearly indicates listening/idle/processing state with distinct visuals
- [ ] **OVRL-02**: Widget is compact, always-on-top, and non-intrusive

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Recognition

- **RECG-03**: Multi-engine interface (unified IRecognitionEngine abstraction)
- **RECG-04**: Cloud API support (OpenAI gpt-4o-mini-transcribe via REST)
- **RECG-05**: Cloud API support (Google Cloud Speech-to-Text v2)
- **RECG-06**: Engine auto-selection based on context

### Vocabulary

- **VOCB-03**: Named domain profiles (switch vocabulary sets by context)

### Configuration

- **CONF-04**: Secure API key storage via libsecret with file fallback

### Overlay

- **OVRL-03**: Start/stop control on widget
- **OVRL-04**: Clipboard save/restore on text injection

## Out of Scope

| Feature | Reason |
|---------|--------|
| Streaming/real-time transcription | High complexity, batch-on-release is acceptable for daily use |
| LLM post-processing | Depends on multi-engine abstraction (v2) |
| Mobile app | Desktop Linux only |
| Browser extension | System-level injection covers browser text fields |
| Video/screen capture | Audio input only |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| RECG-01 | Phase 1 | Complete |
| RECG-02 | Phase 1 | Complete |
| VOCB-01 | Phase 2 | Pending |
| VOCB-02 | Phase 2 | Pending |
| CONF-01 | Phase 2 | Pending |
| CONF-02 | Phase 3 | Pending |
| CONF-03 | Phase 3 | Pending |
| OVRL-01 | Phase 3 | Pending |
| OVRL-02 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 9 total
- Mapped to phases: 9
- Unmapped: 0

---
*Requirements defined: 2026-03-07*
*Last updated: 2026-03-07 after roadmap creation*
