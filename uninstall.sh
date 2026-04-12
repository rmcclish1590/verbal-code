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
FORCE=false

for arg in "$@"; do
    case "$arg" in
        -f|--force) FORCE=true ;;
    esac
done

# ── Check for running instances ──
if pgrep -f "python.*verbal_code" &>/dev/null; then
    warn "Verbal Code appears to be running."
    if [ "$FORCE" = true ]; then
        info "Stopping running instances..."
        pkill -f "python.*verbal_code" || true
        sleep 2
        pkill -9 -f "python.*verbal_code" 2>/dev/null || true
        ok "Stopped"
    else
        read -rp "Kill running instances? [y/N] " KILL_CHOICE
        if [[ "${KILL_CHOICE,,}" == "y" ]]; then
            pkill -f "python.*verbal_code" || true
            sleep 2
            pkill -9 -f "python.*verbal_code" 2>/dev/null || true
            ok "Stopped"
        else
            warn "Continuing with uninstall — running instance may behave unexpectedly"
        fi
    fi
fi

# ── Confirmation ──
if [ "$FORCE" != true ]; then
    echo ""
    warn "This will remove Verbal Code and all its data."
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

# ── Remove config ──
if [ -d "$HOME/.config/verbal-code" ]; then
    rm -rf "$HOME/.config/verbal-code"
    ok "Removed config: ~/.config/verbal-code/"
    REMOVED+=("config")
else
    SKIPPED+=("config (not found)")
fi

# ── Remove cache (models, icons) ──
if [ -d "$HOME/.cache/verbal-code" ]; then
    rm -rf "$HOME/.cache/verbal-code"
    ok "Removed cache: ~/.cache/verbal-code/"
    REMOVED+=("cache")
else
    SKIPPED+=("cache (not found)")
fi

# ── Whisper models (separate prompt) ──
HF_MODELS=("$HOME"/.cache/huggingface/hub/models--Systran--faster-whisper-*)
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
        warn "Downloaded Whisper models found in ~/.cache/huggingface/"
        warn "These are large and may be shared with other apps."
        read -rp "Remove Whisper model cache? [y/N] " REMOVE_HF
    fi
    if [[ "${REMOVE_HF,,}" == "y" ]]; then
        for m in "${HF_MODELS[@]}"; do
            if [ -d "$m" ]; then
                rm -rf "$m"
                ok "Removed $(basename "$m")"
            fi
        done
        REMOVED+=("whisper models")
    else
        SKIPPED+=("whisper models (kept)")
    fi
else
    SKIPPED+=("whisper models (not found)")
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
echo ""
info "System packages (xdotool, xclip, python3-gi, etc.) were NOT removed."
info "To remove them manually: sudo apt remove xdotool xclip gir1.2-appindicator3-0.1 libnotify-bin"
echo ""
info "Source code remains at $SCRIPT_DIR"
info "Delete manually if desired: rm -rf $SCRIPT_DIR"
echo ""
ok "Verbal Code uninstalled."
