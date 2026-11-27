#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# Paths and the running-app match, shared with install.sh and update.sh.
# shellcheck source=scripts/install-lib.sh
source "$SCRIPT_DIR/scripts/install-lib.sh"

usage() {
    cat <<USAGE
Usage: ./uninstall.sh [-f|--force] [--keep-dictionary | --purge-dictionary]

Removes Verbal Code: launcher, desktop entry, icon, venv, config, caches
and (after asking) downloaded models. Your dictionary is kept unless you
choose to delete it.

  -f, --force           ask nothing: stop a running Verbal Code, remove the
                        models, and keep the dictionary unless
                        --purge-dictionary is given
  --keep-dictionary     keep the dictionary without asking
  --purge-dictionary    delete the dictionary too (permanent)
  --purge               same as --purge-dictionary
  -h, --help            show this help

Without --force, uninstall needs a terminal to confirm.
USAGE
}

FORCE=false
DICT_CHOICE=""  # keep | purge | "" (ask; keep when nobody can be asked)
set_dict_choice() {
    if [ -n "$DICT_CHOICE" ] && [ "$DICT_CHOICE" != "$1" ]; then
        echo "--keep-dictionary and --purge-dictionary can't be combined." >&2
        exit 2
    fi
    DICT_CHOICE=$1
}
for arg in "$@"; do
    case "$arg" in
        -f|--force) FORCE=true ;;
        --keep-dictionary) set_dict_choice keep ;;
        --purge-dictionary|--purge) set_dict_choice purge ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

# Interactive means a person at a terminal who didn't pass --force. Scripted
# and CI runs get no prompts, and the flags decide (MCC-200).
INTERACTIVE=false
if [ "$FORCE" != true ] && [ -t 0 ]; then
    INTERACTIVE=true
fi
if [ "$FORCE" != true ] && [ "$INTERACTIVE" != true ]; then
    # There is no one to confirm with, and removing everything unasked is
    # the wrong default. Nothing has been changed yet.
    fail "Not running in a terminal, so the uninstall can't be confirmed. For a scripted uninstall, use --force (the dictionary is kept unless you add --purge-dictionary)."
fi

# ── Locate the dictionary (MCC-128, MCC-200) ──
# A custom dictionary.path in config.yaml wins; read it before the config
# is removed. Uses the system python3 (the venv may already be gone).
DICT_PATH=$(dictionary_path)
DICT_DISPLAY="${DICT_PATH/#$HOME/\~}"
inspect_dictionary "$DICT_PATH"
if [ "$DICT_STATE" = ok ]; then
    DICT_SUMMARY=$(describe_dictionary "$DICT_PATH")
else
    DICT_SUMMARY="$DICT_DISPLAY (unreadable: ${DICT_PROBLEM:-unknown})"
fi

# ── Check for running instances ──
# APP_PATTERN (scripts/install-lib.sh) matches only this HOME's launcher
# invocation, so unrelated processes that mention the repo are safe.
if app_running; then
    warn "Verbal Code appears to be running."
    if [ "$FORCE" = true ]; then
        info "Stopping running instances..."
        stop_app || warn "Some instances did not stop"
        ok "Stopped"
    else
        read -rp "Kill running instances? [y/N] " KILL_CHOICE || KILL_CHOICE=""
        if [[ "${KILL_CHOICE,,}" == "y" ]]; then
            stop_app || warn "Some instances did not stop"
            ok "Stopped"
        else
            warn "Continuing with uninstall — running instance may behave unexpectedly"
        fi
    fi
fi

# ── Dictionary: keep or delete ──
# Keep is the default everywhere: on Enter, on any answer except an
# explicit delete, and whenever there is no one to ask. A delete has to be
# confirmed by typing "delete", because misreading a prompt would destroy
# curated data.
confirm_dictionary_delete() {
    local answer
    echo ""
    warn "This permanently deletes your dictionary: $DICT_PATH"
    warn "It cannot be undone."
    read -rp "Type 'delete' to confirm, or press Enter to keep it: " answer || answer=""
    [ "$answer" = delete ]
}

if [ "$DICT_STATE" = missing ]; then
    DICT_CHOICE=""
else
    if [ "$INTERACTIVE" = true ] && [ -z "$DICT_CHOICE" ]; then
        echo ""
        info "Your dictionary: $DICT_SUMMARY"
        read -rp "Keep it for a later reinstall, or delete it? [K]eep / [d]elete: " ANSWER \
            || ANSWER=""
        case "${ANSWER,,}" in
            d|delete) DICT_CHOICE=purge ;;
            *) DICT_CHOICE=keep ;;
        esac
    fi
    if [ "$DICT_CHOICE" = purge ] && [ "$INTERACTIVE" = true ] \
        && ! confirm_dictionary_delete; then
        info "Keeping your dictionary."
        DICT_CHOICE=keep
    fi
    DICT_CHOICE=${DICT_CHOICE:-keep}
fi
KEEP_DICT=false
if [ "$DICT_CHOICE" = keep ]; then
    KEEP_DICT=true
fi

# ── Confirmation ──
if [ "$FORCE" != true ]; then
    echo ""
    if [ "$DICT_CHOICE" = purge ]; then
        warn "This will remove Verbal Code and all its data, including your dictionary."
    elif [ "$KEEP_DICT" = true ]; then
        warn "This will remove Verbal Code and its data."
        info "Your dictionary ($DICT_DISPLAY) will be kept."
    else
        warn "This will remove Verbal Code and all its data."
    fi
    read -rp "Continue? [y/N] " CONFIRM || CONFIRM=""
    if [[ "${CONFIRM,,}" != "y" ]]; then
        info "Aborted. Nothing was removed."
        exit 0
    fi
    echo ""
fi

REMOVED=()
SKIPPED=()

# ── Remove launcher ──
if [ -f "$LAUNCHER" ]; then
    rm -f "$LAUNCHER"
    ok "Removed launcher: ~/.local/bin/verbal-code"
    REMOVED+=("launcher")
else
    SKIPPED+=("launcher (not found)")
fi

# ── Remove desktop entry ──
if [ -f "$DESKTOP_FILE" ]; then
    rm -f "$DESKTOP_FILE"
    ok "Removed desktop entry: ~/.local/share/applications/verbal-code.desktop"
    REMOVED+=("desktop entry")
else
    SKIPPED+=("desktop entry (not found)")
fi

# ── Remove icon ──
if [ -f "$ICON_FILE" ]; then
    rm -f "$ICON_FILE"
    ok "Removed icon: ~/.local/share/icons/hicolor/scalable/apps/verbal-code.svg"
    REMOVED+=("icon")
else
    SKIPPED+=("icon (not found)")
fi

gtk-update-icon-cache -f -t "$ICON_THEME_DIR" 2>/dev/null || true
update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true

# ── Remove venv (and the version stamp with its GPU backend marker, the
# ROCm CTranslate2 wheel cache and any leftover update backup: all under
# $VC_DATA_DIR) ──
if [ -d "$VC_DATA_DIR" ]; then
    rm -rf "$VC_DATA_DIR"
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
if [ "$DICT_CHOICE" = purge ]; then
    rm -f "$DICT_PATH"
    if [ -e "$DICT_PATH" ]; then
        warn "Could not delete the dictionary: $DICT_DISPLAY"
    else
        ok "Deleted dictionary: $DICT_DISPLAY"
        REMOVED+=("dictionary")
    fi
fi

# ── Remove cache (sherpa-onnx and vosk models, icons) ──
if [ -d "$CACHE_DIR" ]; then
    rm -rf "$CACHE_DIR"
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
    "$HOME"/.cache/huggingface/hub/models--OpenVoiceOS--nvidia-parakeet-*
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
        read -rp "Remove model cache? [y/N] " REMOVE_HF || REMOVE_HF=""
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
# What happened to the dictionary, either way (MCC-200).
echo ""
if [ "$KEEP_DICT" = true ]; then
    ok "Kept your dictionary: $DICT_SUMMARY"
    info "Reinstalling picks it up automatically. To delete it: ./uninstall.sh --purge-dictionary"
elif [ "$DICT_CHOICE" = purge ] && [ ! -e "$DICT_PATH" ]; then
    ok "Deleted your dictionary: $DICT_SUMMARY. This can't be undone."
elif [ "$DICT_CHOICE" = purge ]; then
    warn "Your dictionary is still at $DICT_DISPLAY: it could not be deleted."
else
    info "No dictionary found at $DICT_DISPLAY; nothing to keep."
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
