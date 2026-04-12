# Slice 7: System Tray Indicator

## Goal
Build `verbal_code/tray.py` — a system tray icon that shows Verbal Code's current state (idle/listening/processing) with color-coded icons and a right-click menu. Integrates with Linux Mint's Cinnamon panel via AppIndicator3.

## Depends On
- Slice 4 (push-to-talk MVP, for state change hooks)

## Acceptance Criteria
- [ ] `TrayState` enum: IDLE, LISTENING, PROCESSING, ERROR
- [ ] Inline SVG icons for each state (no external icon files needed):
  - IDLE: gray mic icon
  - LISTENING: red mic icon (recording)
  - PROCESSING: yellow mic icon (transcribing)
  - ERROR: gray with red X
- [ ] SVGs written to `~/.cache/verbal-code/icons/` on startup
- [ ] `SystemTray` class with `start()`, `stop()`, `set_state(TrayState)`, `notify(title, msg)`
- [ ] `set_state()` is thread-safe (uses `GLib.idle_add()` to update from any thread)
- [ ] Right-click menu: status line (non-clickable), separator, "Quit Verbal Code"
- [ ] `notify()` sends desktop notifications via `notify-send`
- [ ] GTK main loop runs in a daemon background thread
- [ ] Graceful degradation: if GTK/AppIndicator not available, log warning and continue without tray
- [ ] Wired into `app.py`: LISTENING on dictation start, PROCESSING on dictation stop, IDLE after injection
- [ ] Config: `tray.enabled`, `tray.notifications`

## Files to Create/Modify
- CREATE: `verbal_code/tray.py`
- MODIFY: `verbal_code/app.py` — instantiate SystemTray, call `set_state()` at lifecycle points
- System deps: `python3-gi`, `gir1.2-appindicator3-0.1`, `libnotify-bin`

## Technical Notes
- `gi.require_version("Gtk", "3.0")` and `gi.require_version("AppIndicator3", "0.1")` before importing
- `AppIndicator3.Indicator.new("verbal-code", icon_name, CATEGORY)` — set `set_icon_theme_path()` to the cache dir
- GTK must run in its own thread: `threading.Thread(target=Gtk.main, daemon=True)`
- `GLib.idle_add(callback)` schedules work on the GTK thread from other threads
- `Gtk.main_quit()` to stop the GTK loop
- Wrap all GTK imports in try/except — PyGObject may not be installed

## Test It
```bash
sudo apt install python3-gi gir1.2-appindicator3-0.1 libnotify-bin
python -m verbal_code
# Tray icon should appear in Cinnamon panel
# Hold hotkey — icon turns red
# Release — icon turns yellow briefly, then gray
# Right-click — menu with Quit option
```
