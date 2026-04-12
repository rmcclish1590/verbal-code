# Slice 12: Hotkey Editor Window

## Goal
Add a "Hotkeys" menu item to the system tray dropdown that opens a GTK3 window for interactively capturing and saving a new push-to-talk hotkey combo. On save, the config file is rewritten and the `HotkeyListener` is restarted with the new binding.

## Depends On
- Slice 4 (hotkey push-to-talk)
- Slice 7 (system tray indicator)

## Acceptance Criteria
- [ ] Tray dropdown menu includes a "Hotkeys..." item between the status label and "Quit Verbal Code"
- [ ] Clicking "Hotkeys..." opens a GTK3 window titled "Verbal Code — Hotkeys"
- [ ] Window displays the current hotkey combo (e.g. "Super+Alt+Space")
- [ ] Window has a "Record" button that enters interactive key capture mode
- [ ] Clicking "Record" pauses the global `HotkeyListener` so the combo does not trigger dictation
- [ ] During recording, the window captures modifier keys (ctrl, alt, super, shift) via GTK `key-press-event`
- [ ] During recording, pressing a non-modifier key finalizes the capture and exits recording mode
- [ ] The captured combo is displayed in the window (e.g. "New hotkey: Ctrl+Alt+D")
- [ ] Modifier keys are deduplicated (pressing both Ctrl_L and Ctrl_R counts as one "ctrl")
- [ ] Pressing only modifiers without a non-modifier key does not finalize — recording continues
- [ ] "Save" button writes the new combo to the config YAML file, preserving all other config sections
- [ ] "Save" triggers `HotkeyListener` to be stopped and recreated with the new combo
- [ ] A desktop notification confirms the hotkey change after save
- [ ] "Cancel" button closes the window without saving
- [ ] Closing the window via the window manager X button behaves like Cancel
- [ ] If recording is active when the window is closed, the global `HotkeyListener` is resumed
- [ ] If no config file exists, Save creates `~/.config/verbal-code/config.yaml` with the hotkey section
- [ ] Window appears centered and above other windows

## Files to Create/Modify
- CREATE: `verbal_code/hotkey_editor.py` — GTK window class for hotkey capture and config save
- MODIFY: `verbal_code/tray.py` — add "Hotkeys..." menu item and `on_hotkeys` callback
- MODIFY: `verbal_code/app.py` — add `resolve_config_path()`, wire hotkey editor callbacks, pass config path to `VerbalCode`
- MODIFY: `install.sh` — no new dependencies required (GTK3, PyYAML, and pynput are already installed); verify `python3-gi` and `gir1.2-appindicator3-0.1` remain listed in `APT_PACKAGES`
- MODIFY: `uninstall.sh` — no new installed files to clean up (hotkey editor is runtime-only, config is already removed by the existing `~/.config/verbal-code` cleanup)

## Technical Notes
- Use GTK `key-press-event` signals on the window for key capture (not a temporary pynput listener) — avoids competing with the global listener and is simpler since the GTK window is already focused
- Map Gdk keyval names to config strings: `Control_L`/`Control_R` → `"ctrl"`, `Alt_L`/`Alt_R` → `"alt"`, `Super_L`/`Super_R` → `"super"`, `Shift_L`/`Shift_R` → `"shift"`
- Map special Gdk keys to config strings: `space` → `"space"`, `Return` → `"enter"`, `Tab` → `"tab"`, `BackSpace` → `"backspace"`, `Escape` → `"esc"`
- For regular letter keys, use `Gdk.keyval_name(event.keyval).lower()` directly as the config key string
- Use `yaml.safe_load` + `yaml.safe_dump` to rewrite config (no new dependency needed) — note that `safe_dump` sorts keys alphabetically, which reorders sections but keeps the file valid
- If `config_path` is `None` (running with defaults, no file), fall back to `~/.config/verbal-code/config.yaml` and create the directory with `os.makedirs(exist_ok=True)`
- On save, create a new `HotkeyListener` instance rather than mutating the existing one — the trigger key and modifier sets are set in the constructor with no `reconfigure()` method
- All GTK operations must happen on the GTK thread; the menu item `activate` signal already fires on the GTK thread, so the editor window can be created directly in the callback
- Connect the window `destroy` signal to resume the global listener if recording was active when the window was closed
- `HotkeyListener.stop()` and `HotkeyListener.start()` are safe to call from the GTK thread

## Window Layout
```
+---------------------------------------+
| Current hotkey: Super+Alt+Space       |  <- Gtk.Label
|                                       |
| New hotkey: [not set]                 |  <- Gtk.Label (updated during capture)
|                                       |
| [ Record ]  [ Save ]  [ Cancel ]     |  <- Gtk.ButtonBox
+---------------------------------------+
```
- Window size: 400x180, centered, keep-above
- "Save" button disabled until a new combo is captured
- "Record" button label changes to "Recording..." and becomes insensitive during capture

## Edge Cases to Handle
- User presses only modifiers without a non-modifier key — recording continues, label shows accumulated modifiers
- User closes window during recording — resume the global `HotkeyListener` before destroying
- Escape key as a hotkey trigger — if the user wants Escape as the trigger key, it should work (map via `_SPECIAL_GDK_KEYS`); do not let Escape close the window during recording
- Double-click on "Hotkeys..." while window is already open — either focus the existing window or ignore
- Config file has unexpected structure — `setdefault("hotkey", {})` before writing to avoid KeyError

## Test It
```bash
python -m verbal_code
# Right-click tray icon — "Hotkeys..." should appear in the menu
# Click "Hotkeys..." — editor window opens showing current combo
# Click "Record" — button changes to "Recording..."
# Press Ctrl+Alt+D — window shows "New hotkey: Alt+Ctrl+D"
# Click "Save" — window closes, notification confirms change
# Hold Ctrl+Alt+D — dictation should start (new hotkey works)
# Old hotkey combo should no longer trigger dictation

# Verify config was updated:
cat ~/.config/verbal-code/config.yaml | grep -A3 hotkey

# Click "Hotkeys..." again — current hotkey should show the new combo
# Click "Record", press a combo, click "Cancel" — no change saved
# Verify old hotkey still works after cancel
```
