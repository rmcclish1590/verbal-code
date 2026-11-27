# shellcheck shell=bash
# Variables set here are read by the scripts that source this file.
# shellcheck disable=SC2034
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
# The verified ROCm CTranslate2 wheel (MCC-195), kept so update.sh can
# reinstall it without a download. Under the app's data dir, not CACHE_DIR:
# snapshot_user_data lists CACHE_DIR as user data, and update.sh must not
# see its own wheel there as a user-data change (MCC-196). The pin itself
# lives in verbal_code/ct2_backend.py.
WHEEL_CACHE_DIR="$VC_DATA_DIR/wheels"

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

# The stamp also carries the GPU backend marker (MCC-195): gpu_backend=
# rocm|cuda|cpu, and for rocm the wheel file and whether the launcher must
# put /opt/rocm/lib on LD_LIBRARY_PATH. Without a backend argument the
# marker lines are left out, as on installs that predate GPU support.
write_stamp() {  # version commit [gpu_backend [ct2_wheel [rocm_ld_path]]]
    mkdir -p "$VC_DATA_DIR"
    {
        printf 'version=%s\ncommit=%s\ninstalled=%s\n' "$1" "$2" "$(date -Is)"
        if [ -n "${3:-}" ]; then
            printf 'gpu_backend=%s\n' "$3"
        fi
        if [ "${3:-}" = rocm ] && [ -n "${4:-}" ]; then
            printf 'ct2_wheel=%s\n' "$4"
        fi
        if [ "${3:-}" = rocm ] && [ "${5:-0}" = 1 ]; then
            printf 'rocm_ld_path=1\n'
        fi
    } > "$STAMP_FILE.new"
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
    pip_install --quiet -e "$1$2"
    pip_install --quiet pytest ruff
    check_dependencies \
        || fail "Verbal Code's Python dependencies conflict (listed above). Re-run the installer; if that doesn't fix it, report it."
}

# ── Dependency conflicts (MCC-202) ──
# The venv uses --system-site-packages (the tray needs the system's GTK
# bindings), so pip also sees every distro Python package, and those can
# conflict among themselves: Linux Mint 22's yt-dlp 2024.4.9 wants
# websockets>=12 next to its websockets 10.4. pip then prints
# "ERROR: pip's dependency resolver does not currently take into account
# ..." after any install that touches one of yt-dlp's dependencies (brotli,
# on a fresh venv). That is not Verbal Code's problem and must not fail a
# step. verbal_code.depcheck (also used by the GPU backend step) counts
# only conflicts inside Verbal Code's own dependency tree.

# Removes pip's resolver-conflict block from pip's stderr on stdin;
# check_dependencies reports what matters instead.
strip_resolver_conflicts() {
    awk '
        /^ERROR: pip.s dependency resolver does not currently take into account/ { skip = 1; next }
        skip && / (requires|has requirement|is not supported)/ { next }
        { skip = 0; print }
    '
}

# pip install "$@" in the venv, without the resolver-conflict block. When
# pip itself fails, its whole output is shown.
pip_install() {
    local err rc=0
    err=$(mktemp)
    "$PYTHON" -m pip install "$@" 2>"$err" || rc=$?
    if [ "$rc" -ne 0 ]; then
        cat "$err" >&2
    else
        strip_resolver_conflicts < "$err" >&2
    fi
    rm -f "$err"
    return "$rc"
}

# Returns 1 when Verbal Code's own dependency tree has a conflict (each is
# printed). A conflict among unrelated packages prints one note, unless
# --quiet is given, and passes.
check_dependencies() {  # [--quiet]
    local note rc=0 args=()
    if [ "${1:-}" = --quiet ]; then
        args=(--no-note)
    fi
    note=$(cd / && "$PYTHON" -m verbal_code.depcheck "${args[@]}") || rc=$?
    case "$rc" in
        0)
            if [ -n "$note" ]; then
                info "$note"
            fi
            ;;
        1) return 1 ;;
        *) warn "Could not check the Python dependencies (see above); continuing." ;;
    esac
}

# The installed app starts, its model catalog loads, and its dependencies
# are consistent (after update.sh's GPU backend step, too). Runs from /
# because `python -m` puts the working directory on sys.path, and from a
# checkout that would import ./verbal_code instead of what was just
# installed.
health_check() {
    (cd / && "$PYTHON" -m verbal_code --version >/dev/null \
        && "$PYTHON" -m verbal_code --list-models >/dev/null) \
        && check_dependencies --quiet
}

# ── GPU backend (MCC-195) ──
# CTranslate2 (Whisper's runtime) comes from PyPI as a CUDA build; an AMD
# GPU needs the ROCm build pinned in verbal_code/ct2_backend.py, which is
# the one package installed by file rather than through pyproject.toml.
# Every helper runs from / so a checkout can't shadow the installed code.

# Sets GPU_BACKEND (rocm|cuda|cpu) and GPU_LD_PATH (1 when the ROCm libs
# load only with /opt/rocm/lib on LD_LIBRARY_PATH) from the installed
# app's detection. VERBAL_CODE_GPU_BACKEND=rocm|cuda|cpu overrides it.
detect_gpu_backend() {
    local line
    line=$(cd / && "$PYTHON" -m verbal_code --gpu-detect 2>/dev/null) || line=""
    GPU_BACKEND=$(sed -n 's/^backend=\([a-z]*\).*/\1/p' <<< "$line")
    GPU_BACKEND=${GPU_BACKEND:-cpu}
    GPU_LD_PATH=0
    if [[ " $line " == *" ld_path=1 "* ]]; then
        GPU_LD_PATH=1
    fi
}

# Prints the venv's actual CTranslate2 build, read from the installed
# library (not the marker): rocm, pypi or missing.
installed_ct2_backend() {
    local flavor
    flavor=$(cd / && "$PYTHON" -m verbal_code.ct2_backend flavor 2>/dev/null) \
        || flavor=missing
    echo "${flavor%% *}"
}

# Puts the build for backend $1 in the venv and verifies a GPU is visible.
# Sets CT2_BACKEND (what was achieved), CT2_WHEEL and ROCM_LD_PATH for
# write_stamp. A failure falls back to the PyPI wheel (CPU) with a warning;
# with "strict" as $2 it returns 1 instead and leaves the rollback to the
# caller (update.sh).
install_ct2_backend() {  # rocm|cuda|cpu [strict]
    local backend=$1 strict=${2:-} wheel rc=0 ld_args=() install_args=()
    CT2_BACKEND=cpu
    CT2_WHEEL=""
    ROCM_LD_PATH=0
    if [ "${GPU_LD_PATH:-0}" = 1 ]; then
        ld_args=(--ld-library-path)
    fi
    case "$backend" in
        rocm)
            if [ -n "$strict" ]; then
                install_args=(--no-fallback)
            fi
            # Already the pinned build and working (a re-run): keep it.
            if (cd / && "$PYTHON" -m verbal_code.ct2_backend is-pinned-rocm) \
                && (cd / && "$PYTHON" -m verbal_code.ct2_backend verify \
                    "${ld_args[@]}" 2>/dev/null); then
                wheel=$(cd / && "$PYTHON" -m verbal_code.ct2_backend wheel-name)
            else
                info "Installing the ROCm build of CTranslate2 (pinned, hash-verified)..."
                wheel=$(cd / && "$PYTHON" -m verbal_code.ct2_backend install-rocm \
                    --cache-dir "$WHEEL_CACHE_DIR" "${ld_args[@]}" "${install_args[@]}") \
                    || rc=$?
            fi
            if [ "$rc" -eq 0 ]; then
                CT2_BACKEND=rocm
                CT2_WHEEL=$wheel
                ROCM_LD_PATH=${GPU_LD_PATH:-0}
                ok "GPU backend: rocm ($wheel)"
            elif [ -n "$strict" ]; then
                return 1
            else
                warn "Whisper will run on CPU (see the reason above)."
            fi
            ;;
        cuda)
            if (cd / && "$PYTHON" -m verbal_code.ct2_backend verify); then  # PyPI wheel
                CT2_BACKEND=cuda
                ok "GPU backend: cuda (PyPI CTranslate2)"
            elif [ -n "$strict" ]; then
                return 1
            else
                warn "NVIDIA GPU not usable by CTranslate2; Whisper will run on CPU."
            fi
            ;;
        cpu)
            # A ROCm build left from an earlier install can't import without
            # its runtime, which would break the Whisper engine.
            if [ "$(installed_ct2_backend)" = rocm ]; then
                info "Replacing the ROCm build of CTranslate2 with PyPI's..."
                (cd / && "$PYTHON" -m verbal_code.ct2_backend install-pypi) \
                    || { [ -n "$strict" ] && return 1; warn "Could not reinstall PyPI's CTranslate2"; }
            fi
            ;;
    esac
}

# update.sh (MCC-196): keep the backend the install recorded. A deploy's
# pip run can swap the ROCm build back to PyPI's (a ctranslate2 bump, a
# new Python tag), so the venv's actual build is checked, not the marker.
# Sets CT2_BACKEND, CT2_WHEEL and ROCM_LD_PATH for write_stamp; returns 1
# when the ROCm build can't be put back, so the update rolls back instead
# of silently dropping to CPU. Never switches backends.
ensure_ct2_backend() {
    local marker
    marker=$(read_stamp gpu_backend)
    CT2_BACKEND=$marker
    CT2_WHEEL=$(read_stamp ct2_wheel)
    GPU_LD_PATH=$(read_stamp rocm_ld_path)
    GPU_LD_PATH=${GPU_LD_PATH:-0}
    ROCM_LD_PATH=$GPU_LD_PATH
    case "$marker" in
        rocm) install_ct2_backend rocm strict || return 1 ;;
        cuda)
            # The PyPI build is the CUDA build; nothing to reinstall. A
            # driver problem isn't the update's to fix, so only warn.
            if ! (cd / && "$PYTHON" -m verbal_code.ct2_backend verify 2>/dev/null); then
                warn "The NVIDIA GPU isn't usable right now; run verbal-code --doctor"
            fi
            ;;
    esac
}

# What ensure_ct2_backend would do, for update.sh --dry-run: "keep",
# "reinstall ROCm wheel" or "none". Changes nothing.
ct2_backend_plan() {
    case "$(read_stamp gpu_backend)" in
        rocm)
            if (cd / && "$PYTHON" -m verbal_code.ct2_backend is-pinned-rocm 2>/dev/null); then
                echo "keep (ROCm wheel)"
            else
                echo "reinstall ROCm wheel"
            fi
            ;;
        cuda) echo "keep (PyPI CUDA build)" ;;
        *) echo none ;;
    esac
}

# The doctor's one-line verdict (R9.6), or nothing if it can't run.
doctor_verdict() {
    (cd / && "$PYTHON" -m verbal_code --doctor 2>/dev/null) \
        | sed -n 's/^Verdict: //p' || true
}

# ── Launcher, desktop entry and icon ──
# With ROCM_LD_PATH=1 (the ROCm backend, whose libraries resolve only from
# /opt/rocm/lib because ROCm was installed without an ld.so.conf.d entry;
# detected at install time and kept in the stamp) the launcher puts that
# directory on LD_LIBRARY_PATH. Everyone else gets the plain launcher
# (MCC-198).
# shellcheck disable=SC2016  # the $-expressions belong to the launcher
render_launcher() {
    echo '#!/usr/bin/env bash'
    echo 'VENV="$HOME/.local/share/verbal-code/venv"'
    if [ "${ROCM_LD_PATH:-0}" = 1 ]; then
        echo '# The ROCm build of CTranslate2 loads its HIP libraries from here.'
        echo 'export LD_LIBRARY_PATH="/opt/rocm/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"'
    fi
    echo 'exec "$VENV/bin/python" -m verbal_code "$@"'
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

# ── The dictionary (MCC-128, MCC-200) ──
# The user's curated corrections: the one piece of user data that can't be
# regenerated, so install reports it and uninstall asks before deleting it.

# Prints where the dictionary lives: a custom dictionary.path from
# config.yaml, else ~/.config/verbal-code/dictionary.json. Uses the system
# python3, so it works before the venv exists and after it is removed.
dictionary_path() {
    local custom
    custom=$(python3 - "$CONFIG_DIR/config.yaml" 2>/dev/null <<'PY' || true
import os, sys, yaml
with open(sys.argv[1]) as f:
    cfg = yaml.safe_load(f) or {}
path = (cfg.get("dictionary") or {}).get("path")
if path:
    print(os.path.expanduser(str(path)))
PY
)
    echo "${custom:-$CONFIG_DIR/dictionary.json}"
}

# Reads the dictionary at $1 the way the app does, without changing it.
# Sets DICT_STATE (missing | ok | invalid), DICT_ENTRIES (ok only),
# DICT_MODIFIED (last-modified date) and DICT_PROBLEM (invalid only).
inspect_dictionary() {  # path
    local result
    DICT_STATE=missing
    DICT_ENTRIES=0
    DICT_MODIFIED=""
    DICT_PROBLEM=""
    [ -e "$1" ] || return 0
    result=$(python3 - "$1" 2>/dev/null <<'PY'
import datetime, json, os, sys
path = sys.argv[1]
try:
    modified = datetime.datetime.fromtimestamp(os.path.getmtime(path))
    stamp = modified.strftime("%Y-%m-%d %H:%M")
except OSError:
    stamp = "unknown"
try:
    with open(path) as f:
        raw = json.load(f) or {}
    entries = raw.get("entries", [])
    if not isinstance(entries, list) or not all(
        isinstance(e, dict) and isinstance(e.get("term"), str) for e in entries
    ):
        raise ValueError("unexpected structure")
except (OSError, ValueError, AttributeError) as exc:
    problem = "not valid JSON" if isinstance(exc, json.JSONDecodeError) else (
        str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
    print(f"invalid\t{stamp}\t{problem}")
else:
    print(f"ok\t{stamp}\t{len(entries)}")
PY
) || result=$'invalid\tunknown\tcould not be read'
    IFS=$'\t' read -r DICT_STATE DICT_MODIFIED DICT_ENTRIES <<< "$result"
    if [ "$DICT_STATE" = invalid ]; then
        DICT_PROBLEM=$DICT_ENTRIES
        DICT_ENTRIES=0
    fi
}

# "~/.config/verbal-code/dictionary.json (12 entries, last changed ...)"
describe_dictionary() {  # path  (after inspect_dictionary)
    local entries="$DICT_ENTRIES entries"
    [ "$DICT_ENTRIES" = 1 ] && entries="1 entry"
    echo "${1/#$HOME/\~} ($entries, last changed $DICT_MODIFIED)"
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
