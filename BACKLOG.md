# Verbal Code — Backlog

Compiled 2026-08-27 from the `specs/` slice documents (the project's de-facto change
log — there is no CHANGELOG.md yet), unchecked spec acceptance criteria, the agent
audit notes in `.claude/agent-memory/`, and a fresh code review.

Provenance tags: `(spec-NN)` = from a spec slice, `(audit)` = from prior
security/refactor audits, `(review)` = found in this code review.

---

## P0 — Bugs (all fixed 2026-08-27)

- [x] **Streaming loop re-transcribes the entire buffer on every audio chunk** `(review)`
  `transcriber.py:127` — `_stream_samples` is never reduced after the 1.5 s gate is
  passed, and `_stream_buffer` is never trimmed. After the first 1.5 s of a dictation,
  *every* ~64 ms chunk triggers a full Whisper inference over the whole accumulated
  session. CPU cost grows quadratically with utterance length. Fix: only transcribe
  when `_stream_samples - _last_transcribed_samples >= interval`, or trim the buffer.

- [x] **Streaming inference runs even though its output is discarded** `(review)`
  `app.py:283–287` — live injection of partial results is commented out, but
  `transcribe_stream()` still runs continuously during recording. Combined with the
  bug above, the app burns a full STT inference pipeline per chunk for nothing.
  Fix: skip the transcriber call entirely (VAD gating can stay) unless live
  injection is enabled; add a `stt.streaming_enabled` config flag.

- [x] **Hotkeys using `ctrl` + a letter never activate** `(review)`
  `hotkeys.py:_normalize_key` — with Ctrl held, pynput on X11 reports
  `KeyCode.char` as a control character (`'\x04'` for `d`), which is truthy, so the
  `vk` fallback is never reached and `'\x04' != 'd'`. The *code-default* hotkey
  (`ctrl+super+alt+d`, `app.py:165`) is therefore dead when no config file exists.
  Fix: when required modifiers include ctrl, normalize via `key.vk` before `key.char`.

- [x] **`VoiceActivityDetector.flush()` is never called** `(review)` `(spec-08)`
  `vad.py:124` — speech still buffered in the VAD when the hotkey is released is
  silently dropped in the streaming path. Call `flush()` from `_on_dictation_stop()`
  (or when the streaming loop exits).

- [x] **Clipboard injector race: clipboard restored before the paste lands** `(review)`
  `injector.py:62–67` — Ctrl+V is synthesized and the old clipboard is restored
  immediately; slow apps process the paste after restoration and paste the *old*
  content. Also, the `xclip` write's return code is never checked. Fix: small
  settle delay (or `xdotool key --sync`) before restore; check the write succeeded.

- [x] **`delay_ms: 50` means 50 ms per keystroke, not a one-time delay** `(review)`
  `injector.py:36` + shipped `config.yaml` — xdotool `--delay` is inter-keystroke; a
  200-char dictation takes ~10 s to appear. README describes it as an injection
  delay. Fix: default to 0–12 ms, rename or document the semantics, and consider
  auto-switching to clipboard paste for long texts.

- [x] **Non-16 kHz `audio.sample_rate` silently produces garbage with Whisper** `(review)`
  faster-whisper assumes 16 kHz for raw numpy input. Setting `audio.sample_rate:
  48000` breaks transcription with no warning. Fix: validate/resample, or pin
  capture at 16 kHz and drop the knob.

## P1 — Correctness / robustness

- [x] **`app.stop()` leaks the streaming thread** (fixed 2026-08-27) `(review)` — it never sets
  `_stream_stop` nor joins `_stream_thread`; only `capture.stop()` is called.
- [ ] **Default hotkey inconsistency** `(review)` — code default is
  `ctrl+super+alt+d` (`app.py:165,202`), config.yaml and README say `super+alt+space`.
  Pick one source of truth (module-level DEFAULTS dict).
- [ ] **`--test-transcribe`/`--test-inject` run before `validate_config()`** `(review)`
  — a missing STT package yields a raw traceback instead of the friendly install hint.
- [ ] **VAD batch-path trimming never implemented** `(spec-08, unchecked item)` —
  "Integrated into `_on_dictation_stop()`: optionally trim silence from start/end of
  full audio before batch transcription." Currently batch audio is raw capture.
  (Note: `vad_filter=True` in faster-whisper already covers Whisper; Vosk batch gets
  no trimming at all.)
- [ ] **No validation of numeric config values** `(audit)` — `sample_rate`,
  `chunk_size`, `beam_size`, `vad.threshold` accepted unchecked; nonsense values
  cause crashes or resource exhaustion.
- [ ] **`logging.file` path used unvalidated in `FileHandler`** `(audit)` — restrict
  to a sane location or at least expanduser + parent-dir check.
- [ ] **`/tmp/verbal_code_test.wav` fixed path** `(audit)` — symlink risk; use
  `tempfile.mkstemp`.
- [x] **Unused import** `(review)` — fixed 2026-08-27. — `Callable` in `injector.py`; run
  `ruff check` in CI (config exists in pyproject but nothing enforces it).

## P2 — Features

- [ ] **Live streaming injection** `(spec-06 intent)` — the feature the streaming
  machinery was built for is disabled (commented out). Needs delta-injection with
  correction handling (Whisper revises earlier words; naive append will duplicate).
  Vosk's final-utterance stream is the easier first target.
- [ ] **Wayland support** `(spec-03: ydotool "for future Wayland")` — the ydotool
  injector exists, but pynput hotkeys are X11-only, so the app doesn't actually work
  on Wayland. Options: `evdev` listener (input group) or XDG desktop portal
  GlobalShortcuts.
- [ ] **Toggle-to-dictate mode** — press once to start, again to stop, alongside
  push-to-talk; long dictations without holding a chord.
- [ ] **Auto clipboard injection for long text** — typing simulation for short
  fragments, paste for long ones (also mitigates the delay_ms issue).
- [ ] **Punctuation/formatting commands** — "new line", "period", etc. in
  `TextProcessor`.
- [ ] **Tray: engine/model display and quick model switch** — the tray menu has only
  status, Hotkeys…, Quit.
- [ ] **CHANGELOG.md** — start one; the specs directory currently serves this role
  implicitly.

## P3 — Performance / dependency improvements

- [ ] **Drop the torch dependency for VAD (~2 GB → ~40 MB)** — faster-whisper already
  bundles Silero VAD via onnxruntime (`vad_filter=True` is passed in both batch and
  stream calls, so VAD runs twice today). Either rely on the built-in filter, or
  load the `silero-vad` package in ONNX mode (`load_silero_vad(onnx=True)`) so the
  pre-gate works without torch. Update install.sh + README ("requires torch" note).
- [ ] **Lower default `beam_size` for dictation** — 5 → 1–2 roughly halves latency
  on CPU with negligible accuracy loss on short utterances; keep 5 as an opt-in.
- [ ] **Offer `large-v3-turbo` / `distil-small.en` models** — faster-whisper 1.2
  supports turbo; much better speed/accuracy trade-off than base for GPU-less use.
- [ ] **Evaluate sherpa-onnx as the streaming backend** — streaming Zipformer models
  give true partial results with better accuracy than vosk-small, ONNX runtime only,
  actively maintained; would make live injection practical.
- [ ] **Single audio buffer** — capture currently stores every chunk twice (queue +
  `_session_chunks`); harmless at dictation lengths but easy to fold into one.
- [ ] **Migrate tray to Ayatana AppIndicator** — `AppIndicator3 0.1` is deprecated;
  Mint/modern Debian ship `gir1.2-ayatanaappindicator3-0.1`. Fall back between the
  two at import time (or consider `pystray` to drop the GTK dependency).
- [ ] **Pin dependencies** `(audit)` — `>=` lower bounds only in requirements.txt /
  pyproject.toml; add upper bounds or a lock/constraints file.
- [ ] **Test coverage** — only config/hotkey-normalize/injector-text tests exist;
  no tests for transcriber delta logic, VAD state machine, audio capture, or the
  app orchestration (the P0 streaming bug would have been caught by a
  transcriber-stream test).

## Stale audit notes (verified fixed — no action)

- notify-send `--` separator: present in `tray.py:165`.
- `torch.hub.load(trust_repo=True)`: no longer used; VAD loads via the `silero-vad`
  pip package.
