# shellcheck shell=bash
# Shared by install.sh, update.sh and uninstall.sh (MCC-193). This is the one
# definition of where Verbal Code's files live, which of them are
# application files (built from this repo and safe to replace) and which are
# user data (never touched by install or update), plus the build and deploy
# steps that install and update must not diverge on.
#
# Source it after setting `set -euo pipefail`; it only defines variables and
# functions.

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail()  { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }

# ── Locations ──
VC_DATA_DIR="$HOME/.local/share/verbal-code"
VENV_DIR="$VC_DATA_DIR/venv"
PYTHON="$VENV_DIR/bin/python"
CONFIG_DIR="$HOME/.config/verbal-code"
CACHE_DIR="$HOME/.cache/verbal-code"
HF_HUB_DIR="$HOME/.cache/huggingface/hub"
LAUNCHER="$HOME/.local/bin/verbal-code"
DESKTOP_DIR="$HOME/.local/share/applications"
DESKTOP_FILE="$DESKTOP_DIR/verbal-code.desktop"
ICON_THEME_DIR="$HOME/.local/share/icons/hicolor"
ICON_FILE="$ICON_THEME_DIR/scalable/apps/verbal-code.svg"
# Version and commit of the last install or update, for update's summary.
STAMP_FILE="$VC_DATA_DIR/installed-version"
# update.sh keeps one backup here only while it deploys; it is gone after a
# successful update or a rollback. Its presence at start means an earlier
# update was killed mid-deploy.
UPDATE_BACKUP_DIR="$VC_DATA_DIR/update-backup"

# Application files: install and update (re)write these. The venv is one
# too; the app code itself is the repo, installed editable.
APP_FILES=("$LAUNCHER" "$DESKTOP_FILE" "$ICON_FILE" "$STAMP_FILE")

# User data: install and update never modify these; only uninstall removes
# them (and it keeps the dictionary unless --purge, MCC-128).
#   $CONFIG_DIR   config.yaml (incl. saved hotkeys, MCC-32, and the selected
#                 model, MCC-33), dictionary.json, a log kept there
#   a custom dictionary.path or logging.file set in config.yaml
#   $CACHE_DIR    sherpa-onnx and vosk models, tray icons
#   $HF_HUB_DIR   whisper, moonshine and parakeet models
USER_DATA_DIRS=("$CONFIG_DIR" "$CACHE_DIR" "$HF_HUB_DIR")

# Optional extras (pyproject.toml [project.optional-dependencies]) and the
# distribution that marks each one as installed.
declare -A EXTRA_PACKAGES=([moonshine]=useful-moonshine-onnx [vosk]=vosk)

# ── System packages ──
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
add_indicator_package() {
    if apt-cache show gir1.2-ayatanaappindicator3-0.1 &>/dev/null; then
        APT_PACKAGES+=(gir1.2-ayatanaappindicator3-0.1)
    else
        APT_PACKAGES+=(gir1.2-appindicator3-0.1)
    fi
}

# Prints the APT_PACKAGES that aren't installed, one per line.
missing_apt_packages() {
    local pkg
    for pkg in "${APT_PACKAGES[@]}"; do
        dpkg -s "$pkg" &>/dev/null || echo "$pkg"
    done
}

install_missing_apt_packages() {
    local missing
    mapfile -t missing < <(missing_apt_packages)
    if [ ${#missing[@]} -gt 0 ]; then
        info "Installing system packages: ${missing[*]}"
        sudo apt install -y "${missing[@]}"
        ok "System packages installed"
    else
        ok "All system packages already installed"
    fi
}

# ── The running app ──
# Match only this HOME's launcher invocation. A broad pattern like
# "python.*verbal_code" would also match unrelated processes whose command
# line merely mentions the repo (an editor's language server, a pytest run),
# and anchoring on $VENV_DIR keeps a scratch-HOME test run away from the
# real instance.
APP_PATTERN="$(printf '%s' "$VENV_DIR/bin/python -m verbal_code" | sed 's/[][\.*^$+?(){}|]/\\&/g')"

app_running() {
    pgrep -f "$APP_PATTERN" &>/dev/null
}

# SIGTERM first (the app shuts down cleanly on it), SIGKILL after 5 s.
stop_app() {
    local _
    pkill -TERM -f "$APP_PATTERN" 2>/dev/null || true
    for _ in $(seq 50); do
        app_running || return 0
        sleep 0.1
    done
    pkill -KILL -f "$APP_PATTERN" 2>/dev/null || true
    sleep 0.5
    ! app_running
}

# Starts the app detached from this terminal, from $HOME like a desktop
# launch (a checkout as the working directory would shadow the install).
# Fails without a graphical session to attach the tray to.
start_app() {
    if [ -z "${DISPLAY:-}" ] && [ -z "${WAYLAND_DISPLAY:-}" ]; then
        return 1
    fi
    (cd "$HOME" && setsid -f "$LAUNCHER" >/dev/null 2>&1 </dev/null)
}

# ── Versions ──
# The version of the source tree in $1.
source_version() {
    sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$1/verbal_code/__init__.py"
}

# The short commit of $1, "-dirty" with uncommitted tracked changes (they
# are live too: the install is editable), or "unknown" outside git.
source_commit() {
    local commit
    if ! commit=$(git -C "$1" rev-parse --short HEAD 2>/dev/null); then
        echo unknown
        return
    fi
    if [ -n "$(git -C "$1" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
        commit="$commit-dirty"
    fi
    echo "$commit"
}

write_stamp() {  # version commit
    mkdir -p "$VC_DATA_DIR"
    printf 'version=%s\ncommit=%s\ninstalled=%s\n' "$1" "$2" "$(date -Is)" \
        > "$STAMP_FILE.new"
    mv -f "$STAMP_FILE.new" "$STAMP_FILE"
}

read_stamp() {  # key
    [ -f "$STAMP_FILE" ] && sed -n "s/^$1=//p" "$STAMP_FILE"
    return 0
}

# ── Python package ──
# Prints the extras spec ("[vosk]", "[moonshine,vosk]" or nothing) matching
# the optional engines already in the venv, so an update keeps them.
detect_extras() {
    local found=() extra
    for extra in $(printf '%s\n' "${!EXTRA_PACKAGES[@]}" | sort); do
        if "$PYTHON" -m pip show --quiet "${EXTRA_PACKAGES[$extra]}" &>/dev/null; then
            found+=("$extra")
        fi
    done
    if [ ${#found[@]} -gt 0 ]; then
        local IFS=,
        echo "[${found[*]}]"
    fi
}

# Resolves the dependencies of repo $1 with extras $2 without installing
# anything, and prints pip's "Would install ..." package list.
resolve_package() {
    local out
    if ! out=$("$PYTHON" -m pip install --dry-run -e "$1$2" 2>&1); then
        echo "$out" | tail -n 20 >&2
        return 1
    fi
    echo "$out" | sed -n 's/^Would install //p'
}

# The build step (MCC-132): a fresh wheel from the current source, with
# stale build artifacts removed first, then a dependency resolve. Nothing in
# the venv changes, so a failure here leaves the existing install intact.
# The deploy installs editable from the same source; the wheel proves that
# source builds before anything is replaced. Sets PLANNED_PACKAGES.
build_package() {  # repo extras
    local repo=$1 extras=$2 wheel_dir
    info "Building verbal-code from $repo..."
    rm -rf "$repo/build" "$repo"/*.egg-info
    wheel_dir=$(mktemp -d)
    if ! "$PYTHON" -m pip wheel --quiet --no-deps --wheel-dir "$wheel_dir" "$repo"; then
        rm -rf "$wheel_dir"
        fail "Build failed: see the pip output above. Nothing was installed or replaced."
    fi
    rm -rf "$wheel_dir"
    if ! PLANNED_PACKAGES=$(resolve_package "$repo" "$extras"); then
        fail "Dependencies did not resolve: see the pip output above. Nothing was installed or replaced."
    fi
    ok "Build succeeded"
}

# Installs repo $1 with extras $2 into the venv. Installing through the
# package applies the version pins in pyproject.toml, and pip only replaces
# distributions whose version changes.
deploy_package() {  # repo extras
    "$PYTHON" -m pip install --quiet -e "$1$2"
    "$PYTHON" -m pip install --quiet pytest ruff
}

# The installed app starts and its model catalog loads. Runs from / because
# `python -m` puts the working directory on sys.path, and from a checkout
# that would import ./verbal_code instead of what was just installed.
health_check() {
    (cd / && "$PYTHON" -m verbal_code --version >/dev/null \
        && "$PYTHON" -m verbal_code --list-models >/dev/null)
}

# ── Launcher, desktop entry and icon ──
render_launcher() {
    cat << 'LAUNCHER_EOF'
#!/usr/bin/env bash
VENV="$HOME/.local/share/verbal-code/venv"
exec "$VENV/bin/python" -m verbal_code "$@"
LAUNCHER_EOF
}

render_desktop_entry() {
    cat << 'DESKTOP_EOF'
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
}

# Writes the launcher, desktop entry and icon from repo $1, replacing only
# files whose content changed (each atomically). With "check" as $2 it only
# reports. Sets APP_FILES_CHANGED and APP_FILES_UNCHANGED to labels.
install_app_files() {  # repo [check]
    local repo=$1 mode=${2:-write} staging
    APP_FILES_CHANGED=()
    APP_FILES_UNCHANGED=()
    staging=$(mktemp -d)
    render_launcher > "$staging/launcher"
    render_desktop_entry > "$staging/desktop"
    _place_file "$staging/launcher" "$LAUNCHER" launcher 755 "$mode"
    _place_file "$staging/desktop" "$DESKTOP_FILE" "desktop entry" 644 "$mode"
    _place_file "$repo/assets/verbal-code.svg" "$ICON_FILE" icon 644 "$mode"
    rm -rf "$staging"
    if [ "$mode" = write ] && [ ${#APP_FILES_CHANGED[@]} -gt 0 ]; then
        gtk-update-icon-cache -f -t "$ICON_THEME_DIR" 2>/dev/null || true
        update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
    fi
}

_place_file() {  # src dest label mode write|check
    if [ -f "$2" ] && cmp -s "$1" "$2"; then
        APP_FILES_UNCHANGED+=("$3")
        return
    fi
    APP_FILES_CHANGED+=("$3")
    if [ "$5" = write ]; then
        mkdir -p "$(dirname "$2")"
        cp "$1" "$2.new"
        chmod "$4" "$2.new"
        mv -f "$2.new" "$2"
    fi
}

# ── User data ──
# Prints the custom dictionary.path and logging.file from config.yaml, one
# per line. Uses the system python3 so it works without the venv.
config_user_files() {
    python3 - "$CONFIG_DIR/config.yaml" 2>/dev/null <<'PY' || true
import os, sys, yaml
with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f) or {}
for section, key in (("dictionary", "path"), ("logging", "file")):
    value = (cfg.get(section) or {}).get(key)
    if value:
        print(os.path.expanduser(str(value)))
PY
}

# Prints a fingerprint of the user data: a checksum of every file in the
# config directory and of a custom dictionary or log file, plus the model
# entries in the caches (listed, not hashed: they are gigabytes).
snapshot_user_data() {
    local extra
    if [ -d "$CONFIG_DIR" ]; then
        find "$CONFIG_DIR" -type f -print0 | sort -z | xargs -0 -r sha256sum
    fi
    while IFS= read -r extra; do
        if [ -f "$extra" ] && [[ "$extra" != "$CONFIG_DIR"/* ]]; then
            sha256sum "$extra"
        fi
    done < <(config_user_files)
    local dir
    for dir in "$CACHE_DIR" "$HF_HUB_DIR"; do
        if [ -d "$dir" ]; then
            find "$dir" -mindepth 1 -maxdepth 2 | sort
        fi
    done
}
