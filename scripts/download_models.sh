#!/bin/bash
set -euo pipefail

# ── Colors ───────────────────────────────────────────────
BOLD='\033[1m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()    { echo -e "${BOLD}[*]${NC} $1"; }
success() { echo -e "${GREEN}[+]${NC} $1"; }
warn()    { echo -e "${YELLOW}[!]${NC} $1"; }

MODELS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/verbal-code/models"
META_DIR="$MODELS_DIR/.meta"
mkdir -p "$MODELS_DIR" "$META_DIR"

# ── Vosk model ────────────────────────────────────────────

VOSK_MODEL_BASE="vosk-model-small-en-us"
VOSK_CURRENT_VERSION="0.15"
VOSK_MODELS_URL="https://alphacephei.com/vosk/models"

info "Checking for latest Vosk model..."

# Try to find a newer version by checking the models page
VOSK_LATEST_VERSION="$VOSK_CURRENT_VERSION"
if command -v curl &>/dev/null; then
    # Scrape the models page for vosk-model-small-en-us-X.XX versions
    PAGE_CONTENT=$(curl -sL --max-time 10 "$VOSK_MODELS_URL" 2>/dev/null || true)
    if [ -n "$PAGE_CONTENT" ]; then
        # Extract all version numbers for this model, pick the highest
        FOUND_VERSION=$(echo "$PAGE_CONTENT" \
            | grep -oP "${VOSK_MODEL_BASE}-\K[0-9]+\.[0-9]+" \
            | sort -V | tail -1 || true)
        if [ -n "$FOUND_VERSION" ]; then
            VOSK_LATEST_VERSION="$FOUND_VERSION"
        fi
    fi
fi

VOSK_MODEL="${VOSK_MODEL_BASE}-${VOSK_LATEST_VERSION}"
VOSK_URL="${VOSK_MODELS_URL}/${VOSK_MODEL}.zip"
VOSK_INSTALLED_FILE="$META_DIR/vosk-installed-version"

# Check if we have this version already
VOSK_INSTALLED=""
if [ -f "$VOSK_INSTALLED_FILE" ]; then
    VOSK_INSTALLED=$(cat "$VOSK_INSTALLED_FILE")
fi

if [ "$VOSK_INSTALLED" = "$VOSK_LATEST_VERSION" ] && [ -d "$MODELS_DIR/$VOSK_MODEL" ]; then
    success "Vosk model is up to date: $VOSK_MODEL"
elif [ -n "$VOSK_INSTALLED" ] && [ "$VOSK_INSTALLED" != "$VOSK_LATEST_VERSION" ] && [ -d "$MODELS_DIR/${VOSK_MODEL_BASE}-${VOSK_INSTALLED}" ]; then
    info "Vosk model update available: ${VOSK_MODEL_BASE}-${VOSK_INSTALLED} → $VOSK_MODEL"
    info "Downloading Vosk model: $VOSK_MODEL..."
    cd "$MODELS_DIR"
    curl -L -o "${VOSK_MODEL}.zip" "$VOSK_URL"
    unzip -q "${VOSK_MODEL}.zip"
    rm "${VOSK_MODEL}.zip"
    echo "$VOSK_LATEST_VERSION" > "$VOSK_INSTALLED_FILE"
    # Remove old version
    OLD_MODEL="${VOSK_MODEL_BASE}-${VOSK_INSTALLED}"
    if [ -d "$MODELS_DIR/$OLD_MODEL" ] && [ "$OLD_MODEL" != "$VOSK_MODEL" ]; then
        warn "Removing old model: $OLD_MODEL"
        rm -rf "$MODELS_DIR/$OLD_MODEL"
    fi
    success "Vosk model updated to: $VOSK_MODEL"
else
    info "Downloading Vosk model: $VOSK_MODEL..."
    cd "$MODELS_DIR"
    curl -L -o "${VOSK_MODEL}.zip" "$VOSK_URL"
    unzip -q "${VOSK_MODEL}.zip"
    rm "${VOSK_MODEL}.zip"
    echo "$VOSK_LATEST_VERSION" > "$VOSK_INSTALLED_FILE"
    success "Vosk model installed: $VOSK_MODEL"
fi

# ── Whisper models (quantized, multi-model) ──────────────

WHISPER_BASE_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

# Associative array: model label -> filename
declare -A WHISPER_MODELS=(
    ["base.en-q5_1"]="ggml-base.en-q5_1.bin"
    ["small.en-q5_1"]="ggml-small.en-q5_1.bin"
    ["medium.en-q5_0"]="ggml-medium.en-q5_0.bin"
)

info "Checking Whisper models..."

WHISPER_OK=0
WHISPER_FAIL=0

for label in "${!WHISPER_MODELS[@]}"; do
    filename="${WHISPER_MODELS[$label]}"
    filepath="$MODELS_DIR/$filename"

    if [ -f "$filepath" ] && [ -s "$filepath" ]; then
        success "Whisper model already exists: $filename"
        ((++WHISPER_OK))
        continue
    fi

    info "Downloading Whisper model: $filename..."
    if curl -L --fail --progress-bar -o "$filepath" "$WHISPER_BASE_URL/$filename"; then
        success "Whisper model installed: $filename"
        ((++WHISPER_OK))
    else
        warn "Failed to download Whisper model: $filename"
        rm -f "$filepath"
        ((++WHISPER_FAIL))
    fi
done

info "Whisper models: $WHISPER_OK downloaded, $WHISPER_FAIL failed"

# ── Summary ───────────────────────────────────────────────

echo ""
success "All models ready in: $MODELS_DIR"
ls -lh "$MODELS_DIR"
