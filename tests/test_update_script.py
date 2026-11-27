"""update.sh end to end (MCC-193), against a scratch HOME.

Each test copies the scripts into a throwaway git checkout and runs them
with HOME pointing at a temp dir. The venv's ``python`` is a bash stub:
``-m pip`` logs its arguments and fails on demand (``FAKE_FAIL``), and
``-m verbal_code`` with no arguments idles like the running app. The
scripts' process match is anchored on the scratch HOME's venv path, so the
real Verbal Code is never stopped.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

FAKE_PYTHON = r"""#!/usr/bin/env bash
venv="$(cd "$(dirname "$0")/.." && pwd)"
if [ "${1:-}" = -m ] && [ "${2:-}" = pip ]; then
    shift 2
    echo "pip $*" >> "$FAKE_LOG"
    case "$1" in
        show)
            for arg in "${@:2}"; do
                case "$arg" in
                    -*) ;;
                    *) [[ " ${FAKE_INSTALLED:-} " == *" $arg "* ]]
                       exit ;;
                esac
            done ;;
        wheel)
            [ "${FAKE_FAIL:-}" = build ] && { echo "error: build broke" >&2; exit 1; }
            exit 0 ;;
        install)
            if [[ " $* " == *" --dry-run "* ]]; then
                [ "${FAKE_FAIL:-}" = resolve ] && exit 1
                echo "Would install verbal-code-0.1.0"
                exit 0
            fi
            pid_file="$FAKE_LOG.app-pid"
            if [ -f "$pid_file" ] && kill -0 "$(cat "$pid_file")" 2>/dev/null; then
                echo "app running during install" >> "$FAKE_LOG"
            fi
            touch "$venv/deployed-marker"
            # pip's post-install resolver note about another package.
            if [ -n "${FAKE_RESOLVER_NOTE:-}" ]; then
                printf '%s %s %s\n' \
                    "ERROR: pip's dependency resolver does not currently take" \
                    "into account all the packages that are installed. This" \
                    "behaviour is the source of the following dependency conflicts." >&2
                echo "$FAKE_RESOLVER_NOTE" >&2
            fi
            # A dependency bump makes pip swap the ROCm build for PyPI's.
            if [ -n "${FAKE_DEPLOY_REPLACES_CT2:-}" ]; then
                echo "pypi 4.9.1" > "$venv/ct2-flavor"
            fi
            [ "${FAKE_FAIL:-}" = deploy ] && exit 1
            exit 0 ;;
        check)
            # FAKE_PIP_CHECK, or FAKE_PIP_CHECK_AFTER_DEPLOY once deployed.
            out=${FAKE_PIP_CHECK:-}
            if [ -f "$venv/deployed-marker" ] \
                && [ -n "${FAKE_PIP_CHECK_AFTER_DEPLOY:-}" ]; then
                out=$FAKE_PIP_CHECK_AFTER_DEPLOY
            fi
            [ -z "$out" ] && { echo "No broken requirements found."; exit 0; }
            echo "$out"
            exit 1 ;;
    esac
    exit 0
fi
# The real dependency check (MCC-202): Verbal Code's tree from the test
# interpreter's metadata, `pip check` answered by this stub.
if [ "${1:-}" = -m ] && [ "${2:-}" = verbal_code.depcheck ]; then
    echo "depcheck ${*:3}" >> "$FAKE_LOG"
    exec "$FAKE_REAL_PYTHON" -m verbal_code.depcheck --pip-python "$0" "${@:3}"
fi
if [ "${1:-}" = -m ] && [ "${2:-}" = verbal_code.ct2_backend ]; then
    echo "ct2 ${*:3}" >> "$FAKE_LOG"
    flavor=$(cat "$venv/ct2-flavor" 2>/dev/null || echo "pypi 4.9.1")
    case "${3:-}" in
        flavor) echo "$flavor" ;;
        is-pinned-rocm) [ "$flavor" = "rocm 4.9.1" ]; exit ;;
        verify) [ "${FAKE_FAIL:-}" = verify ] && exit 3 ;;
        wheel-name) echo "$FAKE_WHEEL" ;;
        install-rocm)
            if [ "${FAKE_FAIL:-}" = backend ]; then
                echo "ctranslate2 sees no GPU device" >&2
                exit 1
            fi
            echo "rocm 4.9.1" > "$venv/ct2-flavor"
            echo "$FAKE_WHEEL" ;;
        install-pypi) echo "pypi 4.9.1" > "$venv/ct2-flavor" ;;
    esac
    exit 0
fi
if [ "${1:-}" = -m ] && [ "${2:-}" = verbal_code ]; then
    case "${3:-}" in
        --gpu-detect)
            echo "${FAKE_GPU_LINE:-backend=cpu python=cp312 ld_path=0}"; exit 0 ;;
        --doctor) echo "Verdict: ${FAKE_VERDICT:-CPU (no GPU)}"; exit 0 ;;
        --version)
            [ "${FAKE_FAIL:-}" = health ] && exit 1
            echo "Verbal Code 0.1.0"; exit 0 ;;
        --list-models) echo "parakeet nemo-parakeet-tdt-0.6b-v2"; exit 0 ;;
        "")
            echo $$ > "$FAKE_LOG.app-pid"
            trap 'exit 0' TERM
            while :; do sleep 0.05; done ;;
    esac
    exit 0
fi
exec python3 "$@"
"""

FAKE_WHEEL = (
    "ctranslate2-4.9.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
)

# An "old" launcher that really starts the stub app, for restart tests.
LIVE_LAUNCHER = (
    "#!/usr/bin/env bash\n"
    'exec "$HOME/.local/share/verbal-code/venv/bin/python" -m verbal_code "$@"\n'
)

# System tools the scripts call that must not touch the real machine.
FAKE_TOOLS = {
    "dpkg": "exit 0",  # every system package "installed"
    "apt-cache": "exit 0",
    "sudo": 'echo "sudo must not run in tests: $*" >&2; exit 1',
    "gtk-update-icon-cache": "exit 0",
    "update-desktop-database": "exit 0",
}

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.invalid",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.invalid",
}


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "init.defaultBranch=main", *args],
        cwd=cwd,
        env={**os.environ, **GIT_ENV},
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _write_exe(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    path.chmod(0o755)


def _digest_tree(root: Path) -> dict[str, str]:
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


class Sandbox:
    def __init__(self, tmp: Path) -> None:
        self.tmp = tmp
        self.home = tmp / "home"
        self.repo = tmp / "repo"
        self.log = tmp / "calls.log"
        self.venv = self.home / ".local/share/verbal-code/venv"
        self.config_dir = self.home / ".config/verbal-code"
        self.launcher = self.home / ".local/bin/verbal-code"
        self.stamp = self.home / ".local/share/verbal-code/installed-version"
        self.backup = self.home / ".local/share/verbal-code/update-backup"
        self.fakebin = tmp / "fakebin"
        self.extra_env: dict[str, str] = {}

        for rel in ("update.sh", "scripts/install-lib.sh", "config.yaml",
                    "assets/verbal-code.svg", "verbal_code/__init__.py"):
            dest = self.repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dest)
        _git(self.repo, "init", "-q")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-qm", "initial")

        for name, body in FAKE_TOOLS.items():
            _write_exe(self.fakebin / name, f"#!/usr/bin/env bash\n{body}\n")
        self.log.touch()

    # ── State helpers ──
    def install(self) -> None:
        """An existing install: venv, old launcher, stamp and user data."""
        _write_exe(self.venv / "bin/python", FAKE_PYTHON)
        (self.venv / "pyvenv.cfg").write_text("home = /usr/bin\n")
        _write_exe(self.launcher, "#!/usr/bin/env bash\n# old launcher\n")
        self.stamp.write_text("version=0.0.9\ncommit=0ldc0de\n")
        self.config_dir.mkdir(parents=True)
        (self.config_dir / "config.yaml").write_text(
            "hotkey:\n  combo: [ctrl, alt]\nstt:\n  engine: parakeet\n"
            "  model: nemo-parakeet-tdt-0.6b-v3\nlogging:\n"
            "  file: ~/.config/verbal-code/vc-logging.log\n"
        )
        (self.config_dir / "dictionary.json").write_text('{"terms": ["liatrio"]}')
        (self.config_dir / "vc-logging.log").write_text("INFO started\n")
        sherpa = self.home / ".cache/verbal-code/sherpa-onnx/model"
        sherpa.mkdir(parents=True)
        (sherpa / "encoder.onnx").write_bytes(b"\x00" * 64)
        hub = self.home / ".cache/huggingface/hub/models--istupakov--parakeet-x/blobs"
        hub.mkdir(parents=True)
        (hub / "weights").write_bytes(b"\x01" * 64)

    def install_gpu(self, flavor: str = "rocm 4.9.1") -> None:
        """An existing install on the ROCm backend (MCC-196)."""
        self.install()
        self.stamp.write_text(
            f"version=0.0.9\ncommit=0ldc0de\ngpu_backend=rocm\nct2_wheel={FAKE_WHEEL}\n"
        )
        (self.venv / "ct2-flavor").write_text(flavor + "\n")

    def flavor(self) -> str:
        return (self.venv / "ct2-flavor").read_text().strip()

    def ct2_calls(self) -> list[str]:
        return [c for c in self.calls() if c.startswith("ct2 install")]

    def user_data(self) -> dict[str, str]:
        return {
            **_digest_tree(self.config_dir),
            **_digest_tree(self.home / ".cache"),
        }

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines()

    def real_installs(self) -> list[str]:
        return [c for c in self.calls()
                if c.startswith("pip install") and "--dry-run" not in c
                and c != "pip install --quiet pytest ruff"]

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            **GIT_ENV,
            "HOME": str(self.home),
            "PATH": f"{self.fakebin}:{os.environ['PATH']}",
            "FAKE_LOG": str(self.log),
            "FAKE_WHEEL": FAKE_WHEEL,
            "FAKE_REAL_PYTHON": sys.executable,
            "DISPLAY": ":test",
            **self.extra_env,
        }

    def run(self, *args: str, **env: str) -> subprocess.CompletedProcess[str]:
        self.extra_env.update(env)
        return subprocess.run(
            ["bash", str(self.repo / "update.sh"), *args],
            env=self.env(),
            capture_output=True,
            text=True,
            timeout=60,
        )

    # ── The fake running app ──
    def app_pid(self) -> int | None:
        pid_file = Path(f"{self.log}.app-pid")
        if not pid_file.exists():
            return None
        pid = int(pid_file.read_text())
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return None
        return pid

    def start_app(self) -> int:
        subprocess.run(["setsid", "-f", str(self.venv / "bin/python"), "-m",
                        "verbal_code"], env=self.env(), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if (pid := self.app_pid()) is not None:
                return pid
            time.sleep(0.05)
        raise AssertionError("fake app did not start")

    def kill_apps(self) -> None:
        """Kills every fake app, including one still exec'ing from the launcher."""
        pattern = f"^bash {self.home}/.local/"
        for _ in range(40):
            pkill = ["pkill", "-KILL", "-f", pattern]
            if subprocess.run(pkill, check=False).returncode:
                return  # nothing left to kill
            time.sleep(0.05)

    def wait_for_new_app(self, old_pid: int) -> int | None:
        for _ in range(100):
            pid = self.app_pid()
            if pid not in (None, old_pid):
                return pid
            time.sleep(0.05)
        return None


@pytest.fixture
def sandbox(tmp_path: Path):
    box = Sandbox(tmp_path)
    yield box
    box.kill_apps()


def _output(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


def test_no_install_fails_pointing_to_install_script(sandbox):
    result = sandbox.run()
    assert result.returncode != 0
    assert "No Verbal Code installation found" in _output(result)
    assert "./install.sh" in _output(result)
    assert not sandbox.launcher.exists()


def test_update_deploys_and_preserves_user_data(sandbox):
    sandbox.install()
    before = sandbox.user_data()
    commit = _git(sandbox.repo, "rev-parse", "--short", "HEAD")

    result = sandbox.run()

    assert result.returncode == 0, _output(result)
    assert sandbox.user_data() == before
    out = _output(result)
    assert f"0.0.9 (0ldc0de) → 0.1.0 ({commit})" in out
    assert "User data unchanged" in out
    # Build (a wheel, then a dry resolve) strictly before the deploy.
    calls = sandbox.calls()
    wheel = next(i for i, c in enumerate(calls) if c.startswith("pip wheel"))
    install = next(i for i, c in enumerate(calls) if c in sandbox.real_installs())
    assert wheel < install
    assert sandbox.real_installs() == [f"pip install --quiet -e {sandbox.repo}"]
    launcher = sandbox.launcher.read_text()
    assert 'exec "$VENV/bin/python" -m verbal_code "$@"' in launcher
    assert os.access(sandbox.launcher, os.X_OK)
    assert f"commit={commit}" in sandbox.stamp.read_text()
    assert not sandbox.backup.exists()


def test_update_keeps_installed_extras(sandbox):
    sandbox.install()
    result = sandbox.run(FAKE_INSTALLED="vosk")
    assert result.returncode == 0, _output(result)
    assert sandbox.real_installs() == [f"pip install --quiet -e {sandbox.repo}[vosk]"]


def test_failed_build_changes_nothing(sandbox):
    sandbox.install()
    before = sandbox.user_data()

    result = sandbox.run(FAKE_FAIL="build")

    assert result.returncode != 0
    assert "Build failed" in _output(result)
    assert "not changed" in _output(result)
    assert sandbox.real_installs() == []
    assert "old launcher" in sandbox.launcher.read_text()
    assert "commit=0ldc0de" in sandbox.stamp.read_text()
    assert sandbox.user_data() == before


def test_unresolvable_dependencies_change_nothing(sandbox):
    sandbox.install()
    result = sandbox.run(FAKE_FAIL="resolve")
    assert result.returncode != 0
    assert "did not resolve" in _output(result)
    assert sandbox.real_installs() == []


@pytest.mark.parametrize("failure", ["deploy", "health"])
def test_failed_deploy_rolls_back(sandbox, failure):
    sandbox.install()
    before = sandbox.user_data()

    result = sandbox.run(FAKE_FAIL=failure)

    assert result.returncode != 0
    out = _output(result)
    assert "rolling back" in out
    assert "0.0.9 (0ldc0de) is installed, unchanged" in out
    # The pip stub marks the venv before failing; the restore undoes it.
    assert not (sandbox.venv / "deployed-marker").exists()
    assert (sandbox.venv / "bin/python").exists()
    assert "old launcher" in sandbox.launcher.read_text()
    assert sandbox.stamp.read_text() == "version=0.0.9\ncommit=0ldc0de\n"
    assert not sandbox.backup.exists()
    assert sandbox.user_data() == before


def test_running_app_is_stopped_then_restarted(sandbox):
    sandbox.install()
    _write_exe(sandbox.launcher, LIVE_LAUNCHER)
    old_pid = sandbox.start_app()

    result = sandbox.run()

    assert result.returncode == 0, _output(result)
    assert "app running during install" not in sandbox.calls()
    assert "Verbal Code restarted" in _output(result)
    assert sandbox.wait_for_new_app(old_pid) is not None


def test_no_restart_leaves_the_app_stopped(sandbox):
    sandbox.install()
    sandbox.start_app()

    result = sandbox.run("--no-restart")

    assert result.returncode == 0, _output(result)
    assert "Start Verbal Code again when ready" in _output(result)
    assert sandbox.app_pid() is None


def test_failed_update_restarts_the_previous_version(sandbox):
    sandbox.install()
    _write_exe(sandbox.launcher, LIVE_LAUNCHER)
    old_pid = sandbox.start_app()

    result = sandbox.run(FAKE_FAIL="deploy")

    assert result.returncode != 0
    assert "Verbal Code restarted" in _output(result)
    new_pid = sandbox.wait_for_new_app(old_pid)
    assert new_pid is not None
    # The rollback ignores Ctrl-C while it restores; the restarted app must
    # not inherit that and still stop on SIGTERM.
    os.kill(new_pid, signal.SIGTERM)
    for _ in range(40):
        if sandbox.app_pid() is None:
            break
        time.sleep(0.05)
    assert sandbox.app_pid() is None


def test_dry_run_changes_nothing(sandbox):
    sandbox.install()
    before = sandbox.user_data()
    old_pid = sandbox.start_app()

    result = sandbox.run("--dry-run")

    assert result.returncode == 0, _output(result)
    out = _output(result)
    assert "Dry run" in out
    assert "Installed:  0.0.9 (0ldc0de)" in out
    assert "verbal-code-0.1.0" in out
    assert "Files to replace: launcher desktop entry icon" in out
    assert "would be stopped, then restarted" in out
    assert sandbox.real_installs() == []
    assert not any(c.startswith("pip wheel") for c in sandbox.calls())
    assert "old launcher" in sandbox.launcher.read_text()
    assert sandbox.app_pid() == old_pid
    assert sandbox.user_data() == before


def test_interrupted_update_is_restored_first(sandbox):
    sandbox.install()
    # What a killed update leaves: a complete backup of the old venv, and a
    # half-updated venv in place.
    shutil.copytree(sandbox.venv, sandbox.backup / "venv", symlinks=True)
    (sandbox.backup / "venv/old-version").touch()
    (sandbox.backup / "files").mkdir()
    (sandbox.venv / "half-updated").touch()

    result = sandbox.run()

    assert result.returncode == 0, _output(result)
    assert "did not finish" in _output(result)
    assert (sandbox.venv / "old-version").exists()
    assert not (sandbox.venv / "half-updated").exists()
    assert not sandbox.backup.exists()


def _with_upstream(sandbox: Sandbox) -> Path:
    """Gives the checkout an upstream with one newer commit; returns it."""
    upstream = sandbox.tmp / "upstream.git"
    _git(sandbox.tmp, "clone", "-q", "--bare", str(sandbox.repo), str(upstream))
    _git(sandbox.repo, "remote", "add", "origin", str(upstream))
    _git(sandbox.repo, "fetch", "-q", "origin")
    _git(sandbox.repo, "branch", "-q", "--set-upstream-to=origin/main")
    other = sandbox.tmp / "other"
    _git(sandbox.tmp, "clone", "-q", str(upstream), str(other))
    (other / "NEWS").write_text("new\n")
    _git(other, "add", "NEWS")
    _git(other, "commit", "-qm", "newer")
    _git(other, "push", "-q", "origin", "main")
    return other


def test_pull_fast_forwards_before_building(sandbox):
    sandbox.install()
    other = _with_upstream(sandbox)
    newest = _git(other, "rev-parse", "--short", "HEAD")

    result = sandbox.run("--pull")

    assert result.returncode == 0, _output(result)
    assert _git(sandbox.repo, "rev-parse", "--short", "HEAD") == newest
    assert f"→ 0.1.0 ({newest})" in _output(result)


def test_failed_update_after_pull_restores_the_checkout(sandbox):
    sandbox.install()
    _with_upstream(sandbox)
    before = _git(sandbox.repo, "rev-parse", "HEAD")

    result = sandbox.run("--pull", FAKE_FAIL="deploy")

    assert result.returncode != 0
    assert _git(sandbox.repo, "rev-parse", "HEAD") == before


def test_pull_refuses_uncommitted_changes(sandbox):
    sandbox.install()
    _with_upstream(sandbox)
    (sandbox.repo / "config.yaml").write_text("edited: true\n")

    result = sandbox.run("--pull")

    assert result.returncode != 0
    assert "uncommitted changes" in _output(result)
    assert sandbox.real_installs() == []


def test_ctrl_c_during_deploy_rolls_back(sandbox):
    sandbox.install()
    # A pip that hangs mid-install, so the update can be interrupted there.
    stub = (sandbox.venv / "bin/python").read_text().replace(
        '[ "${FAKE_FAIL:-}" = deploy ] && exit 1',
        '[ "${FAKE_FAIL:-}" = hang ] && { echo hung >> "$FAKE_LOG"; sleep 30; }',
    )
    _write_exe(sandbox.venv / "bin/python", stub)
    sandbox.extra_env["FAKE_FAIL"] = "hang"
    proc = subprocess.Popen(
        ["bash", str(sandbox.repo / "update.sh")], env=sandbox.env(),
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        start_new_session=True,
    )
    for _ in range(200):
        if "hung" in sandbox.calls():
            break
        time.sleep(0.05)
    else:
        proc.kill()
        raise AssertionError("update never reached the deploy")
    os.killpg(proc.pid, signal.SIGINT)  # Ctrl-C reaches the whole group
    out, _ = proc.communicate(timeout=60)

    assert proc.returncode != 0
    assert "rolling back" in out
    assert not (sandbox.venv / "deployed-marker").exists()
    assert "old launcher" in sandbox.launcher.read_text()
    assert not sandbox.backup.exists()


# ── GPU backend (MCC-196) ──

def test_rocm_wheel_replaced_by_deploy_is_reinstalled(sandbox):
    sandbox.install_gpu()
    before = sandbox.user_data()

    result = sandbox.run(FAKE_DEPLOY_REPLACES_CT2="1")

    assert result.returncode == 0, _output(result)
    assert sandbox.ct2_calls() == [
        f"ct2 install-rocm --cache-dir {sandbox.home}/.local/share/verbal-code/"
        "wheels --no-fallback"
    ]
    # Verified by the installed build, not just the marker.
    assert sandbox.flavor() == "rocm 4.9.1"
    stamp = sandbox.stamp.read_text()
    assert "gpu_backend=rocm" in stamp and f"ct2_wheel={FAKE_WHEEL}" in stamp
    assert sandbox.user_data() == before
    assert "User data unchanged" in _output(result)


def test_intact_rocm_wheel_is_kept(sandbox):
    sandbox.install_gpu()
    result = sandbox.run()
    assert result.returncode == 0, _output(result)
    assert sandbox.ct2_calls() == []
    assert sandbox.flavor() == "rocm 4.9.1"
    assert "gpu_backend=rocm" in sandbox.stamp.read_text()


def test_failed_backend_reinstall_rolls_back(sandbox):
    sandbox.install_gpu()
    before = sandbox.user_data()
    old_stamp = sandbox.stamp.read_text()

    result = sandbox.run(FAKE_DEPLOY_REPLACES_CT2="1", FAKE_FAIL="backend")

    assert result.returncode != 0
    out = _output(result)
    assert "Could not keep the ROCm build" in out
    assert "rolling back" in out
    assert "0.0.9 (0ldc0de) is installed, unchanged" in out
    # The venv backup comes back with the working ROCm build in it.
    assert sandbox.flavor() == "rocm 4.9.1"
    assert not (sandbox.venv / "deployed-marker").exists()
    assert sandbox.stamp.read_text() == old_stamp
    assert sandbox.user_data() == before


def test_cpu_marker_means_no_backend_action(sandbox):
    sandbox.install()
    sandbox.stamp.write_text("version=0.0.9\ncommit=0ldc0de\ngpu_backend=cpu\n")
    result = sandbox.run()
    assert result.returncode == 0, _output(result)
    assert not any(c.startswith("ct2 ") for c in sandbox.calls())
    assert "gpu_backend=cpu" in sandbox.stamp.read_text()


def test_install_without_marker_stays_without_one(sandbox):
    sandbox.install()
    result = sandbox.run()
    assert result.returncode == 0, _output(result)
    assert "gpu_backend" not in sandbox.stamp.read_text()


def test_dry_run_reports_the_backend_plan(sandbox):
    sandbox.install_gpu(flavor="pypi 4.9.1")
    before = sandbox.user_data()
    result = sandbox.run("--dry-run")
    assert result.returncode == 0, _output(result)
    assert "GPU backend: reinstall ROCm wheel" in _output(result)
    assert sandbox.ct2_calls() == []
    assert sandbox.flavor() == "pypi 4.9.1"
    assert sandbox.user_data() == before


def test_dry_run_plan_keep_and_none(sandbox):
    sandbox.install_gpu()
    assert "GPU backend: keep (ROCm wheel)" in _output(sandbox.run("--dry-run"))
    sandbox.stamp.write_text("version=0.0.9\ncommit=0ldc0de\n")
    assert "GPU backend: none" in _output(sandbox.run("--dry-run"))


def test_newly_detected_gpu_is_offered_not_switched(sandbox):
    sandbox.install()
    result = sandbox.run(
        FAKE_GPU_LINE="backend=rocm gfx=gfx1200 index=0 python=cp312 ld_path=0",
        FAKE_VERDICT="CPU (GPU problem: the ROCm build is not installed)",
    )
    assert result.returncode == 0, _output(result)
    out = _output(result)
    assert "rocm-capable GPU is now detected" in out
    assert "--doctor --fix" in out
    assert "GPU: CPU (GPU problem" in out  # the doctor's verdict (R9.6)
    assert sandbox.ct2_calls() == []


def test_launcher_gets_rocm_lib_path_only_when_recorded(sandbox):
    """MCC-198: LD_LIBRARY_PATH only for rocm, and only when needed."""
    sandbox.install_gpu()
    sandbox.stamp.write_text(sandbox.stamp.read_text() + "rocm_ld_path=1\n")
    result = sandbox.run()
    assert result.returncode == 0, _output(result)
    launcher = sandbox.launcher.read_text()
    assert 'export LD_LIBRARY_PATH="/opt/rocm/lib' in launcher
    assert "rocm_ld_path=1" in sandbox.stamp.read_text()
    # A dry run afterwards sees the launcher as current.
    assert "Files to replace: none" in _output(sandbox.run("--dry-run"))


def test_launcher_has_no_rocm_lib_path_by_default(sandbox):
    sandbox.install_gpu()
    result = sandbox.run()
    assert result.returncode == 0, _output(result)
    assert "LD_LIBRARY_PATH" not in sandbox.launcher.read_text()


# ── Dependency conflicts (MCC-202) ──

# Linux Mint 22's own conflict, seen through --system-site-packages.
MINT_CONFLICT = ("yt-dlp 2024.4.9 has requirement websockets>=12.0, but you "
                 "have websockets 10.4.")
MINT_RESOLVER_LINE = ("yt-dlp 2024.4.9 requires websockets>=12.0, but you have "
                      "websockets 10.4 which is incompatible.")
OWN_CONFLICT = ("faster-whisper 1.2.1 has requirement ctranslate2<5,>=4.0, but "
                "you have ctranslate2 5.0.0.")


def test_unrelated_system_conflict_passes_with_one_note(sandbox):
    sandbox.install_gpu()
    result = sandbox.run(FAKE_PIP_CHECK=MINT_CONFLICT,
                         FAKE_RESOLVER_NOTE=MINT_RESOLVER_LINE)
    out = result.stdout + result.stderr
    assert result.returncode == 0, out
    assert "ERROR:" not in out and "dependency resolver" not in out
    assert out.count("yt-dlp wants websockets>=12.0") == 1
    assert "Verbal Code doesn't use them and isn't affected" in out
    assert sandbox.flavor() == "rocm 4.9.1"  # the GPU backend stays
    assert "gpu_backend=rocm" in sandbox.stamp.read_text()
    assert not sandbox.backup.exists()


def test_own_dependency_conflict_fails_and_rolls_back(sandbox):
    sandbox.install()
    old_launcher = sandbox.launcher.read_text()
    result = sandbox.run(FAKE_PIP_CHECK=MINT_CONFLICT,
                         FAKE_PIP_CHECK_AFTER_DEPLOY=f"{MINT_CONFLICT}\n{OWN_CONFLICT}")
    out = result.stdout + result.stderr
    assert result.returncode != 0
    assert ("Verbal Code's dependencies conflict: faster-whisper 1.2.1 has "
            "requirement ctranslate2<5,>=4.0") in out
    assert "yt-dlp" not in out.split("dependencies conflict:", 1)[1].splitlines()[0]
    assert "Rolled back" in out or "rolled back" in out
    assert sandbox.launcher.read_text() == old_launcher


def test_dry_run_ignores_unrelated_conflicts(sandbox):
    sandbox.install()
    result = sandbox.run("--dry-run", FAKE_PIP_CHECK=MINT_CONFLICT)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ERROR:" not in result.stdout + result.stderr
