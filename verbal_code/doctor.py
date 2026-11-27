"""``verbal-code --doctor``: is GPU transcription working, and if not, why
(MCC-194). Needs no audio hardware and no valid config, and never imports
ctranslate2 in-process: a broken GPU wheel can fail to import or crash, so
the device count comes from a child interpreter with a timeout.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import TextIO

from verbal_code import __version__, gpu

# Variables that change which GPU CTranslate2 sees or how it allocates
# (README → GPU acceleration).
GPU_ENV_VARS = (
    "VERBAL_CODE_GPU_BACKEND",
    "CT2_CUDA_ALLOCATOR",
    "HSA_OVERRIDE_GFX_VERSION",
    "HIP_VISIBLE_DEVICES",
    "ROCR_VISIBLE_DEVICES",
    "CUDA_VISIBLE_DEVICES",
    "LD_LIBRARY_PATH",
)
_CT2_PROBE_TIMEOUT_SECONDS = 60  # first import of a ROCm build can be slow
_CT2_PROBE = (
    "import ctranslate2; print(ctranslate2.__version__); "
    "print(ctranslate2.get_cuda_device_count())"
)
FIX_HINT = "./install.sh"


@dataclass
class Ct2Probe:
    """``ctranslate2`` as a fresh interpreter sees it."""

    imported: bool
    device_count: int = 0
    error: str = ""


def probe_ctranslate2(
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    python: str = sys.executable,
) -> Ct2Probe:
    try:
        result = run(
            [python, "-c", _CT2_PROBE],
            capture_output=True,
            text=True,
            timeout=_CT2_PROBE_TIMEOUT_SECONDS,
            cwd="/",  # never import a checkout's modules by accident
        )
    except subprocess.TimeoutExpired:
        return Ct2Probe(False, error="import ctranslate2 timed out")
    except OSError as exc:
        return Ct2Probe(False, error=str(exc))
    if result.returncode != 0:
        lines = [ln for ln in result.stderr.strip().splitlines() if ln.strip()]
        return Ct2Probe(False, error=lines[-1] if lines else
                        f"exit status {result.returncode}")
    lines = result.stdout.strip().splitlines()
    try:
        return Ct2Probe(True, int(lines[-1]))
    except (IndexError, ValueError):
        return Ct2Probe(True, error="unexpected output from ctranslate2")


def effective_whisper_device(
    device: str, compute_type: str, cuda_devices: int
) -> tuple[str, str]:
    """The (device, compute_type) Whisper runs with for a config's
    ``stt.whisper.device`` / ``compute_type`` and the visible GPU count.
    ``auto`` compute picks float16 on GPU, int8 on CPU; an explicit compute
    type is always respected."""
    on_gpu = device != "cpu" and cuda_devices >= 1
    resolved = "cuda" if on_gpu else "cpu"
    if compute_type in ("auto", "", None):
        compute_type = "float16" if on_gpu else "int8"
    return resolved, compute_type


@dataclass
class Verdict:
    gpu_ok: bool
    text: str
    exit_code: int


def verdict(
    report: gpu.GpuReport,
    marker: str | None,
    flavor: str,
    probe: Ct2Probe,
) -> Verdict:
    """The final line, and the exit code: 0 when the result matches the
    marker (GPU expected and working, or CPU expected), 1 otherwise."""
    expects_gpu = marker in ("rocm", "cuda")
    wheel_matches = (
        flavor == "rocm" if report.recommended_backend == "rocm"
        else flavor == "pypi"
    )
    if (report.recommended_backend != "cpu" and wheel_matches
            and probe.imported and probe.device_count >= 1):
        return Verdict(True, "GPU OK", 0)

    code = 1 if expects_gpu else 0
    if report.recommended_backend == "cpu":
        if report.vendor == "none" and not expects_gpu:
            return Verdict(False, "CPU (no GPU)", code)
        reason = report.runtime_detail
        fix = report.hint or "see README → GPU acceleration"
    elif flavor == "missing":
        reason = "ctranslate2 is not installed"
        fix = "./install.sh"
    elif not wheel_matches and marker == "rocm":
        reason = "GPU backend was replaced by a pip upgrade"
        fix = FIX_HINT
    elif not wheel_matches and report.recommended_backend == "rocm":
        reason = "the ROCm build of CTranslate2 is not installed"
        fix = FIX_HINT
    elif not wheel_matches:
        reason = "the ROCm build of CTranslate2 is installed on a non-AMD setup"
        fix = FIX_HINT
    elif not probe.imported:
        reason = f"ctranslate2 does not import ({probe.error})"
        fix = FIX_HINT
    else:
        reason = "ctranslate2 sees no GPU device"
        fix = "check the runtime with rocminfo / nvidia-smi"
    return Verdict(False, f"CPU (GPU problem: {reason}, fix: {fix})", code)


def _gib(value: int | None) -> str:
    return "?" if value is None else f"{value / 1024 ** 3:.1f} GiB"


def _stamp_value(key: str) -> str | None:
    try:
        with open(gpu.STAMP_FILE) as f:
            for line in f:
                if line.startswith(f"{key}="):
                    return line.partition("=")[2].strip()
    except OSError:
        pass
    return None


def run_doctor(
    config: dict,
    out: TextIO | None = None,
    report: gpu.GpuReport | None = None,
    probe: Ct2Probe | None = None,
    flavor: tuple[str, str | None] | None = None,
    marker: str | None = None,
    env: dict[str, str] | None = None,
) -> int:
    """Print the report and return the exit code (R9.5)."""
    out = out or sys.stdout
    env = dict(os.environ) if env is None else env
    report = report or gpu.detect()
    flavor_name, flavor_version = flavor or gpu.installed_ct2_flavor()
    marker = marker if marker is not None else gpu.read_marker()
    probe = probe or probe_ctranslate2()

    def line(label: str, value: object) -> None:
        print(f"  {label:<26}{value}", file=out)

    print("Verbal Code doctor", file=out)
    line("Version", f"{__version__} (installed commit "
         f"{_stamp_value('commit') or 'unknown'})")
    line("Python", f"{platform.python_version()} ({gpu.python_tag()}, "
         f"{platform.machine()})")

    print("\nGPU", file=out)
    if not report.devices:
        line("Devices", "none found")
    for device in report.devices:
        details = [device.target or "target unknown"]
        if device.index is not None:
            details.append(f"index {device.index}")
        if device.support_note():
            details.append(device.support_note())
        line(device.vendor.upper(), f"{device.name}: {', '.join(details)}")
        line("  VRAM used/total",
             f"{_gib(device.vram_used)} / {_gib(device.vram_total)}")
    line("Runtime", ("OK: " if report.runtime_ok else "not usable: ")
         + report.runtime_detail)
    if report.hint:
        line("Hint", report.hint)
    line("Recommended backend", report.recommended_backend)

    print("\nCTranslate2", file=out)
    line("Backend marker", marker or "none (installed before GPU support)")
    line("Installed build", flavor_name + (f" {flavor_version}"
                                           if flavor_version else ""))
    if probe.imported:
        line("CUDA/HIP devices", probe.device_count)
    else:
        line("Import", f"failed: {probe.error}")

    print("\nEnvironment", file=out)
    for name in GPU_ENV_VARS:
        line(name, env.get(name, "(unset)"))

    whisper_cfg = (config.get("stt") or {}).get("whisper") or {}
    device = whisper_cfg.get("device", "auto")
    compute = whisper_cfg.get("compute_type", "auto")
    eff_device, eff_compute = effective_whisper_device(
        device, compute, probe.device_count if probe.imported else 0
    )
    engine = (config.get("stt") or {}).get("engine", "whisper")
    print("\nWhisper", file=out)
    line("Configured", f"device={device} compute_type={compute}"
         + ("" if engine == "whisper" else f" (engine is {engine}; Whisper "
            "is the only engine that uses the GPU)"))
    line("Effective", f"device={eff_device} compute_type={eff_compute}")

    result = verdict(report, marker, flavor_name, probe)
    print(f"\nVerdict: {result.text}", file=out)
    return result.exit_code
