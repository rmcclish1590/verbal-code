# Slice 3: Text Injection into Focused Window

## Goal
Build `verbal_code/injector.py` — injects text into whatever window is currently focused. Default method is `xdotool type` on X11. Include clipboard fallback and a `--test-inject` flag that types a test sentence after a 3-second delay (so you can click into a text field).

## Depends On
- Slice 0 (config loading)

## Acceptance Criteria
- [ ] `InjectorBase` ABC with `inject(text: str)` and `is_available() -> bool`
- [ ] `XdotoolInjector` — runs `xdotool type --clearmodifiers -- <text>`, configurable `typing_delay_ms`
- [ ] `ClipboardInjector` — saves clipboard, sets text via `xclip`, simulates `ctrl+v` via xdotool, restores clipboard
- [ ] `YdotoolInjector` — runs `ydotool type -- <text>` (for future Wayland)
- [ ] `create_injector(config) -> InjectorBase` factory with automatic fallback chain: preferred method → xdotool → clipboard → ydotool
- [ ] `TextProcessor` class with `process(text) -> str` that handles: auto-capitalize first word, add trailing space. Has `reset()` for new sessions.
- [ ] `--test-inject` CLI flag: prints "Click into a text field... injecting in 3 seconds", waits, then injects "Hello from Verbal Code! This is a test."
- [ ] All subprocess calls have `timeout=10`, capture stderr, log errors
- [ ] `--clearmodifiers` flag on xdotool to prevent hotkey modifiers from mixing into the typed text

## Files to Create/Modify
- CREATE: `verbal_code/injector.py`
- MODIFY: `verbal_code/app.py` — add `--test-inject` flag
- System deps: `xdotool`, `xclip` (document in output if missing)

## Technical Notes
- `xdotool type --clearmodifiers -- "text"` is critical — without `--clearmodifiers`, held Ctrl/Alt keys will modify the typed characters
- `subprocess.run([...], capture_output=True, text=True, timeout=10)` — never block forever
- Clipboard save/restore: `xclip -selection clipboard -o` to get, pipe text into `xclip -selection clipboard` to set
- `shutil.which("xdotool")` to check availability

## Test It
```bash
sudo apt install xdotool xclip  # if not installed
python -m verbal_code --test-inject
# Click into a text editor/terminal within 3 seconds
# "Hello from Verbal Code! This is a test." should appear
```
