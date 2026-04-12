# Slice 4: Global Hotkey Push-to-Talk (MVP)

## Goal
Build `verbal_code/hotkeys.py` and wire everything together in `app.py` for the core push-to-talk loop: hold Ctrl+Super+Alt+D → record audio → release → transcribe → inject text into focused window. **This is the MVP.**

## Depends On
- Slice 1 (audio capture)
- Slice 2 (whisper transcription)
- Slice 3 (text injection)

## Acceptance Criteria
- [ ] `HotkeyListener` class with `start()`, `stop()`, `is_active` property
- [ ] Constructor takes `modifiers: list[str]`, `key: str`, `on_activate: Callable`, `on_deactivate: Callable`
- [ ] Modifier mapping: "ctrl" → Key.ctrl_l, "alt" → Key.alt_l, "shift" → Key.shift_l, "super"/"meta" → Key.cmd
- [ ] Normalizes left/right key variants (ctrl_l and ctrl_r both match "ctrl")
- [ ] `on_activate` fires when ALL modifiers + trigger key are held simultaneously
- [ ] `on_deactivate` fires when ANY part of the combo is released
- [ ] Listener runs in a daemon thread via `pynput.keyboard.Listener`
- [ ] `VerbalCode` class in `app.py` orchestrates the full lifecycle:
  - `_on_dictation_start()`: reset transcriber, start audio capture
  - `_on_dictation_stop()`: stop audio, run `transcribe_batch()` on full audio, process text, inject
  - Skip transcription if audio < 0.3 seconds
- [ ] Blocks on main thread with sleep loop, clean shutdown on SIGINT/SIGTERM
- [ ] Logs: "Dictation started", "Dictation stopped", audio duration, transcribed text, injection confirmation
- [ ] Config: `hotkey.modifiers` (default `["ctrl", "super", "alt"]`), `hotkey.key` (default `"d"`)

## Files to Create/Modify
- CREATE: `verbal_code/hotkeys.py`
- MODIFY: `verbal_code/app.py` — add `VerbalCode` class, wire all components
- MODIFY: `requirements.txt` — add `pynput>=1.7.6`

## Technical Notes
- pynput's `keyboard.Listener` uses X11 RECORD extension on Linux — works globally across all windows
- The `_on_press`/`_on_release` callbacks track modifier state in a `set()` and check if the full combo is active
- Key comparison gotcha: pynput sometimes gives `KeyCode(char='d')` and sometimes `KeyCode(vk=...)` — compare `.char` attribute for letter keys
- `--clearmodifiers` on xdotool is essential here since Ctrl+Super+Alt will still be held when injection happens right after release — add a tiny delay (50ms) before injecting, or rely on `--clearmodifiers`
- Thread safety: dictation start/stop should be guarded by a lock to prevent double-activation

## Test It
```bash
pip install pynput
python -m verbal_code
# Hold Ctrl+Super+Alt+D, speak, release
# Text should appear in the focused window
# Ctrl+C to exit
```

## Edge Cases to Handle
- Double-press (user presses hotkey while already recording) — ignore
- Very short press (<0.3s) — skip transcription, log "too short"
- Transcription returns empty string — log "no speech detected", don't inject
