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
error()   { echo -e "${RED}[-]${NC} $1"; }

# ── Resolve repo root ───────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Environment checks ──────────────────────────────────
if [ "$(id -u)" -eq 0 ]; then
    error "Do not run this script as root. It will ask for sudo when needed."
    exit 1
fi

if ! command -v sudo &>/dev/null; then
    error "sudo is required but not found."
    exit 1
fi

echo ""
echo -e "${BOLD}╔══════════════════════════════════════╗${NC}"
echo -e "${BOLD}║     verbal-code installer            ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════╝${NC}"
echo ""

# ── Step 1: Install system dependencies ──────────────────
info "Step 1/6: Installing system dependencies..."
if bash "$REPO_ROOT/scripts/install_deps.sh"; then
    success "System dependencies installed."
else
    error "Failed to install system dependencies."
    exit 1
fi
echo ""

# ── Step 2: Download speech models ───────────────────────
info "Step 2/6: Downloading speech models..."
if bash "$REPO_ROOT/scripts/download_models.sh"; then
    success "Speech models ready."
else
    error "Failed to download speech models."
    exit 1
fi
echo ""

# ── Step 3: Build ────────────────────────────────────────
info "Step 3/6: Building verbal-code..."
cd "$REPO_ROOT"
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build -j"$(nproc)"
success "Build complete."
echo ""

# ── Step 4: Install binary ───────────────────────────────
info "Step 4/6: Installing binary to /usr/local/bin/..."
if [ -f /usr/local/bin/verbal-code ]; then
    warn "Binary already exists at /usr/local/bin/verbal-code — updating."
fi
sudo cp "$REPO_ROOT/build/src/app/verbal-code" /usr/local/bin/verbal-code
sudo chmod 755 /usr/local/bin/verbal-code
success "Binary installed to /usr/local/bin/verbal-code"
echo ""

# ── Step 5: Install icon ────────────────────────────────
info "Step 5/6: Installing application icon..."
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
mkdir -p "$ICON_DIR"
cp "$REPO_ROOT/assets/verbal-code.svg" "$ICON_DIR/verbal-code.svg"
success "Icon installed to $ICON_DIR/verbal-code.svg"
echo ""

# ── Step 6: Install desktop entry ────────────────────────
info "Step 6/6: Installing desktop entry..."
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
cp "$REPO_ROOT/assets/verbal-code.desktop" "$APPS_DIR/verbal-code.desktop"

if command -v update-desktop-database &>/dev/null; then
    update-desktop-database "$APPS_DIR" 2>/dev/null || true
fi
success "Desktop entry installed to $APPS_DIR/verbal-code.desktop"
echo ""

# ── Fix config ownership (in case prior sudo created it) ─
CONFIG_DIR="$HOME/.config/verbal-code"
if [ -d "$CONFIG_DIR" ]; then
    if [ "$(stat -c '%U' "$CONFIG_DIR")" != "$(whoami)" ]; then
        warn "Fixing ownership of $CONFIG_DIR..."
        sudo chown -R "$(id -u):$(id -g)" "$CONFIG_DIR"
    fi
fi

# ── Done ─────────────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo -e "${GREEN}${BOLD}  Installation complete!${NC}"
echo -e "${GREEN}${BOLD}════════════════════════════════════════${NC}"
echo ""
echo "  You can now launch Verbal Code by:"
echo "    - Searching \"Verbal Code\" in your application menu"
echo "    - Running 'verbal-code' from a terminal"
echo ""
echo "  To uninstall: ./scripts/uninstall.sh"
echo ""
