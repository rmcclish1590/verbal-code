#!/bin/bash
set -euo pipefail

# ── Colors ───────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

info()    { echo -e "${BOLD}[*]${NC} $1"; }
success() { echo -e "${GREEN}[+]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }

echo ""
echo -e "${BOLD}verbal-code uninstaller${NC}"
echo ""

# ── Remove binary ────────────────────────────────────────
if [ -f /usr/local/bin/verbal-code ]; then
    info "Removing /usr/local/bin/verbal-code..."
    sudo rm /usr/local/bin/verbal-code
    success "Binary removed."
else
    info "Binary not found at /usr/local/bin/verbal-code — skipping."
fi

# ── Remove desktop entry ────────────────────────────────
DESKTOP_FILE="$HOME/.local/share/applications/verbal-code.desktop"
if [ -f "$DESKTOP_FILE" ]; then
    info "Removing desktop entry..."
    rm "$DESKTOP_FILE"
    if command -v update-desktop-database &>/dev/null; then
        update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true
    fi
    success "Desktop entry removed."
else
    info "Desktop entry not found — skipping."
fi

# ── Remove icon ──────────────────────────────────────────
ICON_FILE="$HOME/.local/share/icons/hicolor/scalable/apps/verbal-code.svg"
if [ -f "$ICON_FILE" ]; then
    info "Removing icon..."
    rm "$ICON_FILE"
    success "Icon removed."
else
    info "Icon not found — skipping."
fi

# ── Ask about user data ─────────────────────────────────
echo ""
CONFIG_DIR="$HOME/.config/verbal-code"
MODELS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/verbal-code"

if [ -d "$CONFIG_DIR" ] || [ -d "$MODELS_DIR" ]; then
    echo -e "${YELLOW}The following user data directories still exist:${NC}"
    [ -d "$CONFIG_DIR" ] && echo "  - $CONFIG_DIR (config, transcriptions)"
    [ -d "$MODELS_DIR" ] && echo "  - $MODELS_DIR (speech models ~200MB)"
    echo ""
    read -rp "Remove user data? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        [ -d "$CONFIG_DIR" ] && rm -rf "$CONFIG_DIR" && success "Removed $CONFIG_DIR"
        [ -d "$MODELS_DIR" ] && rm -rf "$MODELS_DIR" && success "Removed $MODELS_DIR"
    else
        info "User data kept."
    fi
fi

echo ""
success "verbal-code has been uninstalled."
echo ""
