# Slice 11: Desktop Menu Entry & Application Icon

## Goal
Add Verbal Code to the Linux desktop application menu with a branded microphone icon, following the freedesktop `.desktop` entry standard. The icon and `.desktop` file are installed by `install.sh` and removed by `uninstall.sh`.

## Depends On
- Slice 9 (install.sh)
- Slice 10 (uninstall.sh)

## Acceptance Criteria
- [ ] `assets/verbal-code.svg` exists in the repository: a scalable mic icon using the red brand color (`#e53935`), same mic shape as `tray.py`
- [ ] `install.sh` installs the icon to `~/.local/share/icons/hicolor/scalable/apps/verbal-code.svg`
- [ ] `install.sh` creates `~/.local/share/applications/verbal-code.desktop` with correct freedesktop fields
- [ ] `install.sh` runs `gtk-update-icon-cache` and `update-desktop-database` if available (non-fatal if missing)
- [ ] After install, "Verbal Code" appears in the desktop application menu with the mic icon
- [ ] Clicking the menu entry launches the app (equivalent to running `verbal-code` from terminal)
- [ ] `uninstall.sh` removes `~/.local/share/applications/verbal-code.desktop`
- [ ] `uninstall.sh` removes `~/.local/share/icons/hicolor/scalable/apps/verbal-code.svg`
- [ ] `uninstall.sh` runs cache update commands if available (non-fatal)
- [ ] Both scripts log these operations with the existing colored [INFO]/[OK] output style

## Files to Create/Modify
- CREATE: `assets/verbal-code.svg`
- MODIFY: `install.sh` — add desktop entry and icon install steps after the launcher section
- MODIFY: `uninstall.sh` — add removal of `.desktop` file and icon

## Technical Notes
- Ship the icon as `assets/verbal-code.svg` in the repo so it exists at install time (the cache icons in `~/.cache/verbal-code/icons/` are only generated at runtime by `tray.py`)
- Reuse the mic shape from `tray.py`'s `_SVG_TEMPLATE` but with `width="128" height="128"` and brand red `#e53935` instead of idle gray
- Icon install path: `~/.local/share/icons/hicolor/scalable/apps/verbal-code.svg` — follows the freedesktop icon theme spec, `hicolor` is the guaranteed fallback theme
- `.desktop` file path: `~/.local/share/applications/verbal-code.desktop` — user-local per freedesktop spec
- Use `Icon=verbal-code` (themeable name, no path/extension) — the icon theme system resolves it from hicolor
- `Exec=bash -c '"$HOME/.local/bin/verbal-code"'` — some desktop environments don't expand `~` or `$HOME` in Exec values, so `bash -c` handles expansion at launch time
- `Terminal=false` — the app runs as a background daemon with a system tray
- `Categories=Utility;Accessibility;` — places it in the right menu sections
- `gtk-update-icon-cache` and `update-desktop-database` are called with error suppression (`|| true`) since they may not be installed on all systems

## .desktop File Contents
```ini
[Desktop Entry]
Type=Application
Name=Verbal Code
Comment=Voice-to-text for coding — speak and type
Exec=bash -c '"$HOME/.local/bin/verbal-code"'
Icon=verbal-code
Terminal=false
Categories=Utility;Accessibility;
Keywords=voice;speech;dictation;transcription;microphone;
StartupNotify=false
```

## Test It
```bash
# After running install.sh:
desktop-file-validate ~/.local/share/applications/verbal-code.desktop
ls -la ~/.local/share/icons/hicolor/scalable/apps/verbal-code.svg

# Check the app appears in menu (may need log out/in on some DEs)
# Or launch directly:
gio launch ~/.local/share/applications/verbal-code.desktop

# Uninstall and verify cleanup:
./uninstall.sh
ls ~/.local/share/applications/verbal-code.desktop  # should be gone
ls ~/.local/share/icons/hicolor/scalable/apps/verbal-code.svg  # should be gone
```
