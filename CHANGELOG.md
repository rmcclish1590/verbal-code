# Changelog

All notable changes to Verbal Code are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).
Development history before this file existed is recorded as numbered slice
documents in `specs/`; the work backlog lives in Linear (issues are referenced
below as MCC-NN).

## [Unreleased]

### Security

- Transcribed text is no longer written to the logs by default — dictation
  can contain passwords or personal details, and logs persist in plaintext.
  Only character counts are logged now; set `logging.log_transcripts: true`
  to opt back in to full transcript logging. A configured log file is also
  restricted to owner-only permissions (0600) (MCC-38).

### Fixed

- An unknown `stt.engine` value (e.g. a typo like "wisper") now fails
  startup with a clear error listing the valid engines, instead of silently
  falling back to the Whisper backend (MCC-45).

- A dictation started while a tray model switch was still loading no longer
  gets its transcriber swapped out mid-session: the swap now commits under
  the dictation lock and is cancelled (with a notification) if recording
  began during the load, and the in-memory config is only modified when the
  swap actually commits (MCC-44).

- The clipboard-paste injector no longer clobbers the clipboard: non-text
  content (images, file copies) and unreadable/empty clipboards skip the
  restore instead of being replaced with an empty string, and anything the
  user copies during the paste settle window wins over the restore
  (MCC-43).

- With `stt.streaming_enabled: true` and an engine whose partials are
  revisable (Whisper/Moonshine), the streaming thread no longer runs at
  all: it re-transcribed the entire session every 1.5s — O(n²) CPU over a
  dictation — only to produce debug-log lines, since the injected text
  always came from the batch pass on release anyway. Live streaming still
  works unchanged with the vosk engine (MCC-42).

- Recordings are now capped by `audio.max_seconds` (default 300, 0 to
  disable): a toggle-mode dictation left running no longer grows the
  in-memory audio buffer without bound (~3.8 MB/min). Hitting the cap stops
  the recording with a notification and transcribes what was captured
  (MCC-41).

- Switching models from the tray or saving a hotkey no longer destroys the
  comments in config.yaml: config rewrites now round-trip through
  ruamel.yaml (new dependency), are written atomically (temp file +
  rename, so a crash can't truncate the config), and are serialized behind
  a lock so concurrent saves can't lose each other's changes (MCC-40).

- A failed injection (xdotool/ydotool/xclip error or timeout) now raises and
  surfaces the error tray state and notification instead of silently
  reporting success while the dictated text was lost. The hybrid injector
  falls back to typing when a clipboard paste fails, and a paste-keystroke
  failure leaves the dictated text on the clipboard so it can be recovered
  with a manual paste (MCC-39).

### Added

- Regression tests prove the selected transcription model survives a
  restart: the tray quick-switch's save round-trips through `load_config()`
  exactly like a fresh start would, unrelated config sections are preserved,
  and a missing config file is created on first switch. The persistence
  itself already worked (MCC-16); this closes the gap in coverage (MCC-33).

- Every completed dictation logs its hotkey-release→text-on-screen latency as
  `dictation_latency_ms=<value>` at INFO, for performance monitoring
  (MCC-30).

- Test coverage grew from 23 to 158 tests, now spanning transcriber stream
  gating and delta logic, Vosk streaming, silence trimming, audio-capture
  buffering, hotkey capture/dispatch, injector routing, config validation,
  and the app's dictation, model-switch, and live-streaming orchestration
  (MCC-25).

- Tray menu shows the active engine/model and offers a Model submenu for
  switching between installed engines' models on the fly; the choice loads in
  the background and persists to the config file (MCC-16).

- Spoken punctuation and formatting commands ("period", "comma", "question
  mark", "new line", "new paragraph", ...), with automatic capitalisation of
  sentence starts; disable with `injection.punctuation_commands: false`
  (MCC-15).

- Automatic clipboard paste for long dictations (`injection.clipboard_threshold`,
  default 100 characters): short fragments are still typed, long ones land
  instantly via the clipboard (MCC-14).

- Toggle-to-dictate mode (`hotkey.mode: "toggle"`): press the hotkey once to
  start recording and again to stop, alongside the default push-to-talk
  (MCC-13).

- Wayland support: on a Wayland session, global hotkeys are read via an evdev
  listener (requires membership in the `input` group) and injection prefers
  ydotool automatically (MCC-12).

- Live streaming injection with the Vosk engine: each utterance is typed into
  the focused window as it finalises, and hotkey release just flushes the last
  utterance — no duplicate batch pass (MCC-11).
- Modifier-only hotkey combos (e.g. Alt+Ctrl+Super): the hotkey dialog captures
  them on key release, and the listener accepts a modifier as the trigger key
  (MCC-26).
- Moonshine STT engine (`stt.engine: moonshine`) — fast English-only ASR on
  onnxruntime, no torch required.
- Energy-based silence trimming before batch transcription
  (`vad.trim_silence`, `vad.trim_threshold_db`); a silent recording now skips
  transcription entirely (MCC-7).
- Startup validation of numeric config values (sample rate, chunk size, beam
  size, batch size, injection delay, trim threshold) with errors that name the
  offending key (MCC-8).
- This changelog (MCC-17).

### Changed

- Dependencies carry upper bounds (next major version) in requirements.txt
  and pyproject.toml so an incompatible release can't break an install
  (MCC-24).

- The tray prefers the maintained AyatanaAppIndicator3 library, falling back
  to the deprecated AppIndicator3 where Ayatana isn't available; install.sh
  installs whichever the distribution ships (MCC-23).

- Audio capture stores each chunk once: the streaming consumer walks the
  session buffer with a read cursor instead of a second queue (MCC-22).

- Default whisper `beam_size` lowered from 5 to 2 — roughly half the CPU
  latency with negligible accuracy loss on short dictations; set
  `stt.whisper.beam_size: 5` to restore the old behaviour (MCC-19).

- The default hotkey is `super+alt+space` everywhere; the code fallback
  previously disagreed with config.yaml and the README (MCC-5).
- `validate_config()` runs before the `--test-audio` / `--test-transcribe` /
  `--test-inject` diagnostic modes, so a missing STT package produces the
  friendly install hint instead of a traceback (MCC-6).
- `logging.file` is sanitized before use: `~` expands, symlinks and
  directories are refused, and an unusable path degrades to console-only
  logging instead of crashing (MCC-9).
- `--test-audio` writes its WAV through `tempfile.mkstemp` instead of a fixed
  `/tmp` path (MCC-10).
- Whisper batch transcription runs through faster-whisper's
  `BatchedInferencePipeline` with the built-in Silero VAD filter; the default
  model is `distil-small.en`.

### Fixed

- A malformed saved hotkey in config.yaml (wrong types, unknown modifier
  names) now falls back to the default combo with a warning instead of
  breaking startup; saved hotkeys are validated once and used consistently
  by the listener, ready banner, and hotkey editor (MCC-32).

- Streaming thread lifecycle: stop state is initialised (shutdown previously
  raised `AttributeError`), the per-session thread is joined on dictation stop
  instead of spinning forever, and queued audio is drained on stop so the tail
  of a dictation isn't lost (MCC-11).
- Streaming loop re-transcribed the entire buffer on every audio chunk,
  growing CPU cost quadratically with utterance length (P0).
- Streaming inference ran during recording even though its output was
  discarded (P0).
- Hotkeys combining Ctrl with a letter never activated on X11 (P0).
- Clipboard injection restored the clipboard before slow applications
  processed the paste (P0).
- `injection.delay_ms` is per keystroke, not a one-time delay; the shipped
  default is now 0 and the semantics are documented (P0).
- Non-16 kHz `audio.sample_rate` with the whisper engine silently produced
  garbled transcriptions; it is now rejected at startup (P0).
- `app.stop()` leaked the streaming thread (P1).

### Removed

- The torch/torchaudio dependency (~2 GB): voice-activity detection uses
  faster-whisper's bundled ONNX Silero VAD, and `install.sh` now uninstalls
  torch from existing venvs on upgrade (MCC-18).
- `BACKLOG.md` — the backlog moved to Linear.

## [0.1.0] - 2026-08-26

Initial development, built as vertical slices (specs 00–12 in `specs/`).

### Added

- Push-to-talk dictation for Linux Mint/X11: hold a global hotkey, speak,
  release, and the transcribed text is injected into the focused window
  (slices 00–04).
- Audio capture via sounddevice with per-session buffering (slice 01).
- Whisper transcription through faster-whisper (slice 02).
- Text injection via xdotool typing simulation with clipboard-paste fallback,
  plus a ydotool injector for future Wayland use (slice 03).
- Global hotkey listener built on pynput (slice 04).
- Vosk as a lightweight alternative STT engine (slice 05).
- Streaming transcription machinery (slice 06).
- System tray indicator with status states and notifications (slice 07).
- Silero voice-activity detection integration (slice 08).
- `install.sh` guided installer, launcher script, and `--list-devices` /
  `--test-audio` / `--test-transcribe` / `--test-inject` diagnostics
  (slice 09).
- `uninstall.sh` (slice 10).
- Application menu desktop entry and icon (slice 11).
- In-app hotkey editor dialog reachable from the tray menu (slice 12).
