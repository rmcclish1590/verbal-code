#!/usr/bin/env bash
# Update an existing Verbal Code install in place (MCC-193): build the
# current source, then replace only the application files, without an
# uninstall. User data (config, saved hotkeys and model, dictionary, logs,
# downloaded models) is never touched; see scripts/install-lib.sh for the
# split. A failed build changes nothing; a failed or interrupted deploy rolls
# back to the previous version.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=scripts/install-lib.sh
source "$SCRIPT_DIR/scripts/install-lib.sh"

usage() {
    cat <<EOF
Usage: ./update.sh [--pull] [--dry-run] [--no-restart]

Builds the code in this checkout and deploys it over the existing install.

  --pull        fast-forward this checkout to its upstream branch first
  --dry-run     show what would be updated, and change nothing
  --no-restart  stop a running Verbal Code but don't start it again
  -h, --help    show this help
EOF
}

PULL=false
DRY_RUN=false
RESTART=true
for arg in "$@"; do
    case "$arg" in
        --pull) PULL=true ;;
        --dry-run) DRY_RUN=true ;;
        --no-restart) RESTART=false ;;
        -h|--help) usage; exit 0 ;;
        *) usage >&2; exit 2 ;;
    esac
done

# ── Preflight ──
if [ ! -x "$PYTHON" ]; then
    fail "No Verbal Code installation found at ${VENV_DIR/#$HOME/\~}. Run ./install.sh to install it first."
fi

OLD_VERSION=$(read_stamp version)
OLD_COMMIT=$(read_stamp commit)
if [ -z "$OLD_VERSION" ]; then
    # Installed before update stamps existed: the venv's metadata still
    # records the version.
    OLD_VERSION=$("$PYTHON" -m pip show verbal-code 2>/dev/null | sed -n 's/^Version: //p')
fi
OLD_VERSION=${OLD_VERSION:-unknown}
OLD_COMMIT=${OLD_COMMIT:-unknown}
EXTRAS=$(detect_extras)
add_indicator_package

APP_WAS_RUNNING=false
if app_running; then
    APP_WAS_RUNNING=true
fi

# ── Dry run ──
if [ "$DRY_RUN" = true ]; then
    info "Dry run: nothing will be changed."
    echo ""
    if [ -d "$UPDATE_BACKUP_DIR" ]; then
        warn "An earlier update did not finish; a real run restores its backup first."
    fi
    NEW_COMMIT=$(source_commit "$SCRIPT_DIR")
    if [ "$PULL" = true ]; then
        if git -C "$SCRIPT_DIR" fetch --quiet \
            && UPSTREAM=$(git -C "$SCRIPT_DIR" rev-parse --short '@{u}' 2>/dev/null); then
            NEW_COMMIT="$UPSTREAM (after --pull)"
        else
            warn "Could not fetch an upstream branch for --pull"
        fi
    fi
    info "Installed:  $OLD_VERSION ($OLD_COMMIT)"
    info "This build: $(source_version "$SCRIPT_DIR") ($NEW_COMMIT)"
    info "Extras kept: ${EXTRAS:-none}"
    mapfile -t MISSING < <(missing_apt_packages)
    info "System packages to install: ${MISSING[*]:-none}"
    if PLANNED=$(resolve_package "$SCRIPT_DIR" "$EXTRAS"); then
        info "Python packages to install or upgrade: ${PLANNED:-none}"
        if [ "$PULL" = true ]; then
            info "(resolved for the current checkout, before --pull)"
        fi
    else
        warn "Dependencies do not resolve for this checkout; a real run would stop here."
    fi
    info "GPU backend: $(ct2_backend_plan)"
    # The launcher keeps the recorded LD_LIBRARY_PATH need (MCC-198).
    if [ "$(read_stamp gpu_backend)" = rocm ]; then
        ROCM_LD_PATH=$(read_stamp rocm_ld_path)
    fi
    install_app_files "$SCRIPT_DIR" check
    info "Files to replace: ${APP_FILES_CHANGED[*]:-none}"
    info "Files already current: ${APP_FILES_UNCHANGED[*]:-none}"
    if [ "$APP_WAS_RUNNING" = true ]; then
        if [ "$RESTART" = true ]; then
            info "Verbal Code is running: it would be stopped, then restarted."
        else
            info "Verbal Code is running: it would be stopped and left stopped."
        fi
    fi
    info "Never touched: config, saved hotkeys and model, dictionary, logs, downloaded models"
    exit 0
fi

# ── Rollback ──
# Everything after this point runs as one transaction: on any failure,
# including Ctrl-C, the EXIT trap puts back what changed.
BACKED_UP=false
DEPLOYED=false
PULLED=false
PRE_PULL_HEAD=""
STOPPED=false
WORK_DIR=$(mktemp -d)

restore_backup() {
    local i
    rm -rf "$VENV_DIR"
    mv "$UPDATE_BACKUP_DIR/venv" "$VENV_DIR"
    for i in "${!APP_FILES[@]}"; do
        if [ -e "$UPDATE_BACKUP_DIR/files/$i" ]; then
            mkdir -p "$(dirname "${APP_FILES[$i]}")"
            mv -f "$UPDATE_BACKUP_DIR/files/$i" "${APP_FILES[$i]}"
        else
            rm -f "${APP_FILES[$i]}"
        fi
    done
    rm -rf "$UPDATE_BACKUP_DIR"
    gtk-update-icon-cache -f -t "$ICON_THEME_DIR" 2>/dev/null || true
    update-desktop-database "$DESKTOP_DIR" 2>/dev/null || true
}

restart_app() {
    if start_app; then
        ok "Verbal Code restarted"
    else
        warn "No graphical session found; start Verbal Code yourself: verbal-code"
    fi
}

on_exit() {
    local status=$?
    trap '' INT TERM HUP
    if [ "$status" -ne 0 ] && [ "$DEPLOYED" != true ]; then
        echo "" >&2
        if [ "$BACKED_UP" = true ]; then
            warn "Update failed; rolling back to the previous version..."
            restore_backup
        fi
        if [ "$PULLED" = true ]; then
            git -C "$SCRIPT_DIR" reset --quiet --keep "$PRE_PULL_HEAD" \
                || warn "Could not move the checkout back to $PRE_PULL_HEAD"
        fi
        if [ "$BACKED_UP" = true ] || [ "$PULLED" = true ]; then
            warn "Rolled back: Verbal Code $OLD_VERSION ($OLD_COMMIT) is installed, unchanged."
        else
            warn "The existing installation was not changed."
        fi
        if [ "$STOPPED" = true ]; then
            if [ "$RESTART" = true ]; then
                # Ignored signals survive exec; the app must not inherit
                # the rollback's protection against a second Ctrl-C.
                trap - INT TERM HUP
                restart_app
            else
                info "Start Verbal Code again when ready: verbal-code"
            fi
        fi
    fi
    rm -rf "$UPDATE_BACKUP_DIR.partial" "$WORK_DIR"
    exit "$status"
}
trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 129' HUP

# ── Stop the app ──
# Before anything changes: the install is editable, so even --pull alters
# the code a running instance imports lazily.
if [ "$APP_WAS_RUNNING" = true ]; then
    info "Stopping Verbal Code..."
    stop_app || fail "Could not stop the running Verbal Code; close it and run the update again."
    STOPPED=true
    ok "Stopped"
fi

# A backup left behind means an earlier update was killed mid-deploy; its
# venv may be half-updated, so put the backed-up version back first.
if [ -d "$UPDATE_BACKUP_DIR" ]; then
    warn "An earlier update did not finish; restoring the version it backed up..."
    restore_backup
    ok "Previous version restored"
fi

# ── Source ──
if [ "$PULL" = true ]; then
    if ! git -C "$SCRIPT_DIR" diff --quiet || ! git -C "$SCRIPT_DIR" diff --cached --quiet; then
        fail "--pull needs a checkout without uncommitted changes; commit or stash them first."
    fi
    git -C "$SCRIPT_DIR" rev-parse --abbrev-ref '@{u}' &>/dev/null \
        || fail "--pull: the current branch has no upstream branch."
    info "Fetching the latest code..."
    git -C "$SCRIPT_DIR" fetch --quiet
    PRE_PULL_HEAD=$(git -C "$SCRIPT_DIR" rev-parse HEAD)
    git -C "$SCRIPT_DIR" merge --quiet --ff-only '@{u}' \
        || fail "--pull: the branch has diverged from its upstream and can't fast-forward."
    if [ "$(git -C "$SCRIPT_DIR" rev-parse HEAD)" != "$PRE_PULL_HEAD" ]; then
        PULLED=true
        ok "Checkout fast-forwarded to $(git -C "$SCRIPT_DIR" rev-parse --short HEAD)"
    else
        ok "Checkout already up to date"
    fi
fi
NEW_VERSION=$(source_version "$SCRIPT_DIR")
NEW_COMMIT=$(source_commit "$SCRIPT_DIR")

# ── Build ──
install_missing_apt_packages
build_package "$SCRIPT_DIR" "$EXTRAS"

# ── Back up ──
snapshot_user_data > "$WORK_DIR/user-data.before"
info "Backing up the current install..."
mkdir -p "$UPDATE_BACKUP_DIR.partial/files"
cp -a "$VENV_DIR" "$UPDATE_BACKUP_DIR.partial/venv"
for i in "${!APP_FILES[@]}"; do
    if [ -e "${APP_FILES[$i]}" ]; then
        cp -a "${APP_FILES[$i]}" "$UPDATE_BACKUP_DIR.partial/files/$i"
    fi
done
# The rename makes the backup complete-or-absent for the restore above.
mv "$UPDATE_BACKUP_DIR.partial" "$UPDATE_BACKUP_DIR"
BACKED_UP=true

# ── Deploy ──
info "Deploying verbal-code${EXTRAS:+ with extras $EXTRAS}..."
deploy_package "$SCRIPT_DIR" "$EXTRAS"
# Before the health check: a GPU backend that can't be put back fails the
# update, and the rollback restores the working install (MCC-196).
ensure_ct2_backend \
    || fail "Could not keep the ROCm build of CTranslate2 (see above). If the ROCm runtime is gone, switch to CPU with verbal-code --doctor --fix, then update again."
install_app_files "$SCRIPT_DIR"
health_check || fail "The updated Verbal Code failed to start (verbal-code --version / --list-models)."
if [ -n "$CT2_BACKEND" ]; then
    write_stamp "$NEW_VERSION" "$NEW_COMMIT" "$CT2_BACKEND" "$CT2_WHEEL" "$ROCM_LD_PATH"
else
    write_stamp "$NEW_VERSION" "$NEW_COMMIT"
fi
DEPLOYED=true
rm -rf "$UPDATE_BACKUP_DIR"
ok "Deployed"

# ── Verify user data ──
snapshot_user_data > "$WORK_DIR/user-data.after"
if cmp -s "$WORK_DIR/user-data.before" "$WORK_DIR/user-data.after"; then
    USER_DATA_OK=true
else
    USER_DATA_OK=false
fi

# ── Summary ──
echo ""
echo "────────────────────────────────"
ok "Verbal Code updated: $OLD_VERSION ($OLD_COMMIT) → $NEW_VERSION ($NEW_COMMIT)"
info "Python packages installed or upgraded: ${PLANNED_PACKAGES:-none}"
info "Files replaced: ${APP_FILES_CHANGED[*]:-none}"
if [ "$USER_DATA_OK" = true ]; then
    ok "User data unchanged: config, saved hotkeys and model, dictionary, logs, downloaded models"
else
    warn "User data changed during the update:"
    diff "$WORK_DIR/user-data.before" "$WORK_DIR/user-data.after" >&2 || true
fi

# New options in the repo's config template that the user's config doesn't
# set. The code supplies their defaults, so this is information, not a fix:
# the user's config is never rewritten.
NEW_OPTIONS=$(python3 - "$SCRIPT_DIR/config.yaml" "$CONFIG_DIR/config.yaml" 2>/dev/null <<'PY' || true
import sys, yaml
with open(sys.argv[1]) as f:
    template = yaml.safe_load(f) or {}
with open(sys.argv[2]) as f:
    user = yaml.safe_load(f) or {}
new = []
for section, options in template.items():
    if section not in user:
        new.append(section)
    elif isinstance(options, dict) and isinstance(user[section], dict):
        new += [f"{section}.{key}" for key in options if key not in user[section]]
print(" ".join(new))
PY
)
if [ -n "$NEW_OPTIONS" ]; then
    info "Options your config doesn't set (their defaults apply; see config.yaml in the repo): $NEW_OPTIONS"
fi

# A GPU added since the install is offered, never switched to (MCC-196).
detect_gpu_backend
if [ "$GPU_BACKEND" != cpu ] && [ "${CT2_BACKEND:-cpu}" = cpu ]; then
    info "A $GPU_BACKEND-capable GPU is now detected; to use it: ./install.sh or verbal-code --doctor --fix"
fi
VERDICT=$(doctor_verdict)
if [ -n "$VERDICT" ]; then
    info "GPU: $VERDICT"
fi

if [ "$STOPPED" = true ]; then
    if [ "$RESTART" = true ]; then
        restart_app
    else
        info "Start Verbal Code again when ready: verbal-code"
    fi
fi
