#!/usr/bin/env bash
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.config/verbal-code"
FORCE=false
PURGE=false

for arg in "$@"; do
    case "$arg" in
        -f|--force) FORCE=true ;;
        --purge) PURGE=true ;;
    esac
done

# ── Locate the dictionary (kept unless --purge, MCC-128) ──
# User-curated terms take time to build, so a reinstall should find them.
# A custom dictionary.path in config.yaml wins; read it before the config
# is removed. Uses the system python3 (the venv may already be gone).
DICT_PATH="$CONFIG_DIR/dictionary.json"
CUSTOM_DICT=$(python3 - "$CONFIG_DIR/config.yaml" 2>/dev/null <<'PY' || true
import os, sys, yaml
with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f) or {}
path = (cfg.get("dictionary") or {}).get("path")
if path:
    print(os.path.expanduser(str(path)))
PY
)
if [ -n "$CUSTOM_DICT" ]; then
    DICT_PATH="$CUSTOM_DICT"
fi
DICT_DISPLAY="${DICT_PATH/#$HOME/\~}"
KEEP_DICT=false
if [ "$PURGE" != true ] && [ -f "$DICT_PATH" ]; then
    KEEP_DICT=true
fi

# ── Check for running instances ──
# Match only the launcher's exact interpreter invocation. A broad pattern
# like "python.*verbal_code" would also kill unrelated processes whose
# command line merely mentions the repo (an editor's language server, a
# pytest run, any tool passed a verbal_code path).
APP_PATTERN="verbal-code/venv/bin/python -m verbal_code"

if pgrep -f "$APP_PATTERN" &>/dev/null; then
    warn "Verbal Code appears to be running."
    if [ "$FORCE" = true ]; then
        info "Stopping running instances..."
        pkill -f "$APP_PATTERN" || true
        sleep 2
        pkill -9 -f "$APP_PATTERN" 2>/dev/null || true
        ok "Stopped"
    else
        read -rp "Kill running instances? [y/N] " KILL_CHOICE
        if [[ "${KILL_CHOICE,,}" == "y" ]]; then
            pkill -f "$APP_PATTERN" || true
            sleep 2
            pkill -9 -f "$APP_PATTERN" 2>/dev/null || true
            ok "Stopped"
        else
            warn "Continuing with uninstall — running instance may behave unexpectedly"
        fi
    fi
fi

# ── Confirmation ──
if [ "$FORCE" != true ]; then
    echo ""
    if [ "$PURGE" = true ]; then
        warn "This will remove Verbal Code and all its data, including your dictionary."
    elif [ "$KEEP_DICT" = true ]; then
        warn "This will remove Verbal Code and its data."
        info "Your dictionary ($DICT_DISPLAY) will be kept; use --purge to remove it too."
    else
        warn "This will remove Verbal Code and all its data."
    fi
    read -rp "Continue? [y/N] " CONFIRM
    if [[ "${CONFIRM,,}" != "y" ]]; then
        info "Aborted."
        exit 0
    fi
    echo ""
fi

REMOVED=()
SKIPPED=()

# ── Remove launcher ──
if [ -f "$HOME/.local/bin/verbal-code" ]; then
    rm -f "$HOME/.local/bin/verbal-code"
    ok "Removed launcher: ~/.local/bin/verbal-code"
    REMOVED+=("launcher")
else
    SKIPPED+=("launcher (not found)")
fi

# ── Remove desktop entry ──
if [ -f "$HOME/.local/share/applications/verbal-code.desktop" ]; then
    rm -f "$HOME/.local/share/applications/verbal-code.desktop"
    ok "Removed desktop entry: ~/.local/share/applications/verbal-code.desktop"
    REMOVED+=("desktop entry")
else
    SKIPPED+=("desktop entry (not found)")
fi

# ── Remove icon ──
if [ -f "$HOME/.local/share/icons/hicolor/scalable/apps/verbal-code.svg" ]; then
    rm -f "$HOME/.local/share/icons/hicolor/scalable/apps/verbal-code.svg"
    ok "Removed icon: ~/.local/share/icons/hicolor/scalable/apps/verbal-code.svg"
    REMOVED+=("icon")
else
    SKIPPED+=("icon (not found)")
fi

gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

# ── Remove venv ──
if [ -d "$HOME/.local/share/verbal-code" ]; then
    rm -rf "$HOME/.local/share/verbal-code"
    ok "Removed venv: ~/.local/share/verbal-code/"
    REMOVED+=("venv")
else
    SKIPPED+=("venv (not found)")
fi

# ── Remove config (everything but a kept dictionary) ──
if [ -d "$CONFIG_DIR" ]; then
    if [ "$KEEP_DICT" = true ] && [[ "$DICT_PATH" == "$CONFIG_DIR"/* ]]; then
        find "$CONFIG_DIR" -mindepth 1 ! -type d ! -path "$DICT_PATH" -delete
        find "$CONFIG_DIR" -mindepth 1 -type d -empty -delete
        ok "Removed config: ~/.config/verbal-code/ (dictionary kept)"
    else
        rm -rf "$CONFIG_DIR"
        ok "Removed config: ~/.config/verbal-code/"
    fi
    REMOVED+=("config")
else
    SKIPPED+=("config (not found)")
fi

# A custom dictionary.path can live outside the config directory.
if [ "$PURGE" = true ] && [ -f "$DICT_PATH" ]; then
    rm -f "$DICT_PATH"
    ok "Removed dictionary: $DICT_DISPLAY"
    REMOVED+=("dictionary")
fi

# ── Remove cache (sherpa-onnx and vosk models, icons) ──
if [ -d "$HOME/.cache/verbal-code" ]; then
    rm -rf "$HOME/.cache/verbal-code"
    ok "Removed cache: ~/.cache/verbal-code/"
    REMOVED+=("cache")
else
    SKIPPED+=("cache (not found)")
fi

# ── Silero VAD model cache (legacy: older versions used torch/silero-vad) ──
SILERO_CACHE="$HOME/.cache/torch/hub/snakers4_silero-vad_master"
if [ -d "$SILERO_CACHE" ]; then
    rm -rf "$SILERO_CACHE"
    ok "Removed Silero VAD cache: $SILERO_CACHE"
    REMOVED+=("silero-vad cache")
else
    SKIPPED+=("silero-vad cache (not found)")
fi

# ── Whisper / Moonshine / Parakeet models (separate prompt) ──
# One glob per Hugging Face org the engines download from: faster-whisper's
# model table spans Systran (plain and distil), distil-whisper and
# mobiuslabsgmbh (large-v3-turbo).
HF_MODELS=(
    "$HOME"/.cache/huggingface/hub/models--Systran--faster-whisper-*
    "$HOME"/.cache/huggingface/hub/models--Systran--faster-distil-whisper-*
    "$HOME"/.cache/huggingface/hub/models--distil-whisper--distil-*-ct2
    "$HOME"/.cache/huggingface/hub/models--mobiuslabsgmbh--faster-whisper-*
    "$HOME"/.cache/huggingface/hub/models--UsefulSensors--moonshine*
    "$HOME"/.cache/huggingface/hub/models--istupakov--parakeet-*
)
HF_FOUND=false
for m in "${HF_MODELS[@]}"; do
    if [ -d "$m" ]; then
        HF_FOUND=true
        break
    fi
done

if [ "$HF_FOUND" = true ]; then
    if [ "$FORCE" = true ]; then
        REMOVE_HF="y"
    else
        echo ""
        warn "Downloaded Whisper/Moonshine/Parakeet models found in ~/.cache/huggingface/"
        warn "These are large and may be shared with other apps."
        read -rp "Remove model cache? [y/N] " REMOVE_HF
    fi
    if [[ "${REMOVE_HF,,}" == "y" ]]; then
        for m in "${HF_MODELS[@]}"; do
            if [ -d "$m" ]; then
                rm -rf "$m"
                ok "Removed $(basename "$m")"
            fi
        done
        REMOVED+=("whisper/moonshine/parakeet models")
    else
        SKIPPED+=("whisper/moonshine/parakeet models (kept)")
    fi
else
    SKIPPED+=("whisper/moonshine/parakeet models (not found)")
fi

# ── Summary ──
echo ""
echo "────────────────────────────────"
if [ ${#REMOVED[@]} -gt 0 ]; then
    ok "Removed: ${REMOVED[*]}"
fi
if [ ${#SKIPPED[@]} -gt 0 ]; then
    info "Skipped: ${SKIPPED[*]}"
fi
if [ "$KEEP_DICT" = true ]; then
    echo ""
    ok "Kept your dictionary: $DICT_DISPLAY"
    info "Reinstalling picks it up automatically. To delete it too: ./uninstall.sh --purge"
fi
echo ""
info "System packages (xdotool, xclip, python3-gi, etc.) were NOT removed."
info "To remove them manually: sudo apt remove xdotool xclip libnotify-bin gir1.2-ayatanaappindicator3-0.1"
info "(older releases use gir1.2-appindicator3-0.1 instead of the ayatana package)"
echo ""
info "Source code remains at $SCRIPT_DIR"
info "Delete manually if desired: rm -rf $SCRIPT_DIR"
echo ""
ok "Verbal Code uninstalled."
