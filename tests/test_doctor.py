"""verbal-code --doctor (MCC-194): report, verdict and exit code."""

from __future__ import annotations

import io
import subprocess
import sys

import pytest

from verbal_code import doctor, gpu


def _report(backend: str, vendor: str = "amd") -> gpu.GpuReport:
    device = gpu.GpuDevice(
        vendor=vendor, name="AMD Radeon RX 9060 XT", pci_id="1002:7590",
        target="gfx1200", vram_total=16 * 1024**3, vram_used=1024**3,
        index=0, supported=True, official=True,
    )
    if backend == "cpu" and vendor == "none":
        return gpu.GpuReport()
    if backend == "cpu":
        return gpu.GpuReport(
            vendor, [device], False, "ROCm 6.x found; ROCm 7.2+ required", "cpu",
            hint="AMD GPU found but ROCm 6.x found; ROCm 7.2+ required.",
        )
    return gpu.GpuReport(vendor, [device], True, "ROCm 7 runtime found",
                         backend, chosen=device)


def _run(config=None, **kwargs) -> tuple[int, str]:
    out = io.StringIO()
    code = doctor.run_doctor(config or {}, out=out, env={}, **kwargs)
    return code, out.getvalue()


OK = doctor.Ct2Probe(True, 1)
NO_DEVICE = doctor.Ct2Probe(True, 0)


class TestVerdict:
    def test_working_rocm_is_gpu_ok(self):
        code, out = _run(report=_report("rocm"), probe=OK,
                         flavor=("rocm", "4.9.1"), marker="rocm")
        assert code == 0
        assert out.rstrip().endswith("Verdict: GPU OK")
        assert "gfx1200" in out and "officially supported by ROCm 7.2" in out
        assert "1.0 GiB / 16.0 GiB" in out
        assert "device=cuda compute_type=float16" in out

    def test_no_gpu_is_cpu_and_exits_0(self):
        code, out = _run(report=_report("cpu", "none"), probe=NO_DEVICE,
                         flavor=("pypi", "4.9.1"), marker="cpu")
        assert code == 0
        assert "Verdict: CPU (no GPU)" in out

    def test_pip_replaced_rocm_wheel_exits_1(self):
        code, out = _run(report=_report("rocm"), probe=NO_DEVICE,
                         flavor=("pypi", "4.9.1"), marker="rocm")
        assert code == 1
        assert "replaced by a pip upgrade" in out

    def test_gpu_problem_with_cpu_marker_exits_0(self):
        code, out = _run(report=_report("cpu"), probe=NO_DEVICE,
                         flavor=("pypi", "4.9.1"), marker="cpu")
        assert code == 0
        assert "CPU (GPU problem: ROCm 6.x found" in out

    def test_broken_import_exits_1_when_gpu_expected(self):
        probe = doctor.Ct2Probe(False, error="OSError: libhipblas.so.3")
        code, out = _run(report=_report("rocm"), probe=probe,
                         flavor=("rocm", "4.9.1"), marker="rocm")
        assert code == 1
        assert "does not import (OSError: libhipblas.so.3)" in out

    def test_old_install_without_marker_is_cpu_expected(self):
        code, out = _run(report=_report("rocm"), probe=NO_DEVICE,
                         flavor=("pypi", "4.8.4"), marker=None)
        assert code == 0
        assert "installed before GPU support" in out
        assert "ROCm build of CTranslate2 is not installed" in out


def test_env_vars_are_listed():
    out = io.StringIO()
    doctor.run_doctor({}, out=out, env={"HIP_VISIBLE_DEVICES": "1"},
                      report=_report("cpu", "none"), probe=NO_DEVICE,
                      flavor=("pypi", "4.9.1"), marker="cpu")
    text = out.getvalue()
    assert "HIP_VISIBLE_DEVICES" in text and "1" in text
    for name in doctor.GPU_ENV_VARS:
        assert name in text


@pytest.mark.parametrize(
    ("device", "compute", "count", "expected"),
    [
        ("auto", "auto", 1, ("cuda", "float16")),
        ("auto", "auto", 0, ("cpu", "int8")),
        ("cuda", "int8", 1, ("cuda", "int8")),  # explicit compute respected
        ("cpu", "auto", 1, ("cpu", "int8")),
    ],
)
def test_effective_whisper_device(device, compute, count, expected):
    assert doctor.effective_whisper_device(device, compute, count) == expected


class TestProbe:
    def test_reads_device_count(self):
        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 0, "4.9.1\n1\n", "")
        assert doctor.probe_ctranslate2(run=run) == doctor.Ct2Probe(True, 1)

    def test_import_failure_keeps_last_error_line(self):
        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(
                cmd, 1, "", "Traceback ...\nImportError: libamdhip64.so.7\n")
        probe = doctor.probe_ctranslate2(run=run)
        assert not probe.imported
        assert probe.error == "ImportError: libamdhip64.so.7"

    def test_timeout(self):
        def run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 60)
        assert not doctor.probe_ctranslate2(run=run).imported


def test_cli_doctor_skips_validation_and_needs_no_config(tmp_path):
    """--doctor runs with a config validate_config would reject."""
    bad = tmp_path / "config.yaml"
    bad.write_text("stt:\n  engine: nonsense\n")
    env = {"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(
        [sys.executable, "-m", "verbal_code", "--doctor", "-c", str(bad)],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert "Verdict:" in result.stdout, result.stderr
    # No marker in the scratch HOME: CPU is expected, so exit 0.
    assert result.returncode == 0


def test_cli_gpu_detect_prints_one_line(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "verbal_code", "--gpu-detect"],
        capture_output=True, text=True, timeout=60,
        env={"HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
    )
    assert result.returncode == 0
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 1 and lines[0].startswith("backend=")
