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
    libnotify-bin
    python3-venv
    python3-dev
)

# Prefer the maintained Ayatana indicator library; older releases only ship
# the legacy AppIndicator3. The tray code accepts either at runtime.
if apt-cache show gir1.2-ayatanaappindicator3-0.1 &>/dev/null; then
    APT_PACKAGES+=(gir1.2-ayatanaappindicator3-0.1)
else
    APT_PACKAGES+=(gir1.2-appindicator3-0.1)
fi

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

# ── Optional STT engines ──
# parakeet, sherpa and whisper are core dependencies in pyproject.toml and
# are always installed; only moonshine and vosk are extras.
echo ""
info "Parakeet, sherpa-onnx and faster-whisper engines are always installed."
info "Choose optional extra engine(s):"
echo "  1) none (recommended)"
echo "  2) moonshine (fast English-only, CPU/onnxruntime, no torch)"
echo "  3) vosk (lightweight streaming, ~40MB, lower accuracy)"
echo "  4) both"
echo ""
read -rp "Enter choice [1]: " STT_CHOICE
STT_CHOICE="${STT_CHOICE:-1}"

case "$STT_CHOICE" in
    1) EXTRAS="" ;;
    2) EXTRAS="[moonshine]" ;;
    3) EXTRAS="[vosk]" ;;
    4) EXTRAS="[moonshine,vosk]" ;;
    *)
        warn "Invalid choice, installing no extra engines"
        EXTRAS=""
        ;;
esac

# Older installs pulled in torch (~2 GB) for Silero VAD; faster-whisper's
# bundled ONNX VAD replaced it, so reclaim the space on upgrade.
if "$PIP" show torch &>/dev/null; then
    info "Removing obsolete torch dependency (~2 GB)..."
    "$PIP" uninstall --quiet -y torch torchaudio 2>/dev/null || true
    ok "torch removed"
fi

# ── Install verbal-code package ──
# Installing through the package (and its extras) applies the version pins
# in pyproject.toml; re-running the installer upgrades an existing venv.
info "Installing verbal-code and its dependencies in editable mode..."
"$PIP" install --quiet -e "${SCRIPT_DIR}${EXTRAS}"
"$PIP" install --quiet pytest ruff
ok "verbal-code package installed${EXTRAS:+ with extras $EXTRAS}"

# ── Config file ──
CONFIG_CREATED=false
if [ ! -f "$CONFIG_DIR/config.yaml" ]; then
    info "Copying default config to $CONFIG_DIR/config.yaml"
    mkdir -p "$CONFIG_DIR"
    cp "$SCRIPT_DIR/config.yaml" "$CONFIG_DIR/config.yaml"
    CONFIG_CREATED=true
    ok "Config file created"
else
    ok "Config file already exists at $CONFIG_DIR/config.yaml"
fi
# uninstall.sh keeps the dictionary (MCC-128); a reinstall reuses it as-is.
if [ -f "$CONFIG_DIR/dictionary.json" ]; then
    ok "Existing dictionary found at $CONFIG_DIR/dictionary.json; it will be used"
fi

# ── Speech model ──
# Download the model now so the first dictation doesn't wait on it (MCC-130).
# A fresh install defaults to Parakeet v2; on a re-run, Enter keeps whatever
# the config already selects. A skipped or failed download happens on the
# app's first start instead.
CURRENT_MODEL=$("$PYTHON" -c 'import sys
from verbal_code.app import load_config
from verbal_code.transcriber import current_selection
print(*current_selection(load_config(sys.argv[1])))' "$CONFIG_DIR/config.yaml")
if [ "$CONFIG_CREATED" = true ]; then
    MODEL_DEFAULT=1
else
    MODEL_DEFAULT=5
fi

echo ""
info "Choose the speech-to-text model to download now:"
echo "  1) Parakeet TDT 0.6B v2  - English, most accurate (~660 MB, recommended)"
echo "  2) Parakeet TDT 0.6B v3  - English + 24 European languages (~670 MB)"
echo "  3) Parakeet TDT-CTC 110M - English, featherweight for slower CPUs (~140 MB)"
echo "  4) Another engine or model (sherpa-onnx live streaming, whisper, ...)"
echo "  5) Keep the current selection ($CURRENT_MODEL)"
echo "  6) Skip the download (it happens on the app's first start)"
echo ""
# `|| true`: a piped install (e.g. `echo 1 | ./install.sh`) hits EOF here
# and takes the default rather than aborting under `set -e`.
read -rp "Enter choice [$MODEL_DEFAULT]: " MODEL_CHOICE || true
MODEL_CHOICE="${MODEL_CHOICE:-$MODEL_DEFAULT}"

MODEL_ARGS=()
DOWNLOAD=true
case "$MODEL_CHOICE" in
    1) MODEL_ARGS=(--set-model parakeet nemo-parakeet-tdt-0.6b-v2) ;;
    2) MODEL_ARGS=(--set-model parakeet nemo-parakeet-tdt-0.6b-v3) ;;
    3) MODEL_ARGS=(--set-model parakeet nemo-parakeet-tdt_ctc-110m) ;;
    4)
        mapfile -t OTHER_MODELS < <("$PYTHON" -m verbal_code --list-models | grep -v '^parakeet ')
        echo ""
        for i in "${!OTHER_MODELS[@]}"; do
            echo "  $((i + 1))) ${OTHER_MODELS[$i]}"
        done
        read -rp "Enter choice: " OTHER_CHOICE || true
        if [[ "$OTHER_CHOICE" =~ ^[0-9]+$ ]] \
            && [ "$OTHER_CHOICE" -ge 1 ] && [ "$OTHER_CHOICE" -le ${#OTHER_MODELS[@]} ]; then
            read -r OTHER_ENGINE OTHER_MODEL <<< "${OTHER_MODELS[$((OTHER_CHOICE - 1))]}"
            MODEL_ARGS=(--set-model "$OTHER_ENGINE" "$OTHER_MODEL")
            if [ "$OTHER_ENGINE" = sherpa ] || [ "$OTHER_ENGINE" = vosk ]; then
                info "To type while you speak, set stt.streaming_enabled: true in $CONFIG_DIR/config.yaml"
            fi
        else
            warn "Invalid choice, keeping the current selection ($CURRENT_MODEL)"
        fi
        ;;
    5) ;;
    6) DOWNLOAD=false ;;
    *) warn "Invalid choice, keeping the current selection ($CURRENT_MODEL)" ;;
esac

if [ "$DOWNLOAD" = true ]; then
    if "$PYTHON" -m verbal_code "${MODEL_ARGS[@]}" --download-model; then
        ok "Speech model ready"
    else
        warn "The model download did not finish; Verbal Code retries it on first start."
        warn "To retry now: verbal-code --download-model"
    fi
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
info "Switch models any time from the tray's Model menu (new ones download on first use)."
echo ""

# Same exact-invocation pattern as uninstall.sh, so only the app matches.
if pgrep -f "verbal-code/venv/bin/python -m verbal_code" &>/dev/null; then
    warn "Verbal Code is running; restart it to pick up this update."
    echo ""
fi
