"""GPU detection (MCC-194) against a fake sysfs tree and fake commands."""

from __future__ import annotations

import subprocess
import sys

import pytest

from verbal_code import gpu

_CPU_AGENT = """\
*******
Agent 1
*******
  Name:                    AMD Ryzen 5 5600G with Radeon Graphics
  Marketing Name:          AMD Ryzen 5 5600G with Radeon Graphics
  Device Type:             CPU
  BDFID:                   0
"""


def _gpu_agent(n: int, target: str, bdfid: int, marketing: str) -> str:
    return f"""\
*******
Agent {n}
*******
  Name:                    {target}
  Uuid:                    GPU-1234
  Marketing Name:          {marketing}
  Vendor Name:             AMD
  Device Type:             GPU
  BDFID:                   {bdfid}
  ISA Info:
    ISA 1
      Name:                    amdgcn-amd-amdhsa--{target}
"""


def _rocminfo(*agents: str) -> str:
    return "ROCk module is loaded\n==========\nHSA Agents\n==========\n" + "".join(
        [_CPU_AGENT, *agents]
    )


# 12:00.0 -> BDFID 0x1200; 07:00.0 (an iGPU) -> 0x0700
DGPU = _gpu_agent(2, "gfx1200", 0x1200, "AMD Radeon RX 9060 XT")
IGPU = _gpu_agent(2, "gfx90c", 0x0700, "AMD Radeon Graphics")
LD_HIP7 = "\tlibamdhip64.so.7 (libc6,x86-64) => /opt/rocm/lib/libamdhip64.so.7\n"
LD_ROCM7 = LD_HIP7 + (
    "\tlibhipblas.so.3 (libc6,x86-64) => /opt/rocm/lib/libhipblas.so.3\n"
    "\tlibhiprand.so.1 (libc6,x86-64) => /opt/rocm/lib/libhiprand.so.1\n"
)
LD_ROCM6 = "\tlibamdhip64.so.6 (libc6,x86-64) => /opt/rocm/lib/libamdhip64.so.6\n"
LD_CUDA = (
    "\tlibcublas.so.12 (libc6,x86-64) => /usr/lib/libcublas.so.12\n"
    "\tlibcudnn.so.9 (libc6,x86-64) => /usr/lib/libcudnn.so.9\n"
)
SMI = "0, NVIDIA GeForce RTX 4070, 12282, 300, 8.9\n"


def _card(root, n: int, vendor: str, device: str, address: str,
          vram_total: int | None = None, vram_used: int | None = None) -> None:
    pci = root / "devices" / "pci0000:00" / f"0000:{address}"
    pci.mkdir(parents=True)
    (pci / "vendor").write_text(vendor + "\n")
    (pci / "device").write_text(device + "\n")
    if vram_total is not None:
        (pci / "mem_info_vram_total").write_text(f"{vram_total}\n")
        (pci / "mem_info_vram_used").write_text(f"{vram_used}\n")
    card = root / "class" / "drm" / f"card{n}"
    card.mkdir(parents=True)
    (card / "device").symlink_to(pci)
    # A connector entry next to the card must be ignored.
    (root / "class" / "drm" / f"card{n}-DP-1").mkdir()


class FakeRun:
    """Answers commands by program name; records every call."""

    def __init__(self, outputs: dict[str, object]):
        self.outputs = outputs
        self.calls: list[list[str]] = []

    def __call__(self, cmd, **kwargs):
        assert kwargs.get("timeout", 99) <= gpu.PROBE_TIMEOUT_SECONDS
        self.calls.append(cmd)
        name = cmd[0].rsplit("/", 1)[-1]
        out = self.outputs.get(name)
        if out is None:
            raise FileNotFoundError(name)
        if isinstance(out, BaseException):
            raise out
        if isinstance(out, tuple):
            code, stdout = out
            return subprocess.CompletedProcess(cmd, code, stdout, "")
        return subprocess.CompletedProcess(cmd, 0, out, "")


def _detect(tmp_path, outputs, *, kfd_ok=True, env=None, which=None,
            files=(), pip_dirs=(), needs=None, conf_dirs=()):
    run = FakeRun(outputs)
    present = set(files) | ({"/dev/kfd"} if kfd_ok is not None else set())
    report = gpu.detect(
        sysfs_root=str(tmp_path),
        run=run,
        env=env or {},
        which=which or (lambda name: f"/usr/bin/{name}"
                        if name in outputs else None),
        kfd_path="/dev/kfd",
        access=lambda path, mode: bool(kfd_ok),
        exists=lambda path: path in present,
        rocm_lib_dir="/opt/rocm/lib",
        nvidia_pip_lib_dirs=lambda: list(pip_dirs),
        needed=lambda path: list((needs or {}).get(path, [])),
        conf_dirs=lambda: list(conf_dirs),
    )
    return report, run


@pytest.fixture
def amd(tmp_path):
    _card(tmp_path, 1, "0x1002", "0x7590", "12:00.0", 16 * 1024**3, 1024**3)
    return tmp_path


class TestAmd:
    def test_supported_target_with_runtime_recommends_rocm(self, amd):
        report, _ = _detect(amd, {"rocminfo": _rocminfo(DGPU), "ldconfig": LD_ROCM7})
        assert report.recommended_backend == "rocm"
        assert report.runtime_ok
        assert report.chosen.target == "gfx1200"
        assert report.chosen.index == 0
        assert report.chosen.name == "AMD Radeon RX 9060 XT"
        assert report.chosen.official
        assert report.chosen.vram_total == 16 * 1024**3
        assert report.chosen.vram_free == 15 * 1024**3
        assert not report.needs_ld_library_path
        assert report.machine_line("cp312") == (
            "backend=rocm gfx=gfx1200 index=0 python=cp312 ld_path=0"
        )

    def test_dgpu_after_igpu_is_chosen_with_its_hip_index(self, amd):
        _card(amd, 0, "0x1002", "0x1638", "07:00.0")
        dgpu = _gpu_agent(3, "gfx1200", 0x1200, "AMD Radeon RX 9060 XT")
        report, _ = _detect(amd, {"rocminfo": _rocminfo(IGPU, dgpu),
                                  "ldconfig": LD_ROCM7})
        assert report.recommended_backend == "rocm"
        assert report.chosen.target == "gfx1200"
        # HIP counts the unsupported iGPU too.
        assert report.chosen.index == 1
        igpu = next(d for d in report.devices if d.target == "gfx90c")
        assert not igpu.supported
        assert igpu.support_note() == "not supported by the ROCm wheel"

    def test_built_but_uncertified_target_may_work(self, amd):
        agent = _gpu_agent(2, "gfx1030", 0x1200, "AMD Radeon RX 6800")
        report, _ = _detect(amd, {"rocminfo": _rocminfo(agent),
                                  "ldconfig": LD_ROCM7})
        assert report.recommended_backend == "rocm"
        assert report.chosen.supported and not report.chosen.official
        assert "may work" in report.chosen.support_note()

    def test_only_unsupported_target_means_cpu(self, amd):
        report, _ = _detect(amd, {"rocminfo": _rocminfo(IGPU), "ldconfig": LD_ROCM7})
        assert report.recommended_backend == "cpu"
        assert "gfx90c" in report.runtime_detail
        assert report.hint

    def test_no_kfd_access_means_cpu_with_groups_hint(self, amd):
        report, _ = _detect(amd, {"rocminfo": _rocminfo(DGPU), "ldconfig": LD_ROCM7},
                            kfd_ok=False)
        assert report.recommended_backend == "cpu"
        assert "render" in report.hint and "video" in report.hint

    def test_rocm6_only_means_cpu_with_version_hint(self, amd):
        report, _ = _detect(amd, {"rocminfo": _rocminfo(DGPU), "ldconfig": LD_ROCM6})
        assert report.recommended_backend == "cpu"
        assert "ROCm 6.x found; ROCm 7.2+ required" in report.runtime_detail

    def test_rocm_libs_outside_ld_cache_need_ld_library_path(self, amd):
        report, _ = _detect(amd, {"rocminfo": _rocminfo(DGPU), "ldconfig": ""},
                            files={"/opt/rocm/lib/libamdhip64.so.7",
                                   "/opt/rocm/lib/libhipblas.so.3",
                                   "/opt/rocm/lib/libhiprand.so.1"})
        assert report.recommended_backend == "rocm"
        assert report.needs_ld_library_path
        assert report.machine_line("cp312").endswith("ld_path=1")

    def test_hip_runtime_without_hipblas_hiprand_means_cpu(self, amd):
        """ryan-dev's case: rocm-hip-runtime alone, no hipblas/hiprand."""
        report, _ = _detect(amd, {"rocminfo": _rocminfo(DGPU), "ldconfig": LD_HIP7})
        assert report.recommended_backend == "cpu"
        assert "libhipblas.so.3 (hipblas)" in report.runtime_detail
        assert "libhiprand.so.1 (hiprand)" in report.runtime_detail
        # A missing library's own dependencies are named in the same pass.
        assert "librocrand.so.1 (rocrand)" in report.runtime_detail
        assert "librocblas.so.5 (rocblas)" in report.runtime_detail
        assert report.fix.startswith("sudo apt install hipblas ")
        assert {"hiprand", "rocrand", "rocblas"} <= set(report.fix.split())
        assert report.fix.endswith("&& sudo ldconfig")
        assert report.fix in report.hint
        statuses = {lib.name: lib.status for lib in report.libraries}
        assert statuses["libamdhip64.so.7"] == gpu.LIB_OK
        assert statuses["libhiprand.so.1"] == gpu.LIB_MISSING

    def test_rocminfo_missing_means_cpu(self, amd):
        report, _ = _detect(amd, {"ldconfig": LD_ROCM7})
        assert report.recommended_backend == "cpu"
        assert "ROCm 7.2+ runtime not detected" in report.hint

    def test_rocminfo_fallback_path_is_used(self, amd):
        report, run = _detect(
            amd, {"rocminfo": _rocminfo(DGPU), "ldconfig": LD_ROCM7},
            which=lambda name: "/sbin/ldconfig" if name == "ldconfig" else None,
            files={gpu.ROCMINFO_FALLBACK},
        )
        assert report.recommended_backend == "rocm"
        assert [gpu.ROCMINFO_FALLBACK] in run.calls

    def test_rocminfo_timeout_means_cpu(self, amd):
        timeout = subprocess.TimeoutExpired("rocminfo", 5)
        report, _ = _detect(amd, {"rocminfo": timeout, "ldconfig": LD_ROCM7})
        assert report.recommended_backend == "cpu"
        assert "did not run" in report.runtime_detail

    def test_rocminfo_failure_means_cpu(self, amd):
        report, _ = _detect(amd, {"rocminfo": (1, ""), "ldconfig": LD_ROCM7})
        assert report.recommended_backend == "cpu"
        assert "status 1" in report.runtime_detail

    def test_hsa_override_is_never_set(self, amd, monkeypatch):
        monkeypatch.delenv("HSA_OVERRIDE_GFX_VERSION", raising=False)
        _detect(amd, {"rocminfo": _rocminfo(IGPU), "ldconfig": LD_ROCM7})
        import os
        assert "HSA_OVERRIDE_GFX_VERSION" not in os.environ


# ROCm 7.2.1's real chain behind the wheel (readelf -d on ryan-dev), trimmed
# to the ROCm libraries plus one distribution library.
ROCM = "/opt/rocm/lib"
CHAIN = {
    f"{ROCM}/libamdhip64.so.7": [
        "libhsa-runtime64.so.1", "libstdc++.so.6", "libc.so.6"],
    f"{ROCM}/libhsa-runtime64.so.1": ["libnuma.so.1", "libc.so.6"],
    f"{ROCM}/libhipblas.so.3": ["librocblas.so.5", "libc.so.6"],
    f"{ROCM}/librocblas.so.5": ["libamdhip64.so.7", "libm.so.6"],
    f"{ROCM}/libhiprand.so.1": ["librocrand.so.1", "libamdhip64.so.7"],
    f"{ROCM}/librocrand.so.1": ["libamdhip64.so.7"],
}


def _ld(*names: str, directory: str = ROCM) -> str:
    return "".join(f"\t{n} (libc6,x86-64) => {directory}/{n}\n" for n in names)


ALL_ROCM = [path.rsplit("/", 1)[1] for path in CHAIN]
LD_NUMA = _ld("libnuma.so.1", directory="/lib/x86_64-linux-gnu")


def _without(*names: str) -> list[str]:
    return [n for n in ALL_ROCM if n not in names]


class TestRocmLibraries:
    """The full library chain behind the ROCm wheel (MCC-201)."""

    def _detect(self, amd, ld, files=(), conf_dirs=(ROCM,), needs=None):
        return _detect(amd, {"rocminfo": _rocminfo(DGPU), "ldconfig": ld},
                       files=set(files), needs=CHAIN if needs is None else needs,
                       conf_dirs=conf_dirs)[0]

    def test_all_libraries_present_means_rocm(self, amd):
        report = self._detect(amd, _ld(*ALL_ROCM) + LD_NUMA)
        assert report.recommended_backend == "rocm"
        assert report.library_problems() == []
        names = [lib.name for lib in report.libraries]
        # Walked through the real DT_NEEDED entries; glibc and libstdc++ never.
        assert set(names) == {*ALL_ROCM, "libnuma.so.1"}
        assert "libc.so.6" not in names and "libstdc++.so.6" not in names
        rocrand = next(lib for lib in report.libraries if lib.name == "librocrand.so.1")
        assert rocrand.needed_by == "libhiprand.so.1"
        assert rocrand.package == "rocrand"
        assert not report.needs_ld_library_path

    def test_missing_hipblas_and_hiprand_name_their_packages(self, amd):
        present = _without("libhipblas.so.3", "libhiprand.so.1")
        report = self._detect(amd, _ld(*present) + LD_NUMA)
        assert report.recommended_backend == "cpu"
        assert "libhipblas.so.3 (hipblas)" in report.runtime_detail
        assert "libhiprand.so.1 (hiprand)" in report.runtime_detail
        assert "sudo apt install hipblas" in report.fix
        assert "hiprand" in report.hint and "hipblas" in report.hint

    def test_on_disk_but_not_cached_needs_ldconfig(self, amd):
        """ryan-dev, step 1: the packages were installed, the cache was stale."""
        cached = _without("libhipblas.so.3", "libhiprand.so.1")
        files = {f"{ROCM}/libhipblas.so.3", f"{ROCM}/libhiprand.so.1"}
        report = self._detect(amd, _ld(*cached) + LD_NUMA, files=files)
        assert report.recommended_backend == "cpu"
        stale = [lib.name for lib in report.library_problems()]
        assert stale == ["libhipblas.so.3", "libhiprand.so.1"]
        assert all(lib.status == gpu.LIB_STALE for lib in report.library_problems())
        assert "not in the loader cache: libhipblas.so.3, libhiprand.so.1" \
            in report.runtime_detail
        assert report.fix == "sudo ldconfig"
        assert "apt install" not in report.hint
        assert "sudo ldconfig" in report.hint

    def test_missing_transitive_rocrand_is_named(self, amd):
        """ryan-dev, step 2: hiprand installed, the rocrand behind it not."""
        present = [n for n in ALL_ROCM if n != "librocrand.so.1"]
        report = self._detect(amd, _ld(*present) + LD_NUMA)
        assert report.recommended_backend == "cpu"
        (problem,) = report.library_problems()
        assert (problem.name, problem.package, problem.needed_by) == (
            "librocrand.so.1", "rocrand", "libhiprand.so.1")
        assert report.fix == "sudo apt install rocrand && sudo ldconfig"
        assert "librocrand.so.1 (rocrand)" in report.hint

    def test_missing_library_and_its_known_dependency_in_one_pass(self, amd):
        """A missing hiprand can't be read, so the table names rocrand."""
        present = _without("libhiprand.so.1", "librocrand.so.1")
        report = self._detect(amd, _ld(*present) + LD_NUMA)
        assert [lib.name for lib in report.library_problems()] == [
            "libhiprand.so.1", "librocrand.so.1"]
        assert "sudo apt install hiprand rocrand" in report.fix

    def test_missing_distribution_library(self, amd):
        report = self._detect(amd, _ld(*ALL_ROCM))
        (problem,) = report.library_problems()
        assert (problem.name, problem.package) == ("libnuma.so.1", "libnuma1")

    def test_unknown_library_points_to_apt_file(self, amd):
        needs = {**CHAIN, f"{ROCM}/librocrand.so.1": ["libmystery.so.9"]}
        report = self._detect(amd, _ld(*ALL_ROCM) + LD_NUMA, needs=needs)
        (problem,) = report.library_problems()
        assert problem.name == "libmystery.so.9" and problem.package == ""
        assert "package unknown" in report.runtime_detail
        assert "apt-file search libmystery.so.9" in report.fix
        assert "apt-file search" in problem.describe()

    def test_unconfigured_rocm_dir_uses_ld_library_path_not_ldconfig(self, amd):
        """A ROCm tree the loader isn't configured for (no ld.so.conf entry,
        nothing cached from it) still works through LD_LIBRARY_PATH."""
        files = {f"{ROCM}/{n}" for n in ALL_ROCM}
        report = self._detect(amd, LD_NUMA, files=files, conf_dirs=())
        assert report.recommended_backend == "rocm"
        assert report.needs_ld_library_path
        assert all(lib.status == gpu.LIB_LD_PATH for lib in report.libraries
                   if lib.name != "libnuma.so.1")

    def test_cached_from_rocm_dir_counts_as_configured(self, amd):
        """No ld.so.conf entry seen, but the cache already holds ROCm libs from
        the directory: an uncached one there is stale, not LD_LIBRARY_PATH."""
        cached = [n for n in ALL_ROCM if n != "libhiprand.so.1"]
        report = self._detect(amd, _ld(*cached) + LD_NUMA,
                              files={f"{ROCM}/libhiprand.so.1"}, conf_dirs=())
        assert [lib.status for lib in report.library_problems()] == [gpu.LIB_STALE]

    def test_libraries_reach_the_report_when_overridden_to_cpu(self, amd):
        report = _detect(amd, {"rocminfo": _rocminfo(DGPU),
                               "ldconfig": _ld(*ALL_ROCM) + LD_NUMA},
                         env={gpu.OVERRIDE_ENV: "cpu"}, needs=CHAIN)[0]
        assert report.recommended_backend == "cpu"
        assert report.libraries


def test_ld_conf_dirs_follows_includes(tmp_path):
    (tmp_path / "ld.so.conf.d").mkdir()
    (tmp_path / "ld.so.conf").write_text(
        "include ld.so.conf.d/*.conf\n/usr/local/lib  # local\n")
    (tmp_path / "ld.so.conf.d" / "rocm.conf").write_text("/opt/rocm/lib\n")
    (tmp_path / "ld.so.conf.d" / "x86_64.conf").write_text(
        "# Multiarch\n/lib/x86_64-linux-gnu\n")
    assert gpu.ld_conf_dirs(str(tmp_path / "ld.so.conf")) == [
        "/opt/rocm/lib", "/lib/x86_64-linux-gnu", "/usr/local/lib"]
    assert gpu.ld_conf_dirs(str(tmp_path / "missing.conf")) == []


def test_ld_cache_prefers_64_bit_entries():
    text = ("\tlibz.so.1 (libc6) => /usr/lib32/libz.so.1\n"
            "\tlibz.so.1 (libc6,x86-64) => /lib/x86_64-linux-gnu/libz.so.1\n")
    assert gpu._parse_ld_cache(text) == {"libz.so.1": "/lib/x86_64-linux-gnu/libz.so.1"}


def test_library_table_lives_beside_the_pin():
    from verbal_code import ct2_backend

    assert set(ct2_backend.ROCM_WHEEL_NEEDS) <= set(ct2_backend.ROCM_LIBRARIES)
    for _name, (package, needs) in ct2_backend.ROCM_LIBRARIES.items():
        assert package
        assert set(needs) <= set(ct2_backend.ROCM_LIBRARIES)


@pytest.fixture
def nvidia(tmp_path):
    _card(tmp_path, 0, "0x10de", "0x2786", "01:00.0")
    return tmp_path


class TestNvidia:
    def test_driver_and_libs_recommend_cuda(self, nvidia):
        report, _ = _detect(nvidia, {"nvidia-smi": SMI, "ldconfig": LD_CUDA})
        assert report.recommended_backend == "cuda"
        assert report.chosen.name == "NVIDIA GeForce RTX 4070"
        assert report.chosen.target == "8.9"
        assert report.chosen.vram_total == 12282 * 1024**2
        assert report.machine_line("cp312").startswith("backend=cuda cc=8.9 index=0")

    def test_pip_installed_cuda_libs_count(self, nvidia):
        report, _ = _detect(
            nvidia, {"nvidia-smi": SMI, "ldconfig": ""},
            files={"/site/nvidia/cublas/lib/libcublas.so.12",
                   "/site/nvidia/cudnn/lib/libcudnn.so.9"},
            pip_dirs=["/site/nvidia/cublas/lib", "/site/nvidia/cudnn/lib"],
        )
        assert report.recommended_backend == "cuda"

    def test_no_driver_means_cpu(self, nvidia):
        report, _ = _detect(nvidia, {"ldconfig": LD_CUDA})
        assert report.recommended_backend == "cpu"
        assert "nvidia-smi" in report.runtime_detail

    def test_missing_cuda_libs_means_cpu(self, nvidia):
        report, _ = _detect(nvidia, {"nvidia-smi": SMI, "ldconfig": ""})
        assert report.recommended_backend == "cpu"
        assert "libcudnn.so.9" in report.hint


class TestPrecedence:
    @pytest.fixture
    def both(self, amd):
        _card(amd, 2, "0x10de", "0x2786", "01:00.0")
        return amd

    def _outputs(self):
        return {"rocminfo": _rocminfo(DGPU), "nvidia-smi": SMI,
                "ldconfig": LD_ROCM7 + LD_CUDA}

    def test_both_working_prefers_more_vram(self, both):
        report, _ = _detect(both, self._outputs())
        assert report.vendor == "both"
        assert report.recommended_backend == "rocm"  # 16 GiB beats 12 GiB

    @pytest.mark.parametrize("override", ["cuda", "CUDA", " cuda "])
    def test_env_override_picks_the_vendor(self, both, override):
        report, _ = _detect(both, self._outputs(),
                            env={gpu.OVERRIDE_ENV: override})
        assert report.recommended_backend == "cuda"

    def test_env_override_cpu_forces_cpu(self, both):
        report, _ = _detect(both, self._outputs(), env={gpu.OVERRIDE_ENV: "cpu"})
        assert report.recommended_backend == "cpu"

    def test_override_to_a_broken_backend_means_cpu(self, amd):
        report, _ = _detect(amd, {"rocminfo": _rocminfo(DGPU), "ldconfig": LD_ROCM7},
                            env={gpu.OVERRIDE_ENV: "cuda"})
        assert report.recommended_backend == "cpu"
        assert "no cuda GPU found" in report.runtime_detail


def test_no_gpu_means_cpu(tmp_path):
    report, run = _detect(tmp_path, {"rocminfo": _rocminfo(DGPU)})
    assert report.vendor == "none"
    assert report.recommended_backend == "cpu"
    assert run.calls == []  # nothing to probe without a GPU


def test_detection_never_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(gpu, "_detect", lambda *a: 1 / 0)
    report = gpu.detect(sysfs_root=str(tmp_path))
    assert report.recommended_backend == "cpu"
    assert "detection failed" in report.runtime_detail


def test_import_pulls_in_no_gpu_library():
    code = ("import sys, verbal_code.gpu; "
            "print(any(m.split('.')[0] in ('ctranslate2', 'faster_whisper') "
            "for m in sys.modules))")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True,
                         text=True, check=True).stdout.strip()
    assert out == "False"


@pytest.mark.parametrize(
    ("version", "free_threaded", "tag"),
    [((3, 12), False, "cp312"), ((3, 14), True, "cp314t"), ((3, 10), False, "cp310")],
)
def test_python_tag(version, free_threaded, tag):
    assert gpu.python_tag(version, free_threaded) == tag


def test_marker_is_read_from_the_stamp(tmp_path):
    stamp = tmp_path / "installed-version"
    stamp.write_text("version=0.1.0\ncommit=abc\ngpu_backend=rocm\n")
    assert gpu.read_marker(str(stamp)) == "rocm"
    stamp.write_text("version=0.1.0\ncommit=abc\n")
    assert gpu.read_marker(str(stamp)) is None
    assert gpu.read_marker(str(tmp_path / "missing")) is None


def test_elf_needed_reads_dynamic_dependencies():
    # The interpreter's own binary is a real ELF with DT_NEEDED entries.
    import ctypes.util

    libc = ctypes.util.find_library("c")
    assert libc
    import glob

    candidates = glob.glob(f"/lib/x86_64-linux-gnu/{libc}") + glob.glob(
        f"/usr/lib/x86_64-linux-gnu/{libc}"
    )
    if not candidates:
        pytest.skip("libc not found at a known path")
    assert "ld-linux-x86-64.so.2" in gpu.elf_needed(candidates[0])


def test_elf_needed_on_non_elf_is_empty(tmp_path):
    junk = tmp_path / "junk.so"
    junk.write_bytes(b"not an elf")
    assert gpu.elf_needed(str(junk)) == []
    assert gpu.elf_needed(str(tmp_path / "missing.so")) == []


class TestRuntimeReport:
    @pytest.mark.parametrize("config", [
        {"stt": {"engine": "parakeet"}},
        {"stt": {"engine": "whisper", "whisper": {"device": "cpu"}}},
    ])
    def test_skipped_unless_whisper_may_use_the_gpu(self, config, monkeypatch):
        monkeypatch.setattr(gpu, "detect", lambda **k: pytest.fail("detected"))
        assert gpu.runtime_report(config) is None

    @pytest.mark.parametrize("device", ["auto", "cuda"])
    def test_runs_for_whisper_auto_or_cuda(self, device, monkeypatch):
        monkeypatch.setattr(gpu, "detect", lambda **k: gpu.GpuReport())
        config = {"stt": {"engine": "whisper", "whisper": {"device": device}}}
        assert gpu.runtime_report(config) is not None
