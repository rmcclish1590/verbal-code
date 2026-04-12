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

VENV_DIR="$HOME/.local/share/verbal-code/venv"
CONFIG_DIR="$HOME/.config/verbal-code"
LAUNCHER="$HOME/.local/bin/verbal-code"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# ── Python version check ──
info "Checking Python version..."
if ! command -v python3 &>/dev/null; then
    fail "python3 not found. Install Python 3.10+ first."
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]; }; then
    fail "Python 3.10+ required, found $PY_VERSION"
fi
ok "Python $PY_VERSION"

# ── System dependencies ──
APT_PACKAGES=(
    xdotool
    xclip
    libportaudio2
    portaudio19-dev
    python3-gi
    gir1.2-appindicator3-0.1
    libnotify-bin
    python3-venv
)

MISSING=()
for pkg in "${APT_PACKAGES[@]}"; do
    if ! dpkg -s "$pkg" &>/dev/null; then
        MISSING+=("$pkg")
    fi
done

if [ ${#MISSING[@]} -gt 0 ]; then
    info "Installing system packages: ${MISSING[*]}"
    sudo apt install -y "${MISSING[@]}"
    ok "System packages installed"
else
    ok "All system packages already installed"
fi

# ── Python venv ──
if [ -d "$VENV_DIR" ]; then
    info "Venv already exists at $VENV_DIR"
else
    info "Creating Python venv at $VENV_DIR..."
    mkdir -p "$(dirname "$VENV_DIR")"
    python3 -m venv --system-site-packages "$VENV_DIR"
    ok "Venv created"
fi

PIP="$VENV_DIR/bin/pip"
PYTHON="$VENV_DIR/bin/python"

# Upgrade pip
"$PIP" install --upgrade pip --quiet

# ── STT engine selection ──
echo ""
info "Choose STT engine(s) to install:"
echo "  1) faster-whisper (recommended, ~200MB, GPU/CPU)"
echo "  2) vosk (lightweight, ~40MB, CPU only)"
echo "  3) both"
echo ""
read -rp "Enter choice [1]: " STT_CHOICE
STT_CHOICE="${STT_CHOICE:-1}"

info "Installing core dependencies..."
"$PIP" install --quiet PyYAML numpy sounddevice pynput

case "$STT_CHOICE" in
    1)
        info "Installing faster-whisper..."
        "$PIP" install --quiet faster-whisper
        ok "faster-whisper installed"
        ;;
    2)
        info "Installing vosk..."
        "$PIP" install --quiet vosk
        ok "vosk installed"
        ;;
    3)
        info "Installing faster-whisper and vosk..."
        "$PIP" install --quiet faster-whisper vosk
        ok "Both engines installed"
        ;;
    *)
        warn "Invalid choice, defaulting to faster-whisper"
        "$PIP" install --quiet faster-whisper
        ok "faster-whisper installed"
        ;;
esac

# ── Install verbal-code package ──
info "Installing verbal-code in editable mode..."
"$PIP" install --quiet -e "$SCRIPT_DIR"
ok "verbal-code package installed"

# ── Config file ──
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    info "Copying default config to $CONFIG_DIR/config.yaml"
    mkdir -p "$CONFIG_DIR"
    cp "$SCRIPT_DIR/config.yaml" "$CONFIG_DIR/config.yaml"
    ok "Config file created"
else
    ok "Config file already exists at $CONFIG_DIR/config.yaml"
fi

# ── Launcher script ──
info "Creating launcher at $LAUNCHER"
mkdir -p "$(dirname "$LAUNCHER")"
cat > "$LAUNCHER" << 'LAUNCHER_EOF'
#!/usr/bin/env bash
VENV="$HOME/.local/share/verbal-code/venv"
exec "$VENV/bin/python" -m verbal_code "$@"
LAUNCHER_EOF
chmod +x "$LAUNCHER"
ok "Launcher created"

# ── Desktop entry ──
ICON_DIR="$HOME/.local/share/icons/hicolor/scalable/apps"
DESKTOP_DIR="$HOME/.local/share/applications"

info "Installing application icon..."
mkdir -p "$ICON_DIR"
cp "$SCRIPT_DIR/assets/verbal-code.svg" "$ICON_DIR/verbal-code.svg"
ok "Icon installed"

info "Creating desktop entry..."
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/verbal-code.desktop" << 'DESKTOP_EOF'
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
DESKTOP_EOF
ok "Desktop entry created"

gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# ── PATH check ──
if ! echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin"; then
    warn "$HOME/.local/bin is not in your PATH"
    warn "Add this to your ~/.bashrc or ~/.profile:"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ── Done ──
echo ""
ok "Verbal Code installed successfully!"
echo ""
info "To run:  verbal-code"
info "To test: verbal-code --test-audio"
info "Config:  $CONFIG_DIR/config.yaml"
echo ""
