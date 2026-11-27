"""The pinned ROCm build of CTranslate2, and installing it into the venv
(MCC-195).

PyPI's ``ctranslate2`` wheel is built for CUDA only. AMD GPUs need the ROCm
build CTranslate2 publishes as a release asset: a zip with one wheel per
CPython tag. This module is the **one** place that build is pinned. To bump
it, change ``ROCM_VERSION``, ``ROCM_ZIP_URL``, ``ROCM_ZIP_SHA256`` and the
``ROCM_WHEEL_SHA256`` table together, after downloading the new asset and
hashing it and every wheel inside (``unzip`` it, then ``sha256sum``), and
keep the version equal to the ``ctranslate2`` that pip resolves from PyPI so
``pip install -e .`` doesn't swap it back. Never download "latest".

The wheel doesn't bundle ROCm: ``import ctranslate2`` fails on a machine
without the ROCm 7 libraries. So every install is verified (a GPU must be
visible from a fresh interpreter) and, unless the caller wants a hard
failure, a failed verification reinstalls the PyPI wheel, leaving the venv
on CPU but working.

Run with the venv interpreter: ``python -m verbal_code.ct2_backend <cmd>``
(scripts/install-lib.sh does). Exit status 0 = done, 3 = the GPU backend is
unavailable and the venv is on the PyPI (CPU) wheel, 1 = a hard failure.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable

from verbal_code import gpu

ROCM_VERSION = "4.9.1"
ROCM_ZIP_URL = (
    "https://github.com/OpenNMT/CTranslate2/releases/download/"
    f"v{ROCM_VERSION}/rocm-python-wheels-Linux.zip"
)
ROCM_ZIP_SIZE = 277_433_341
ROCM_ZIP_SHA256 = "283c6800475961a13120f8ad2761a00ebe645aac3c155a6794f6d784b1111593"
# Built against ROCm 7.2.0 for gfx targets gpu.ROCM_BUILT_TARGETS; x86_64,
# glibc >= 2.28.
ROCM_WHEEL_SHA256 = {
    "cp39": "a14160071871b21084a16afb1c560deb41558dfcd6a9f17d0738a7bc33cd6138",
    "cp310": "2aed6cd1a624a7c63a2757edf181b17c26447799e999d0197cf86fc21b5baff9",
    "cp311": "755888f56691f35f27a17762e93dd4f4e9f560df81fc7173244a8e4c5b0944e8",
    "cp312": "d5b48a2f32bb1c9f5c5709d9066ede1889116a5804ca56fa08ab8eec3946e2e4",
    "cp313": "77824bd1f8cb31b2bf3e42b8d2fe057eb8382e4e2086aafa4432d4269a5ec8bd",
    "cp314": "5fde9b4fb206cc08bba62af36014f73ec302cdb4ff4167af053f80933da70a85",
    "cp314t": "b9eeccf16dd14e64915a22d4c5cfe283f634a009e558114532cc376033857386",
    "cp315": "0e1b7fe15aa3d6dcf00392ef6c4ec68cdaf7189a2db0bd8f8734f65c9bdcffc1",
    "cp315t": "d02845c30bb3e9dc32c765e34afeab2a9ff2f9a39c10c09819111ca3fbe3ab71",
}
_ZIP_MEMBER_DIR = "temp-linux"

# Inside the app's data dir, not ~/.cache/verbal-code: update.sh checksums
# the cache dirs as user data and must not see its own wheel there
# (MCC-196). uninstall.sh removes the whole data dir.
WHEEL_CACHE_DIR = os.path.expanduser("~/.local/share/verbal-code/wheels")
RETRY_HINT = "verbal-code --doctor --fix"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_CPU = 3

_DOWNLOAD_TIMEOUT_SECONDS = 60
_CHUNK = 1024 * 1024


class BackendError(Exception):
    """The GPU backend could not be installed; the message says why."""


def wheel_filename(tag: str, version: str = ROCM_VERSION) -> str:
    """The wheel's name in the zip; ``cp314t`` is ``cp314-cp314t``."""
    python = tag.removesuffix("t")
    return (f"ctranslate2-{version}-{python}-{tag}-"
            "manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl")


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def fetch_zip(
    dest_dir: str,
    url: str = ROCM_ZIP_URL,
    sha256: str = ROCM_ZIP_SHA256,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> str:
    """Download the release zip into ``dest_dir`` and verify it. A
    partial or corrupt file is deleted; the zip is never used unverified."""
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, os.path.basename(url))
    if os.path.exists(path) and sha256_file(path) == sha256:
        return path
    part = path + ".part"
    _log(f"Downloading {url} (~{ROCM_ZIP_SIZE // 1_000_000} MB)...")
    try:
        with opener(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS) as response, \
                open(part, "wb") as out:
            shutil.copyfileobj(response, out, _CHUNK)
    except (OSError, ValueError) as exc:
        _remove(part)
        raise BackendError(f"download failed ({exc}); retry with {RETRY_HINT}") \
            from exc
    actual = sha256_file(part)
    if actual != sha256:
        _remove(part)
        raise BackendError(
            f"SHA-256 mismatch for {os.path.basename(url)}: expected {sha256}, "
            f"got {actual}. Nothing was installed."
        )
    os.replace(part, path)
    return path


def extract_wheel(
    zip_path: str,
    tag: str,
    dest_dir: str,
    wheel_hashes: dict[str, str] = ROCM_WHEEL_SHA256,
    version: str = ROCM_VERSION,
) -> str:
    """Extract only the wheel for ``tag`` and verify its pinned SHA-256."""
    if tag not in wheel_hashes:
        raise BackendError(f"no ROCm wheel is pinned for Python tag {tag}")
    name = wheel_filename(tag, version)
    member = f"{_ZIP_MEMBER_DIR}/{name}"
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, name)
    part = dest + ".part"
    try:
        with zipfile.ZipFile(zip_path) as archive, archive.open(member) as src, \
                open(part, "wb") as out:
            shutil.copyfileobj(src, out, _CHUNK)
    except KeyError as exc:
        _remove(part)
        raise BackendError(f"{name} is not in {os.path.basename(zip_path)}") \
            from exc
    except (OSError, zipfile.BadZipFile) as exc:
        _remove(part)
        raise BackendError(f"could not extract {name}: {exc}") from exc
    actual = sha256_file(part)
    if actual != wheel_hashes[tag]:
        _remove(part)
        raise BackendError(
            f"SHA-256 mismatch for {name}: expected {wheel_hashes[tag]}, got "
            f"{actual}. Nothing was installed."
        )
    os.replace(part, dest)
    return dest


def obtain_wheel(
    tag: str,
    cache_dir: str = WHEEL_CACHE_DIR,
    fetch: Callable[[str], str] = fetch_zip,
    wheel_hashes: dict[str, str] = ROCM_WHEEL_SHA256,
    version: str = ROCM_VERSION,
) -> str:
    """The verified wheel for ``tag``: from the cache when it is there and
    intact, else downloaded and extracted. Only that one wheel (~34 MB) is
    kept; the 277 MB zip and wheels of other pins are removed."""
    if tag not in wheel_hashes:
        raise BackendError(f"no ROCm wheel is pinned for Python tag {tag}")
    name = wheel_filename(tag, version)
    cached = os.path.join(cache_dir, name)
    if os.path.exists(cached) and sha256_file(cached) == wheel_hashes[tag]:
        return cached
    _remove(cached)
    with tempfile.TemporaryDirectory(dir=_ensure(cache_dir)) as work:
        zip_path = fetch(work)
        wheel = extract_wheel(zip_path, tag, cache_dir, wheel_hashes, version)
    for entry in os.listdir(cache_dir):
        if entry.startswith("ctranslate2-") and entry != name:
            _remove(os.path.join(cache_dir, entry))
    return wheel


def _ensure(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def _remove(path: str) -> None:
    with contextlib.suppress(FileNotFoundError):
        os.remove(path)


# ── The venv ──

RunFn = Callable[..., subprocess.CompletedProcess]


def _pip(run: RunFn, python: str, *args: str) -> subprocess.CompletedProcess:
    return run([python, "-m", "pip", *args], capture_output=True, text=True,
               cwd="/")


def _pip_problems(run: RunFn, python: str) -> set[str]:
    """``pip check`` complaints. The venv sees system site-packages, whose
    own conflicts (e.g. a distro yt-dlp) predate us, so callers compare
    before and after instead of requiring a clean result."""
    result = _pip(run, python, "check")
    if result.returncode == 0:
        return set()
    return {ln for ln in result.stdout.splitlines() if ln.strip()}


def installed_version() -> str | None:
    from importlib import metadata

    try:
        return metadata.version("ctranslate2")
    except metadata.PackageNotFoundError:
        return None


def gpu_visible(
    run: RunFn = subprocess.run, python: str = sys.executable,
    env: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """(True, "") when a fresh interpreter imports ctranslate2 and sees at
    least one GPU; else (False, why)."""
    from verbal_code.doctor import probe_ctranslate2

    def run_with_env(cmd, **kwargs):
        return run(cmd, env=env, **kwargs) if env is not None else run(cmd, **kwargs)

    probe = probe_ctranslate2(run=run_with_env, python=python)
    if not probe.imported:
        return False, f"import ctranslate2 failed: {probe.error}"
    if probe.device_count < 1:
        return False, "ctranslate2 sees no GPU device"
    return True, ""


def pin_satisfies_faster_whisper(version: str = ROCM_VERSION) -> bool | None:
    """Whether the pinned version meets faster-whisper's ``ctranslate2``
    requirement; None when that can't be checked. A pin outside it would be
    replaced by the next ``pip install -e .`` (R4.20)."""
    from importlib import metadata

    try:
        from packaging.requirements import Requirement
        requires = metadata.requires("faster-whisper") or []
    except (ImportError, metadata.PackageNotFoundError):
        return None
    for line in requires:
        req = Requirement(line)
        if req.name == "ctranslate2" and not req.marker:
            return req.specifier.contains(version, prereleases=True)
    return None


def install_pypi(run: RunFn = subprocess.run, python: str = sys.executable,
                 version: str | None = None) -> None:
    """(Re)install PyPI's ctranslate2, at ``version`` if given."""
    spec = f"ctranslate2=={version}" if version else "ctranslate2"
    result = _pip(run, python, "install", "--quiet", "--force-reinstall",
                  "--no-deps", spec)
    if result.returncode != 0:
        raise BackendError(
            f"reinstalling {spec} from PyPI failed: {result.stderr.strip()}"
        )


def install_rocm(
    run: RunFn = subprocess.run,
    python: str = sys.executable,
    cache_dir: str = WHEEL_CACHE_DIR,
    tag: str | None = None,
    fallback: bool = True,
    obtain: Callable[..., str] = obtain_wheel,
    verify: Callable[..., tuple[bool, str]] = gpu_visible,
    machine: str | None = None,
    previous: tuple[str, str | None] | None = None,
    env: dict[str, str] | None = None,
) -> str:
    """Install the pinned ROCm wheel and verify it. Returns the wheel file
    name. On failure raises BackendError; with ``fallback`` the PyPI wheel
    is reinstalled first, so the venv keeps a working (CPU) ctranslate2."""
    tag = tag or gpu.python_tag()
    machine = machine or platform.machine()
    if machine != "x86_64":
        raise BackendError(f"the ROCm wheel is x86_64 only (this is {machine})")
    # Nothing in the venv has changed yet: a hash mismatch, missing tag or
    # network error leaves the current ctranslate2 untouched.
    wheel = obtain(tag, cache_dir)

    flavor, version = previous or gpu.installed_ct2_flavor()
    # A rollback reinstalls what pip resolved before the swap; when that was
    # already a ROCm build, PyPI's release of the pinned version.
    rollback_version = version if flavor == "pypi" else ROCM_VERSION
    problems_before = _pip_problems(run, python)

    result = _pip(run, python, "install", "--quiet", "--force-reinstall",
                  "--no-deps", wheel)
    if result.returncode != 0:
        error = f"pip could not install {os.path.basename(wheel)}: " \
                f"{result.stderr.strip()}"
    else:
        ok, error = verify(run=run, python=python, env=env)
        if ok:
            new = _pip_problems(run, python) - problems_before
            error = "" if not new else "pip check: " + "; ".join(sorted(new))
    if not error:
        return os.path.basename(wheel)
    if fallback:
        install_pypi(run, python, rollback_version)
        raise BackendError(f"{error}. Reinstalled the PyPI ctranslate2; Whisper "
                           f"runs on CPU. Retry with {RETRY_HINT}.")
    raise BackendError(error)


# ── CLI (scripts/install-lib.sh) ──

def _cmd_flavor(_args: argparse.Namespace) -> int:
    flavor, version = gpu.installed_ct2_flavor()
    print(flavor if version is None else f"{flavor} {version}")
    return EXIT_OK


def _cmd_is_pinned_rocm(_args: argparse.Namespace) -> int:
    """Exit 0 when the venv has the pinned ROCm build, 1 otherwise."""
    return EXIT_OK if gpu.installed_ct2_flavor() == ("rocm", ROCM_VERSION) \
        else EXIT_FAILED


def _cmd_wheel_name(_args: argparse.Namespace) -> int:
    print(wheel_filename(gpu.python_tag()))
    return EXIT_OK


def _rocm_env(args: argparse.Namespace) -> dict[str, str] | None:
    if not args.ld_library_path:
        return None
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = ":".join(
        p for p in (gpu.ROCM_LIB_DIR, env.get("LD_LIBRARY_PATH")) if p
    )
    return env


def _cmd_install_rocm(args: argparse.Namespace) -> int:
    if pin_satisfies_faster_whisper() is False:
        _log(f"Warning: the pinned ROCm ctranslate2 {ROCM_VERSION} is outside "
             "faster-whisper's ctranslate2 requirement; pip will replace it. "
             "Bump the pin in verbal_code/ct2_backend.py.")
    try:
        wheel = install_rocm(cache_dir=args.cache_dir,
                             fallback=not args.no_fallback, env=_rocm_env(args))
    except BackendError as exc:
        _log(f"ROCm backend not installed: {exc}")
        return EXIT_FAILED if args.no_fallback else EXIT_CPU
    print(wheel)
    return EXIT_OK


def _cmd_install_pypi(_args: argparse.Namespace) -> int:
    try:
        install_pypi(version=ROCM_VERSION)
    except BackendError as exc:
        _log(str(exc))
        return EXIT_FAILED
    return EXIT_OK


def _cmd_verify(args: argparse.Namespace) -> int:
    ok, why = gpu_visible(env=_rocm_env(args))
    if not ok:
        _log(why)
    return EXIT_OK if ok else EXIT_CPU


def _cmd_describe(_args: argparse.Namespace) -> int:
    """Human summary of detection for install.sh: line 1 the result, line
    2 (optional) the actionable hint."""
    report = gpu.detect()
    print(report.summary())
    if report.hint:
        print(report.hint)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m verbal_code.ct2_backend")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("flavor", help="print the installed build: rocm|pypi|missing "
                   "[version]").set_defaults(func=_cmd_flavor)
    sub.add_parser("is-pinned-rocm", help="exit 0 if the pinned ROCm build is "
                   "installed").set_defaults(func=_cmd_is_pinned_rocm)
    sub.add_parser("wheel-name", help="print the pinned wheel's file name for "
                   "this interpreter").set_defaults(func=_cmd_wheel_name)
    rocm = sub.add_parser("install-rocm", help="install and verify the pinned "
                          "ROCm wheel")
    rocm.add_argument("--cache-dir", default=WHEEL_CACHE_DIR)
    rocm.add_argument("--no-fallback", action="store_true",
                      help="on failure exit 1 without reinstalling the PyPI wheel")
    rocm.add_argument("--ld-library-path", action="store_true",
                      help=f"verify with {gpu.ROCM_LIB_DIR} on LD_LIBRARY_PATH")
    rocm.set_defaults(func=_cmd_install_rocm)
    sub.add_parser("install-pypi", help="reinstall PyPI's ctranslate2 at the "
                   "pinned version").set_defaults(func=_cmd_install_pypi)
    verify = sub.add_parser("verify", help="exit 0 if ctranslate2 sees a GPU")
    verify.add_argument("--ld-library-path", action="store_true")
    verify.set_defaults(func=_cmd_verify)
    sub.add_parser("describe", help="print the detection summary and hint"
                   ).set_defaults(func=_cmd_describe)
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
