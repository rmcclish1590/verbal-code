#!/bin/bash
set -euo pipefail

MODELS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/verbal-code/models"
mkdir -p "$MODELS_DIR"

# ── Vosk model ────────────────────────────────────────────
VOSK_MODEL="vosk-model-small-en-us-0.15"
VOSK_URL="https://alphacephei.com/vosk/models/${VOSK_MODEL}.zip"

if [ ! -d "$MODELS_DIR/$VOSK_MODEL" ]; then
    echo "Downloading Vosk model: $VOSK_MODEL..."
    cd "$MODELS_DIR"
    curl -L -o "${VOSK_MODEL}.zip" "$VOSK_URL"
    unzip -q "${VOSK_MODEL}.zip"
    rm "${VOSK_MODEL}.zip"
    echo "Vosk model installed to: $MODELS_DIR/$VOSK_MODEL"
else
    echo "Vosk model already exists: $MODELS_DIR/$VOSK_MODEL"
fi

# ── Whisper model ─────────────────────────────────────────
WHISPER_MODEL="ggml-base.en.bin"
WHISPER_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/${WHISPER_MODEL}"

if [ ! -f "$MODELS_DIR/$WHISPER_MODEL" ]; then
    echo "Downloading Whisper model: $WHISPER_MODEL..."
    curl -L -o "$MODELS_DIR/$WHISPER_MODEL" "$WHISPER_URL"
    echo "Whisper model installed to: $MODELS_DIR/$WHISPER_MODEL"
else
    echo "Whisper model already exists: $MODELS_DIR/$WHISPER_MODEL"
fi

echo ""
echo "All models downloaded to: $MODELS_DIR"
ls -lh "$MODELS_DIR"
