"""GPU detection for Whisper acceleration (MCC-194).

Answers one question for the installer, ``--doctor`` and the Whisper engine:
which CTranslate2 *backend* can this machine use?

* ``rocm``: an AMD GPU whose gfx target the pinned ROCm wheel was built for,
  with a working ROCm 7 runtime (``rocminfo``, ``/dev/kfd``, ``libamdhip64.so.7``).
* ``cuda``: an NVIDIA GPU with a working driver (``nvidia-smi``) and the CUDA
  12 cuBLAS / cuDNN 9 libraries the PyPI ``ctranslate2`` wheel loads.
* ``cpu``: everything else, including any probe that fails or times out.

This module must stay cheap to import: it never imports ``ctranslate2``,
faster-whisper or any GPU library. Every probe is injectable (``sysfs_root``,
``run``, ``which``, ...) so tests drive it with a fake sysfs tree and fake
command output, and every subprocess call has a timeout of at most 5 s.
Detection never raises; a failure resolves to ``cpu`` with a reason.
"""

from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import sysconfig
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

AMD_VENDOR = "0x1002"
NVIDIA_VENDOR = "0x10de"
BACKENDS = ("rocm", "cuda", "cpu")
OVERRIDE_ENV = "VERBAL_CODE_GPU_BACKEND"
PROBE_TIMEOUT_SECONDS = 5

# gfx targets the pinned CTranslate2 ROCm wheel is compiled for
# (python/tools/prepare_build_environment_linux_rocm.sh at the pinned tag;
# see verbal_code/ct2_backend.py). Anything else, such as a Ryzen 5600G's
# gfx90c iGPU, cannot run it.
ROCM_BUILT_TARGETS = (
    "gfx1030", "gfx1031", "gfx1032", "gfx1035",
    "gfx1100", "gfx1101", "gfx1102", "gfx1103",
    "gfx1150", "gfx1151",
    "gfx1200", "gfx1201",
)
# The subset AMD's ROCm 7.2 support matrix lists for Radeon cards.
ROCM_OFFICIAL_TARGETS = ("gfx1100", "gfx1101", "gfx1200", "gfx1201")

ROCM_LIB_DIR = "/opt/rocm/lib"
# ROCm libraries the wheel's libctranslate2 links (readelf -d) besides the
# HIP runtime, and the AMD apt package that ships each.
ROCM_WHEEL_LIBS = (("libhipblas.so.3", "hipblas"), ("libhiprand.so.1", "hiprand"))
ROCMINFO_FALLBACK = "/opt/rocm/bin/rocminfo"
GROUPS_HINT = (
    "add your user to the 'render' and 'video' groups "
    "(sudo usermod -aG render,video $USER), then log out and in"
)

# The installed-version stamp install.sh/update.sh write (scripts/install-lib.sh
# STAMP_FILE); its gpu_backend= line is the backend marker (MCC-195).
STAMP_FILE = os.path.expanduser("~/.local/share/verbal-code/installed-version")

RunFn = Callable[..., subprocess.CompletedProcess]


@dataclass
class GpuDevice:
    """One GPU as detection sees it."""

    vendor: str  # "amd" | "nvidia"
    name: str
    pci_id: str  # vendor:device, e.g. "1002:7590"
    pci_address: str = ""  # e.g. "0000:12:00.0"
    target: str = ""  # gfx target (AMD) or compute capability (NVIDIA)
    vram_total: int | None = None  # bytes
    vram_used: int | None = None  # bytes
    index: int | None = None  # HIP / CUDA device index
    supported: bool = False  # the backend's build can run on it
    official: bool = False  # vendor-certified (AMD: ROCm 7.2 support list)

    @property
    def vram_free(self) -> int | None:
        if self.vram_total is None or self.vram_used is None:
            return None
        return max(self.vram_total - self.vram_used, 0)

    def support_note(self) -> str:
        if self.vendor != "amd":
            return ""
        if self.official:
            return "officially supported by ROCm 7.2"
        if self.supported:
            return "built but not AMD-certified; may work"
        return "not supported by the ROCm wheel"


@dataclass
class GpuReport:
    """What detection found. ``recommended_backend`` is the answer."""

    vendor: str = "none"  # "amd" | "nvidia" | "both" | "none"
    devices: list[GpuDevice] = field(default_factory=list)
    runtime_ok: bool = False
    runtime_detail: str = "no GPU found"
    recommended_backend: str = "cpu"
    chosen: GpuDevice | None = None
    # True when the ROCm libraries resolve only from /opt/rocm/lib, not from
    # the dynamic linker cache: the launcher must then add it to
    # LD_LIBRARY_PATH (MCC-198).
    needs_ld_library_path: bool = False
    # One actionable line when a GPU exists but can't be used, and its fix
    # alone (a command or a pointer) for --doctor's verdict.
    hint: str = ""
    fix: str = ""

    def machine_line(self, python: str | None = None) -> str:
        """``backend=rocm gfx=gfx1200 index=0 python=cp312 ld_path=0``: the
        line install-lib.sh parses."""
        chosen = self.chosen
        parts = [f"backend={self.recommended_backend}"]
        if chosen is not None and chosen.vendor == "amd":
            parts.append(f"gfx={chosen.target}")
        elif chosen is not None:
            parts.append(f"cc={chosen.target or 'unknown'}")
        if chosen is not None and chosen.index is not None:
            parts.append(f"index={chosen.index}")
        parts.append(f"python={python or python_tag()}")
        parts.append(f"ld_path={int(self.needs_ld_library_path)}")
        return " ".join(parts)

    def summary(self) -> str:
        """One human line, e.g. for install.sh's [OK] message."""
        chosen = self.chosen
        if self.recommended_backend == "cpu":
            return f"no usable GPU ({self.runtime_detail}) → backend: cpu"
        assert chosen is not None
        return (
            f"{chosen.name} ({chosen.target}), {self.runtime_detail} "
            f"→ GPU backend: {self.recommended_backend}"
        )


@dataclass
class _VendorResult:
    devices: list[GpuDevice]
    runtime_ok: bool
    detail: str
    chosen: GpuDevice | None = None
    needs_ld_library_path: bool = False
    hint: str = ""
    fix: str = ""


_README_FIX = "see README → GPU acceleration"
_ROCM_FIX = "install ROCm 7.2+ (" + _README_FIX + ")"


# ── Small helpers ──

def python_tag(
    version: tuple[int, int] | None = None, free_threaded: bool | None = None
) -> str:
    """The CPython wheel tag of this interpreter: ``cp312``, or ``cp314t``
    for a free-threaded (no-GIL) build."""
    major, minor = version or sys.version_info[:2]
    if free_threaded is None:
        free_threaded = bool(sysconfig.get_config_var("Py_GIL_DISABLED"))
    return f"cp{major}{minor}{'t' if free_threaded else ''}"


def _read(path: str) -> str | None:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return None


def _read_int(path: str) -> int | None:
    value = _read(path)
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _probe(run: RunFn, cmd: list[str]) -> subprocess.CompletedProcess | None:
    """Run ``cmd``; None when it is missing, times out or fails to start."""
    try:
        return run(
            cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_SECONDS
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def _pci_cards(sysfs_root: str) -> list[tuple[str, str, str]]:
    """(vendor, pci_id, device_dir) per DRM card, one per PCI device."""
    seen: set[str] = set()
    cards = []
    for card in sorted(glob.glob(os.path.join(sysfs_root, "class/drm/card*"))):
        if not re.fullmatch(r"card\d+", os.path.basename(card)):
            continue  # connectors such as card1-DP-1
        device_dir = os.path.join(card, "device")
        vendor = (_read(os.path.join(device_dir, "vendor")) or "").lower()
        device = (_read(os.path.join(device_dir, "device")) or "").lower()
        if not vendor:
            continue
        address = os.path.basename(os.path.realpath(device_dir))
        if address in seen:
            continue
        seen.add(address)
        pci_id = f"{vendor.removeprefix('0x')}:{device.removeprefix('0x')}"
        cards.append((vendor, pci_id, device_dir))
    return cards


def _ld_cache(run: RunFn) -> str:
    result = _probe(run, ["ldconfig", "-p"])
    if result is None or result.returncode != 0:
        result = _probe(run, ["/sbin/ldconfig", "-p"])
    return result.stdout if result is not None and result.returncode == 0 else ""


# ── AMD ──

def _parse_rocminfo(text: str) -> list[dict[str, str]]:
    """GPU agents in rocminfo order, each {name, marketing, bdfid}."""
    agents: list[dict[str, str]] = []
    for block in re.split(r"^\*+\s*\nAgent \d+\s*\n\*+\s*$", text, flags=re.M)[1:]:
        fields: dict[str, str] = {}
        for line in block.splitlines():
            # Top-level agent fields are indented two spaces; the nested ISA
            # section repeats "Name:" deeper.
            match = re.match(r"^  (\S[^:]*):\s*(.*?)\s*$", line)
            if match and match.group(1) not in fields:
                fields[match.group(1)] = match.group(2)
        if fields.get("Device Type") != "GPU":
            continue
        name = fields.get("Name", "")
        if not re.fullmatch(r"gfx[0-9a-f]+", name):
            continue
        agents.append({
            "name": name,
            "marketing": fields.get("Marketing Name", ""),
            "bdfid": fields.get("BDFID", ""),
        })
    return agents


def _bdfid_to_address(bdfid: str) -> str:
    """rocminfo's BDFID (bus<<8 | device<<3 | function) as a PCI address."""
    try:
        value = int(bdfid)
    except ValueError:
        return ""
    return f"{value >> 8:02x}:{(value >> 3) & 0x1f:02x}.{value & 0x7}"


def _detect_amd(
    cards: list[tuple[str, str, str]],
    run: RunFn,
    which: Callable[[str], str | None],
    kfd_path: str,
    access: Callable[[str, int], bool],
    exists: Callable[[str], bool],
    rocm_lib_dir: str,
) -> _VendorResult:
    by_address: dict[str, GpuDevice] = {}
    for _vendor, pci_id, device_dir in cards:
        address = os.path.basename(os.path.realpath(device_dir))
        by_address[address] = GpuDevice(
            vendor="amd",
            name=f"AMD GPU [{pci_id}]",
            pci_id=pci_id,
            pci_address=address,
            vram_total=_read_int(os.path.join(device_dir, "mem_info_vram_total")),
            vram_used=_read_int(os.path.join(device_dir, "mem_info_vram_used")),
        )
    devices = list(by_address.values())

    def failed(detail: str, fix: str = _ROCM_FIX, hint: str = "") -> _VendorResult:
        return _VendorResult(devices, False, detail, fix=fix, hint=hint or (
            f"AMD GPU found but {detail}. See README → GPU acceleration."
        ))

    rocminfo = which("rocminfo") or (
        ROCMINFO_FALLBACK if exists(ROCMINFO_FALLBACK) else None
    )
    if rocminfo is None:
        return failed("ROCm 7.2+ runtime not detected (no rocminfo)")
    result = _probe(run, [rocminfo])
    if result is None:
        return failed("rocminfo did not run (timed out or failed to start)")
    if result.returncode != 0:
        if "permission" in (result.stdout + result.stderr).lower():
            return failed("no permission to use the GPU", GROUPS_HINT,
                          f"ROCm: {GROUPS_HINT}.")
        return failed(f"rocminfo exited with status {result.returncode}",
                      "run rocminfo to see the error")
    agents = _parse_rocminfo(result.stdout)
    if not agents:
        return failed("rocminfo lists no GPU agent")

    if not exists(kfd_path) or not access(kfd_path, os.R_OK | os.W_OK):
        return failed(
            f"{kfd_path} is not accessible", GROUPS_HINT,
            f"AMD GPU found but {kfd_path} is not accessible: {GROUPS_HINT}.",
        )

    ld_cache = _ld_cache(run)

    def resolves(lib: str) -> tuple[bool, bool]:
        """(in the linker cache, under rocm_lib_dir)."""
        return lib in ld_cache, exists(os.path.join(rocm_lib_dir, lib))

    if not any(resolves("libamdhip64.so.7")):
        if any(resolves("libamdhip64.so.6")):
            return failed("ROCm 6.x found; ROCm 7.2+ required")
        return failed("ROCm 7.2+ runtime not detected (no libamdhip64.so.7)")
    # The wheel links hipBLAS and hipRAND too; the HIP runtime package
    # alone (rocm-hip-runtime) doesn't ship them.
    missing = [lib for lib, _pkg in ROCM_WHEEL_LIBS if not any(resolves(lib))]
    if missing:
        packages = " ".join(pkg for lib, pkg in ROCM_WHEEL_LIBS if lib in missing)
        return failed(
            f"ROCm libraries missing: {', '.join(missing)}",
            f"sudo apt install {packages}",
            f"AMD GPU and ROCm runtime found, but CTranslate2 also needs "
            f"{', '.join(missing)}: sudo apt install {packages} "
            f"(from AMD's ROCm repository). See README → GPU acceleration.",
        )
    in_cache = all(resolves(lib)[0] for lib in ("libamdhip64.so.7",
                                                *(lib for lib, _ in ROCM_WHEEL_LIBS)))
    in_rocm_dir = not in_cache

    # HIP numbers the GPU agents in rocminfo's order, unsupported iGPUs
    # included, so the HIP index is the position among *all* GPU agents.
    chosen: GpuDevice | None = None
    for index, agent in enumerate(agents):
        address = _bdfid_to_address(agent["bdfid"])
        device = next(
            (d for a, d in by_address.items() if address and a.endswith(address)),
            None,
        )
        if device is None:
            device = GpuDevice(vendor="amd", name="AMD GPU", pci_id="1002:?")
            devices.append(device)
        device.target = agent["name"]
        device.index = index
        if agent["marketing"] and agent["marketing"] != "AMD Radeon Graphics":
            device.name = agent["marketing"]
        elif agent["marketing"]:
            device.name = f"{agent['marketing']} [{device.pci_id}]"
        device.supported = device.target in ROCM_BUILT_TARGETS
        device.official = device.target in ROCM_OFFICIAL_TARGETS
        if chosen is None and device.supported:
            chosen = device

    if chosen is None:
        found = ", ".join(a["name"] for a in agents)
        return failed(f"no GPU target the ROCm wheel supports (found {found})",
                      _README_FIX)
    return _VendorResult(
        devices,
        True,
        "ROCm 7 runtime found",
        chosen=chosen,
        needs_ld_library_path=in_rocm_dir,
    )


# ── NVIDIA ──

_NVIDIA_LIBS = ("libcublas.so.12", "libcudnn.so.9")


def _nvidia_pip_lib_dirs() -> list[str]:
    """Library dirs of the nvidia-*-cu12 pip wheels, when installed."""
    dirs = []
    for site in sys.path:
        dirs += glob.glob(os.path.join(site, "nvidia", "*", "lib"))
    return dirs


def _detect_nvidia(
    cards: list[tuple[str, str, str]],
    run: RunFn,
    which: Callable[[str], str | None],
    exists: Callable[[str], bool],
    pip_lib_dirs: Callable[[], list[str]],
) -> _VendorResult:
    devices = [
        GpuDevice(vendor="nvidia", name=f"NVIDIA GPU [{pci_id}]", pci_id=pci_id,
                  pci_address=os.path.basename(os.path.realpath(device_dir)))
        for _vendor, pci_id, device_dir in cards
    ]

    def failed(detail: str) -> _VendorResult:
        return _VendorResult(devices, False, detail, fix=_README_FIX, hint=(
            f"NVIDIA GPU found but {detail}. See README → GPU acceleration."
        ))

    smi = which("nvidia-smi")
    if smi is None:
        return failed("the NVIDIA driver is not installed (no nvidia-smi)")
    result = _probe(run, [
        smi,
        "--query-gpu=index,name,memory.total,memory.used,compute_cap",
        "--format=csv,noheader,nounits",
    ])
    if result is None or result.returncode != 0:
        return failed("nvidia-smi failed (driver not loaded?)")

    smi_devices = []
    for line in result.stdout.strip().splitlines():
        cols = [c.strip() for c in line.split(",")]
        if len(cols) < 5:
            continue
        try:
            index = int(cols[0])
            total = int(float(cols[2])) * 1024 * 1024
            used = int(float(cols[3])) * 1024 * 1024
        except ValueError:
            continue
        smi_devices.append(GpuDevice(
            vendor="nvidia", name=cols[1], pci_id=devices[0].pci_id if devices
            else "10de:?", target=cols[4], vram_total=total, vram_used=used,
            index=index, supported=True, official=True,
        ))
    if not smi_devices:
        return failed("nvidia-smi lists no GPU")

    ld_cache = _ld_cache(run)
    lib_dirs = pip_lib_dirs()
    missing = [
        lib for lib in _NVIDIA_LIBS
        if lib not in ld_cache
        and not any(exists(os.path.join(d, lib)) for d in lib_dirs)
    ]
    if missing:
        return _VendorResult(
            smi_devices, False, f"CUDA libraries missing: {', '.join(missing)}",
            fix="install the CUDA 12 cuBLAS and cuDNN 9 libraries (" + _README_FIX
            + ")",
            hint=(
                "NVIDIA GPU found but the CUDA 12 cuBLAS / cuDNN 9 libraries are "
                f"missing ({', '.join(missing)}). See README → GPU acceleration."
            ),
        )
    return _VendorResult(
        smi_devices, True, "NVIDIA driver and CUDA 12 libraries found",
        chosen=smi_devices[0],
    )


# ── Public entry point ──

def detect(
    sysfs_root: str = "/sys",
    run: RunFn = subprocess.run,
    env: Mapping[str, str] | None = None,
    which: Callable[[str], str | None] = shutil.which,
    kfd_path: str = "/dev/kfd",
    access: Callable[[str, int], bool] = os.access,
    exists: Callable[[str], bool] = os.path.exists,
    rocm_lib_dir: str = ROCM_LIB_DIR,
    nvidia_pip_lib_dirs: Callable[[], list[str]] = _nvidia_pip_lib_dirs,
) -> GpuReport:
    """Detect the GPU and recommend a CTranslate2 backend. Never raises."""
    env = os.environ if env is None else env
    try:
        return _detect(sysfs_root, run, env, which, kfd_path, access, exists,
                       rocm_lib_dir, nvidia_pip_lib_dirs)
    except Exception as exc:  # noqa: BLE001 — detection must never break callers
        return GpuReport(runtime_detail=f"detection failed: {exc}")


def _detect(sysfs_root, run, env, which, kfd_path, access, exists,
            rocm_lib_dir, nvidia_pip_lib_dirs) -> GpuReport:
    cards = _pci_cards(sysfs_root)
    amd_cards = [c for c in cards if c[0] == AMD_VENDOR]
    nvidia_cards = [c for c in cards if c[0] == NVIDIA_VENDOR]

    results: dict[str, _VendorResult] = {}
    if amd_cards:
        results["rocm"] = _detect_amd(amd_cards, run, which, kfd_path, access,
                                      exists, rocm_lib_dir)
    if nvidia_cards:
        results["cuda"] = _detect_nvidia(nvidia_cards, run, which, exists,
                                         nvidia_pip_lib_dirs)
    if not results:
        return GpuReport()

    vendor = "both" if len(results) == 2 else (
        "amd" if "rocm" in results else "nvidia"
    )
    devices = [d for r in results.values() for d in r.devices]
    working = {b: r for b, r in results.items() if r.runtime_ok}

    override = (env.get(OVERRIDE_ENV) or "").strip().lower()
    if override == "cpu":
        return GpuReport(vendor, devices, False,
                         f"{OVERRIDE_ENV}=cpu forces the CPU backend", "cpu")
    if override in ("rocm", "cuda"):
        if override not in working:
            detail = (results[override].detail if override in results
                      else f"no {override} GPU found")
            failure = results.get(override, _VendorResult([], False, ""))
            return GpuReport(vendor, devices, False,
                             f"{OVERRIDE_ENV}={override}, but {detail}", "cpu",
                             hint=failure.hint, fix=failure.fix or _README_FIX)
        backend = override
    elif working:
        # Both usable: the one with more VRAM wins.
        backend = max(
            working,
            key=lambda b: (working[b].chosen.vram_total or 0)
            if working[b].chosen else 0,
        )
    else:
        # A GPU exists but nothing works: report the first failure's hint.
        first = next(iter(results.values()))
        return GpuReport(vendor, devices, False, first.detail, "cpu",
                         hint=first.hint, fix=first.fix)

    chosen_result = working[backend]
    return GpuReport(
        vendor=vendor,
        devices=devices,
        runtime_ok=True,
        runtime_detail=chosen_result.detail,
        recommended_backend=backend,
        chosen=chosen_result.chosen,
        needs_ld_library_path=chosen_result.needs_ld_library_path,
    )


# ── What is installed (no ctranslate2 import) ──

def read_marker(stamp_file: str | None = None) -> str | None:
    """The backend recorded at install time (``gpu_backend=`` in the stamp),
    or None when the stamp predates GPU support."""
    text = _read(stamp_file or STAMP_FILE)
    if text is None:
        return None
    for line in text.splitlines():
        if line.startswith("gpu_backend="):
            value = line.partition("=")[2].strip()
            return value if value in BACKENDS else None
    return None


def write_marker(
    backend: str,
    wheel: str | None = None,
    ld_library_path: bool = False,
    stamp_file: str | None = None,
) -> bool:
    """Record ``backend`` in the stamp, keeping its other lines (version,
    commit, ...). Same keys install-lib.sh's write_stamp writes. Returns
    False when there is no stamp, i.e. no install to record it for."""
    if backend not in BACKENDS:
        raise ValueError(f"unknown backend {backend!r}")
    stamp_file = stamp_file or STAMP_FILE
    text = _read(stamp_file)
    if text is None:
        return False
    keys = {"gpu_backend", "ct2_wheel", "rocm_ld_path"}
    lines = [ln for ln in text.splitlines() if ln.partition("=")[0] not in keys]
    lines.append(f"gpu_backend={backend}")
    if backend == "rocm" and wheel:
        lines.append(f"ct2_wheel={wheel}")
    if backend == "rocm" and ld_library_path:
        lines.append("rocm_ld_path=1")
    tmp = f"{stamp_file}.new"
    with open(tmp, "w") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, stamp_file)
    return True


def installed_ct2_flavor() -> tuple[str, str | None]:
    """(flavor, version) of the venv's ctranslate2 without importing it:
    ``rocm`` when its bundled ``libctranslate2`` links ``libamdhip64``,
    ``pypi`` otherwise, ``missing`` when it isn't installed."""
    from importlib import metadata

    try:
        dist = metadata.distribution("ctranslate2")
    except metadata.PackageNotFoundError:
        return "missing", None
    libs = [
        str(dist.locate_file(f)) for f in (dist.files or [])
        if re.search(r"libctranslate2[^/]*\.so", str(f))
    ]
    for lib in libs:
        if any(n.startswith("libamdhip64.so") for n in elf_needed(lib)):
            return "rocm", dist.version
    return "pypi", dist.version


def elf_needed(path: str) -> list[str]:
    """The DT_NEEDED entries of a 64-bit little-endian ELF shared library
    (what ``readelf -d`` lists), or [] when it can't be read. Reads only the
    headers and the dynamic section, not the whole (large) library."""
    import struct

    try:
        with open(path, "rb") as f:
            header = f.read(64)
            if header[:4] != b"\x7fELF" or header[4] != 2 or header[5] != 1:
                return []
            phoff, = struct.unpack_from("<Q", header, 32)
            phentsize, phnum = struct.unpack_from("<HH", header, 54)
            f.seek(phoff)
            table = f.read(phentsize * phnum)
            loads, dynamic = [], None
            for i in range(phnum):
                p_type, _flags, offset, vaddr, _paddr, filesz, _memsz, _align = (
                    struct.unpack_from("<IIQQQQQQ", table, i * phentsize)
                )
                if p_type == 1:  # PT_LOAD
                    loads.append((vaddr, offset, filesz))
                elif p_type == 2:  # PT_DYNAMIC
                    dynamic = (offset, filesz)
            if dynamic is None:
                return []
            f.seek(dynamic[0])
            dyn = f.read(dynamic[1])
            needed, strtab, strsz = [], None, 0
            for i in range(0, len(dyn) - 15, 16):
                tag, value = struct.unpack_from("<qQ", dyn, i)
                if tag == 0:  # DT_NULL
                    break
                if tag == 1:  # DT_NEEDED
                    needed.append(value)
                elif tag == 5:  # DT_STRTAB (a virtual address)
                    strtab = value
                elif tag == 10:  # DT_STRSZ
                    strsz = value
            if strtab is None:
                return []
            start = next(
                (off + strtab - va for va, off, size in loads
                 if va <= strtab < va + size),
                None,
            )
            if start is None:
                return []
            f.seek(start)
            strings = f.read(strsz)
    except (OSError, struct.error):
        return []
    return [
        strings[n:strings.index(b"\0", n)].decode(errors="replace")
        for n in needed if n < len(strings) and b"\0" in strings[n:]
    ]


def runtime_report(config: dict, **probes) -> GpuReport | None:
    """Detection for the running app: only when Whisper is the engine and
    ``stt.whisper.device`` may use a GPU (``auto`` or ``cuda``). None
    otherwise, so CPU-only engines pay nothing at startup. Sysfs plus one
    ``rocminfo`` run (tens of milliseconds; each probe is capped at 5 s)."""
    stt = config.get("stt") or {}
    if stt.get("engine", "whisper") != "whisper":
        return None
    if (stt.get("whisper") or {}).get("device", "auto") not in ("auto", "cuda"):
        return None
    return detect(**probes)
