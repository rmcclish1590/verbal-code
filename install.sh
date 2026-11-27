#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Paths, app-file vs user-data split, build and deploy steps shared with
# update.sh and uninstall.sh (MCC-193).
# shellcheck source=scripts/install-lib.sh
source "$SCRIPT_DIR/scripts/install-lib.sh"

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

# ── System dependencies (APT_PACKAGES in scripts/install-lib.sh) ──
add_indicator_package
install_missing_apt_packages

# ── Python venv ──
if [ -d "$VENV_DIR" ]; then
    info "Venv already exists at $VENV_DIR"
else
    info "Creating Python venv at $VENV_DIR..."
    mkdir -p "$(dirname "$VENV_DIR")"
    python3 -m venv --system-site-packages "$VENV_DIR"
    ok "Venv created"
fi

# Upgrade pip
"$PYTHON" -m pip install --upgrade pip --quiet

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
if "$PYTHON" -m pip show torch &>/dev/null; then
    info "Removing obsolete torch dependency (~2 GB)..."
    "$PYTHON" -m pip uninstall --quiet -y torch torchaudio 2>/dev/null || true
    ok "torch removed"
fi

# ── Build, then install the verbal-code package ──
# A failed build stops here, before anything is installed (MCC-132).
# Re-running the installer upgrades an existing venv; ./update.sh does the
# same with rollback and without the menus.
build_package "$SCRIPT_DIR" "$EXTRAS"
info "Installing verbal-code and its dependencies in editable mode..."
deploy_package "$SCRIPT_DIR" "$EXTRAS"
ok "verbal-code package installed${EXTRAS:+ with extras $EXTRAS}"

# ── GPU backend (MCC-195) ──
# No prompt: detection picks the backend; VERBAL_CODE_GPU_BACKEND=rocm|cuda|cpu
# overrides it. A machine without a GPU sees nothing new here.
detect_gpu_backend
describe_gpu() {
    cd / || return 0
    "$PYTHON" -m verbal_code.ct2_backend describe 2>/dev/null || true
}
mapfile -t GPU_DESCRIPTION < <(describe_gpu)
if [ "$GPU_BACKEND" != cpu ]; then
    ok "${GPU_DESCRIPTION[0]:-GPU found}"
elif [ -n "${GPU_DESCRIPTION[1]:-}" ]; then
    # A GPU without a working runtime: one actionable line.
    warn "${GPU_DESCRIPTION[1]}"
fi
install_ct2_backend "$GPU_BACKEND"

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

# ── Launcher, desktop entry and icon ──
info "Installing the launcher, desktop entry and icon..."
install_app_files "$SCRIPT_DIR"
ok "Launcher: $LAUNCHER"
ok "Desktop entry and icon installed"
write_stamp "$(source_version "$SCRIPT_DIR")" "$(source_commit "$SCRIPT_DIR")" \
    "$CT2_BACKEND" "$CT2_WHEEL" "$ROCM_LD_PATH"

# ── PATH check ──
if ! echo "$PATH" | tr ':' '\n' | grep -q "$HOME/.local/bin"; then
    warn "$HOME/.local/bin is not in your PATH"
    warn "Add this to your ~/.bashrc or ~/.profile:"
    warn "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

# ── Done ──
echo ""
ok "Verbal Code $(read_stamp version) ($(read_stamp commit)) installed successfully!"
VERDICT=$(doctor_verdict)
if [ -n "$VERDICT" ]; then
    info "GPU: $VERDICT (details: verbal-code --doctor)"
fi
echo ""
info "To run:  verbal-code"
info "To test: verbal-code --test-audio"
info "Update:  ./update.sh (keeps your config, dictionary and models)"
info "Config:  $CONFIG_DIR/config.yaml"
info "Switch models any time from the tray's Model menu (new ones download on first use)."
echo ""

if app_running; then
    warn "Verbal Code is running; restart it to pick up this update."
    echo ""
fi
