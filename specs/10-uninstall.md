# Slice 10: Uninstall Script

## Goal
Create `uninstall.sh` that completely removes all verbal_code files, the virtual environment, cached models, icons, config, and the launcher script. Should be safe, interactive, and leave no traces behind.

## Depends On
- Slice 9 (install script — this mirrors everything it creates)

## What the Installer Creates (must all be removed)
- `~/.local/share/verbal-code/venv/` — Python virtual environment
- `~/.config/verbal-code/config.yaml` — user configuration
- `~/.cache/verbal-code/models/` — downloaded Vosk models
- `~/.cache/verbal-code/icons/` — system tray SVG icons
- `~/.local/bin/verbal-code` — launcher script
- `~/.cache/huggingface/hub/models--Systran--faster-whisper-*` — downloaded Whisper models (via huggingface hub)

## Acceptance Criteria
- [ ] `uninstall.sh` at project root, executable (`chmod +x`)
- [ ] Colored output matching `install.sh` style ([INFO], [OK], [WARN] prefixes)
- [ ] Checks if verbal-code is currently running (`pgrep -f "python.*verbal_code"`), warns and offers to kill it
- [ ] Prompts for confirmation before doing anything: "This will remove Verbal Code and all its data. Continue? [y/N]"
- [ ] Removes these paths (each with an existence check, logged individually):
  - `~/.local/bin/verbal-code` (launcher)
  - `~/.local/share/verbal-code/` (venv and all contents)
  - `~/.config/verbal-code/` (config directory)
  - `~/.cache/verbal-code/` (models and icons)
- [ ] Asks separately about Whisper model cache: "Remove downloaded Whisper models from ~/.cache/huggingface? These are large and shared with other apps. [y/N]"
  - If yes, removes only `~/.cache/huggingface/hub/models--Systran--faster-whisper-*` (glob match), NOT the entire huggingface cache
- [ ] Does NOT remove system apt packages (xdotool, xclip, etc.) — they may be used by other apps. Prints a note listing them in case the user wants to remove them manually.
- [ ] Does NOT remove the source code directory itself — just the installed artifacts. Prints a note: "Source code remains at <script_dir>. Delete manually if desired."
- [ ] Prints a clean summary of what was removed and what was skipped
- [ ] `--force` / `-f` flag skips all confirmation prompts (for scripted use)
- [ ] Exit code 0 on success, 1 on error

## Files to Create
- CREATE: `uninstall.sh`

## Technical Notes
- Use `rm -rf` for directories, `rm -f` for files — both are idempotent
- Check existence with `[ -d ... ]` / `[ -f ... ]` before removing, so output accurately reflects what was actually deleted vs already gone
- `pgrep -f "python.*verbal_code"` to detect running instances (matches both `python -m verbal_code` and the launcher)
- To kill: `pkill -f "python.*verbal_code"` with a 2-second grace period, then `pkill -9` if still alive
- The huggingface cache glob `models--Systran--faster-whisper-*` covers all model sizes (tiny, base, small, medium, large)
- Script should work even if verbal_code was only partially installed (some paths may not exist)

## Test It
```bash
# Install first, then uninstall:
./install.sh
ls ~/.local/bin/verbal-code          # exists
ls ~/.local/share/verbal-code/       # exists
ls ~/.config/verbal-code/            # exists

chmod +x uninstall.sh
./uninstall.sh

ls ~/.local/bin/verbal-code          # gone
ls ~/.local/share/verbal-code/       # gone
ls ~/.config/verbal-code/            # gone
ls ~/.cache/verbal-code/             # gone

# Verify nothing is left:
find ~ -name "*verbal-code*" 2>/dev/null
# Should only show the source code directory
```
