# Verbal Code

## What This Is

A system-wide voice-to-text desktop application for Linux that captures audio input, translates it into written text, and injects the result into any active text field. Think dictation that works everywhere — any app, any text box, activated by hotkey.

## Core Value

Accurate, reliable speech recognition that makes voice input a viable daily replacement for typing in regular workflows.

## Requirements

### Validated

- ✓ Audio capture via PipeWire — existing
- ✓ Speech recognition via Whisper.cpp — existing
- ✓ Text injection via xdotool (X11) and ydotool/wl-clipboard (Wayland) — existing
- ✓ Hotkey activation for X11 (XCB) and Wayland (D-Bus GlobalShortcuts) — existing
- ✓ Runtime X11/Wayland session detection — existing
- ✓ Basic floating overlay window (GTK3) — existing

### Active

- [ ] Improve general speech recognition accuracy (core priority)
- [ ] Support multiple recognition engines (Whisper.cpp, Vosk, cloud APIs like Google/OpenAI)
- [ ] Engine switching — user can select which engine to use
- [ ] Custom vocabulary support — user-defined words and phrases for better domain accuracy
- [ ] Refined floating widget — compact, always-on-top indicator showing listening state and status
- [ ] Settings UI — native GTK window for configuring hotkeys, engine selection, audio device, and preferences
- [ ] Polish and harden existing features for daily-driver reliability

### Out of Scope

- Mobile app — desktop Linux only
- Full transcription window with live text display — widget stays minimal
- Video/screen capture integration — audio input only
- Browser extension — system-level injection covers browser text fields

## Context

The codebase is a C++17/20 application built with CMake. It has ~50 source files across 7 modules (core, audio, recognition, injection, ipc, app, hotkey). 69 tests pass. The app already works end-to-end: hotkey triggers recording, Whisper.cpp transcribes, text is injected. However, general speech recognition accuracy is the primary pain point — the current Whisper.cpp integration doesn't produce reliable enough output for daily use. The overlay exists but needs refinement into a polished floating widget. No settings UI exists yet.

Key existing infrastructure:
- Service-oriented architecture with abstract interfaces (IAudioService, IRecognitionService, etc.)
- Wayland and X11 backends for hotkeys and injection
- GTK3 overlay window with Wayland-aware positioning
- PipeWire audio capture
- Whisper.cpp and Vosk recognition backends

## Constraints

- **Platform**: Linux only (X11 and Wayland)
- **Language**: C++17 minimum, C++20 preferred
- **Build**: CMake 3.22+
- **UI toolkit**: GTK3 (already in use)
- **Quality bar**: Must be reliable enough for daily use as a typing replacement

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Allow cloud recognition APIs | User prioritizes accuracy over privacy constraints | — Pending |
| GTK3 for settings UI | Already using GTK3 for overlay, keeps dependency consistent | — Pending |
| Multiple engine support | Different engines excel at different tasks; user choice maximizes quality | — Pending |

---
*Last updated: 2026-03-07 after initialization*
