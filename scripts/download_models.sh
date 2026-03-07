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

# ── Whisper model ─────────────────────────────────────────

WHISPER_MODEL="ggml-base.en.bin"
WHISPER_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${WHISPER_MODEL}"
WHISPER_API_URL="https://huggingface.co/api/models/ggerganov/whisper.cpp"
WHISPER_ETAG_FILE="$META_DIR/whisper-etag"

info "Checking for latest Whisper model..."

# Get the remote ETag to detect updates
REMOTE_ETAG=""
if command -v curl &>/dev/null; then
    REMOTE_ETAG=$(curl -sI -L --max-time 10 "$WHISPER_URL" 2>/dev/null \
        | grep -i "^etag:" | tail -1 | tr -d '\r' | sed 's/^[Ee][Tt][Aa][Gg]: *//' || true)
fi

LOCAL_ETAG=""
if [ -f "$WHISPER_ETAG_FILE" ]; then
    LOCAL_ETAG=$(cat "$WHISPER_ETAG_FILE")
fi

if [ -f "$MODELS_DIR/$WHISPER_MODEL" ]; then
    if [ -n "$REMOTE_ETAG" ] && [ -n "$LOCAL_ETAG" ] && [ "$REMOTE_ETAG" = "$LOCAL_ETAG" ]; then
        success "Whisper model is up to date: $WHISPER_MODEL"
    elif [ -n "$REMOTE_ETAG" ] && [ "$REMOTE_ETAG" != "$LOCAL_ETAG" ]; then
        info "Whisper model update detected, downloading: $WHISPER_MODEL..."
        curl -L -o "$MODELS_DIR/$WHISPER_MODEL" "$WHISPER_URL"
        echo "$REMOTE_ETAG" > "$WHISPER_ETAG_FILE"
        success "Whisper model updated: $WHISPER_MODEL"
    else
        # Can't check remote — keep existing
        success "Whisper model exists: $WHISPER_MODEL (could not check for updates)"
    fi
else
    info "Downloading Whisper model: $WHISPER_MODEL..."
    curl -L -o "$MODELS_DIR/$WHISPER_MODEL" "$WHISPER_URL"
    if [ -n "$REMOTE_ETAG" ]; then
        echo "$REMOTE_ETAG" > "$WHISPER_ETAG_FILE"
    fi
    success "Whisper model installed: $WHISPER_MODEL"
fi

# ── Summary ───────────────────────────────────────────────

echo ""
success "All models ready in: $MODELS_DIR"
ls -lh "$MODELS_DIR"
