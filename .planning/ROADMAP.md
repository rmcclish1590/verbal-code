# Roadmap: Verbal Code

## Overview

This milestone takes verbal-code from a working prototype to a reliable daily-driver. The path starts with upgrading the recognition engine for better accuracy, then builds the data layer (config persistence and custom vocabulary), and finishes by wiring it all together with a settings UI and polished overlay widget. Three phases, each delivering a coherent capability that the next phase builds on.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Recognition Upgrade** - Upgrade Whisper.cpp to v1.8.3 with Vulkan acceleration and validate accuracy improvement
- [ ] **Phase 2: Configuration and Vocabulary** - Persist application settings and enable user-defined custom vocabulary
- [ ] **Phase 3: Settings UI and Overlay Polish** - GTK3 settings window and refined floating widget with state indicators

## Phase Details

### Phase 1: Recognition Upgrade
**Goal**: Speech recognition is noticeably more accurate and faster than current baseline
**Depends on**: Nothing (first phase)
**Requirements**: RECG-01, RECG-02
**Success Criteria** (what must be TRUE):
  1. Whisper.cpp v1.8.3 builds and loads models successfully with Vulkan iGPU acceleration enabled
  2. User can speak a test phrase and receive more accurate transcription than the current v1.7.3 baseline
  3. Initial_prompt parameter is functional and can accept vocabulary hints
**Plans**: TBD

Plans:
- [ ] 01-01: TBD
- [ ] 01-02: TBD

### Phase 2: Configuration and Vocabulary
**Goal**: User preferences persist across sessions and custom word lists improve domain-specific accuracy
**Depends on**: Phase 1
**Requirements**: CONF-01, VOCB-01, VOCB-02
**Success Criteria** (what must be TRUE):
  1. Application reads and writes settings to a JSON config file at XDG_CONFIG_HOME/verbal-code/
  2. User can define a custom word list (names, acronyms, domain terms) that persists across restarts
  3. Custom vocabulary is translated to Whisper initial_prompt format and improves recognition of listed terms
  4. Custom vocabulary is translated to Vosk grammar format when Vosk engine is active
**Plans**: TBD

Plans:
- [ ] 02-01: TBD
- [ ] 02-02: TBD

### Phase 3: Settings UI and Overlay Polish
**Goal**: Users can configure the application through a GUI and see clear visual feedback during dictation
**Depends on**: Phase 2
**Requirements**: CONF-02, CONF-03, OVRL-01, OVRL-02
**Success Criteria** (what must be TRUE):
  1. GTK3 settings window opens with tabs for engine, audio device, hotkey, and vocabulary configuration
  2. Changing a setting in the UI takes effect immediately without restarting the application
  3. Floating widget clearly shows distinct visuals for listening, idle, and processing states
  4. Widget remains compact, always-on-top, and non-intrusive during normal desktop use
**Plans**: TBD

Plans:
- [ ] 03-01: TBD
- [ ] 03-02: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Recognition Upgrade | 0/0 | Not started | - |
| 2. Configuration and Vocabulary | 0/0 | Not started | - |
| 3. Settings UI and Overlay Polish | 0/0 | Not started | - |
