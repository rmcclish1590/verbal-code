# Slice 9: Install Script, Error Handling & Polish

## Goal
Create `install.sh` for one-command setup on Linux Mint, add robust error handling throughout, validate config on startup, and write the README. This is the final polish to make Verbal Code installable and usable by someone who just cloned the repo.

## Depends On
- All previous slices (this is the final slice)

## Acceptance Criteria

### install.sh
- [ ] Checks Python 3.10+ is installed
- [ ] Installs system deps via apt: `xdotool`, `xclip`, `libportaudio2`, `portaudio19-dev`, `python3-gi`, `gir1.2-appindicator3-0.1`, `libnotify-bin`
- [ ] Only installs packages not already present (checks with `dpkg -s`)
- [ ] Creates Python venv at `~/.local/share/verbal-code/venv` with `--system-site-packages` (for PyGObject)
- [ ] Prompts user to choose STT engine: faster-whisper, vosk, or both
- [ ] Installs the verbal-code package in editable mode (`pip install -e .`)
- [ ] Copies `config.yaml` to `~/.config/verbal-code/config.yaml` if not exists
- [ ] Creates launcher script at `~/.local/bin/verbal-code` that activates venv and runs `python -m verbal_code`
- [ ] Warns if `~/.local/bin` not in PATH
- [ ] Colored output with [INFO], [OK], [WARN], [FAIL] prefixes

### Error Handling
- [ ] Config validation on startup: check required sections exist, warn on unknown keys
- [ ] Graceful error if STT engine package not installed (clear install instructions in error message)
- [ ] Graceful error if xdotool not found (suggest `sudo apt install xdotool`)
- [ ] Graceful error if no microphone found (list available devices in error)
- [ ] All subprocess calls have timeouts
- [ ] Hotkey listener thread failure logged and surfaced via tray notification

### README.md
- [ ] Quick start (3 commands: clone, chmod, install.sh)
- [ ] How it works (hold hotkey → speak → release → text appears)
- [ ] Configuration reference (hotkey, STT engine, audio, injection, VAD, tray)
- [ ] Whisper model comparison table (size, speed, accuracy)
- [ ] Architecture diagram (file tree with one-line descriptions)
- [ ] CLI options
- [ ] Troubleshooting section: no text appears, model not found, high latency, permission denied, audio not captured

## Files to Create/Modify
- CREATE: `install.sh`
- CREATE: `README.md`
- MODIFY: `verbal_code/app.py` — add config validation, improve error messages
- MODIFY: all modules — review error handling, add missing try/except blocks

## Test It
```bash
# Fresh test (ideally in a VM or container):
git clone <repo> verbal-code && cd verbal-code
chmod +x install.sh
./install.sh          # should complete with no errors
verbal-code           # should start and work
verbal-code --help    # should show all options
```
