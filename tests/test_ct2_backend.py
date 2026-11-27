"""The pinned ROCm CTranslate2 backend (MCC-195): download, verify, install
and roll back, with a local fake zip and a fake pip. No network."""

from __future__ import annotations

import hashlib
import io
import subprocess
import zipfile

import pytest

from verbal_code import ct2_backend as cb
from verbal_code import doctor, gpu

VERSION = "9.9.9"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def fake_release(tmp_path):
    """A zip shaped like the release asset, with two wheels, plus its pins."""
    wheels = {tag: f"wheel for {tag}".encode() for tag in ("cp312", "cp314t")}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for tag, data in wheels.items():
            z.writestr(f"temp-linux/{cb.wheel_filename(tag, VERSION)}", data)
    data = buf.getvalue()
    return {
        "zip": data,
        "zip_sha": _sha(data),
        "wheel_sha": {tag: _sha(w) for tag, w in wheels.items()},
        "cache": tmp_path / "wheels",
    }


def _opener(payload: bytes, calls: list | None = None):
    def opener(url, timeout):
        if calls is not None:
            calls.append(url)
        return io.BytesIO(payload)
    return opener


def test_wheel_filenames_match_the_release_asset():
    assert cb.wheel_filename("cp312", "4.9.1") == (
        "ctranslate2-4.9.1-cp312-cp312-manylinux_2_27_x86_64.manylinux_2_28_x86_64.whl"
    )
    # Free-threaded builds keep the plain tag as the Python tag.
    assert cb.wheel_filename("cp314t", "4.9.1").startswith(
        "ctranslate2-4.9.1-cp314-cp314t-"
    )


def test_pin_covers_every_supported_python():
    for minor in range(10, 16):
        assert f"cp3{minor}" in cb.ROCM_WHEEL_SHA256
    assert all(len(h) == 64 for h in cb.ROCM_WHEEL_SHA256.values())
    assert cb.ROCM_VERSION in cb.ROCM_ZIP_URL


def test_pin_satisfies_faster_whispers_requirement():
    """A pin outside faster-whisper's ctranslate2 range would be swapped
    back by every `pip install -e .` (R4.20)."""
    assert cb.pin_satisfies_faster_whisper() is not False


class TestFetchAndExtract:
    @pytest.mark.parametrize("tag", ["cp312", "cp314t"])
    def test_extracts_and_verifies_the_matching_wheel(self, fake_release, tag):
        r = fake_release
        zip_path = cb.fetch_zip(str(r["cache"]), url="https://x/rocm.zip",
                                sha256=r["zip_sha"], opener=_opener(r["zip"]))
        wheel = cb.extract_wheel(zip_path, tag, str(r["cache"]),
                                 r["wheel_sha"], VERSION)
        assert wheel.endswith(cb.wheel_filename(tag, VERSION))
        assert cb.sha256_file(wheel) == r["wheel_sha"][tag]

    def test_zip_hash_mismatch_aborts_and_keeps_nothing(self, fake_release):
        r = fake_release
        with pytest.raises(cb.BackendError, match="SHA-256 mismatch"):
            cb.fetch_zip(str(r["cache"]), url="https://x/rocm.zip",
                         sha256="0" * 64, opener=_opener(r["zip"]))
        assert list(r["cache"].iterdir()) == []

    def test_wheel_hash_mismatch_aborts_and_keeps_nothing(self, fake_release):
        r = fake_release
        zip_path = cb.fetch_zip(str(r["cache"]), url="https://x/rocm.zip",
                                sha256=r["zip_sha"], opener=_opener(r["zip"]))
        bad = {**r["wheel_sha"], "cp312": "0" * 64}
        with pytest.raises(cb.BackendError, match="SHA-256 mismatch"):
            cb.extract_wheel(zip_path, "cp312", str(r["cache"] / "out"), bad,
                             VERSION)
        assert list((r["cache"] / "out").iterdir()) == []

    def test_missing_tag_is_an_error(self, fake_release):
        r = fake_release
        zip_path = cb.fetch_zip(str(r["cache"]), url="https://x/rocm.zip",
                                sha256=r["zip_sha"], opener=_opener(r["zip"]))
        with pytest.raises(cb.BackendError, match="no ROCm wheel is pinned"):
            cb.extract_wheel(zip_path, "cp399", str(r["cache"]), r["wheel_sha"],
                             VERSION)

    def test_network_failure_says_how_to_retry(self, tmp_path):
        def opener(url, timeout):
            raise OSError("Name or service not known")
        with pytest.raises(cb.BackendError, match="--doctor --fix"):
            cb.fetch_zip(str(tmp_path), url="https://x/rocm.zip", opener=opener)
        assert list(tmp_path.iterdir()) == []

    def test_verified_zip_is_reused(self, fake_release):
        r = fake_release
        calls: list[str] = []
        for _ in range(2):
            cb.fetch_zip(str(r["cache"]), url="https://x/rocm.zip",
                         sha256=r["zip_sha"], opener=_opener(r["zip"], calls))
        assert len(calls) == 1


class TestObtainWheel:
    def _fetch(self, release, calls):
        def fetch(dest):
            calls.append(dest)
            return cb.fetch_zip(dest, url="https://x/rocm.zip",
                                sha256=release["zip_sha"],
                                opener=_opener(release["zip"]))
        return fetch

    def test_keeps_only_the_wheel_and_reuses_it(self, fake_release):
        r = fake_release
        calls: list[str] = []
        stale = r["cache"] / "ctranslate2-1.0.0-cp312-cp312-old.whl"
        r["cache"].mkdir()
        stale.write_bytes(b"old pin")
        for _ in range(2):
            wheel = cb.obtain_wheel("cp312", str(r["cache"]),
                                    self._fetch(r, calls), r["wheel_sha"], VERSION)
        assert len(calls) == 1  # second call served from the cache
        assert sorted(p.name for p in r["cache"].iterdir()) == [
            cb.wheel_filename("cp312", VERSION)
        ]  # no 277 MB zip, no stale pin left behind
        assert wheel.endswith(cb.wheel_filename("cp312", VERSION))

    def test_corrupt_cached_wheel_is_replaced(self, fake_release):
        r = fake_release
        calls: list[str] = []
        r["cache"].mkdir()
        (r["cache"] / cb.wheel_filename("cp312", VERSION)).write_bytes(b"corrupt")
        wheel = cb.obtain_wheel("cp312", str(r["cache"]), self._fetch(r, calls),
                                r["wheel_sha"], VERSION)
        assert len(calls) == 1
        assert cb.sha256_file(wheel) == r["wheel_sha"]["cp312"]

    def test_missing_tag_downloads_nothing(self, fake_release):
        calls: list[str] = []
        with pytest.raises(cb.BackendError):
            cb.obtain_wheel("cp399", str(fake_release["cache"]),
                            self._fetch(fake_release, calls),
                            fake_release["wheel_sha"], VERSION)
        assert calls == []


class FakePip:
    """Records pip invocations; `install` of a ROCm wheel can be made to fail."""

    def __init__(self, fail_install=False, check_after=""):
        self.calls: list[list[str]] = []
        self.fail_install = fail_install
        self.check_after = check_after
        self.installed = False

    def __call__(self, cmd, **kwargs):
        args = cmd[3:]
        self.calls.append(args)
        if args[0] == "install":
            if self.fail_install and args[-1].endswith(".whl"):
                return subprocess.CompletedProcess(cmd, 1, "", "boom")
            self.installed = True
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if args[0] == "check":
            out = "yt-dlp has requirement websockets>=12\n"
            if self.installed:
                out += self.check_after
            return subprocess.CompletedProcess(cmd, 1, out, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def installs(self):
        return [c for c in self.calls if c[0] == "install"]


def _install(pip, verify_ok=True, previous=("pypi", "4.8.4"), fallback=True,
             tag="cp312"):
    return cb.install_rocm(
        run=pip, python="/venv/bin/python", tag=tag, fallback=fallback,
        obtain=lambda t, cache: f"/cache/{cb.wheel_filename(t)}",
        verify=lambda **kw: (verify_ok, "" if verify_ok else
                             "ctranslate2 sees no GPU device"),
        machine="x86_64", previous=previous,
    )


class TestInstallRocm:
    def test_installs_the_wheel_without_deps(self):
        pip = FakePip()
        assert _install(pip) == cb.wheel_filename("cp312")
        assert pip.installs() == [[
            "install", "--quiet", "--force-reinstall", "--no-deps",
            f"/cache/{cb.wheel_filename('cp312')}",
        ]]

    def test_preexisting_pip_check_problems_are_tolerated(self):
        assert _install(FakePip()) == cb.wheel_filename("cp312")

    def test_failed_verification_rolls_back_to_pypi(self):
        pip = FakePip()
        with pytest.raises(cb.BackendError, match="sees no GPU.*CPU"):
            _install(pip, verify_ok=False)
        assert pip.installs()[-1] == [
            "install", "--quiet", "--force-reinstall", "--no-deps",
            "ctranslate2==4.8.4",
        ]

    def test_rollback_from_a_rocm_build_uses_the_pinned_version(self):
        pip = FakePip()
        with pytest.raises(cb.BackendError):
            _install(pip, verify_ok=False, previous=("rocm", "4.9.1"))
        assert pip.installs()[-1][-1] == f"ctranslate2=={cb.ROCM_VERSION}"

    def test_new_pip_check_problem_is_a_failure(self):
        pip = FakePip(check_after="faster-whisper 1.2.1 requires ctranslate2<5\n")
        with pytest.raises(cb.BackendError, match="pip check"):
            _install(pip)
        assert pip.installs()[-1][-1] == "ctranslate2==4.8.4"

    def test_pip_failure_without_fallback_leaves_rollback_to_caller(self):
        pip = FakePip(fail_install=True)
        with pytest.raises(cb.BackendError, match="pip could not install"):
            _install(pip, fallback=False)
        assert len(pip.installs()) == 1  # no PyPI reinstall

    def test_non_x86_64_is_refused_before_anything_changes(self):
        pip = FakePip()
        with pytest.raises(cb.BackendError, match="x86_64 only"):
            cb.install_rocm(run=pip, tag="cp312", machine="aarch64",
                            obtain=lambda *a: pytest.fail("downloaded"))
        assert pip.calls == []

    def test_download_failure_changes_nothing(self):
        pip = FakePip()

        def obtain(tag, cache):
            raise cb.BackendError("download failed")
        with pytest.raises(cb.BackendError):
            cb.install_rocm(run=pip, tag="cp312", machine="x86_64", obtain=obtain)
        assert pip.calls == []


class TestCli:
    def test_install_rocm_failure_exits_cpu(self, monkeypatch, capsys):
        def fail(**kwargs):
            raise cb.BackendError("no network")
        monkeypatch.setattr(cb, "install_rocm", fail)
        assert cb.main(["install-rocm"]) == cb.EXIT_CPU
        assert "no network" in capsys.readouterr().err

    def test_strict_install_rocm_failure_exits_1(self, monkeypatch):
        def fail(**kwargs):
            assert kwargs["fallback"] is False
            raise cb.BackendError("verify failed")
        monkeypatch.setattr(cb, "install_rocm", fail)
        assert cb.main(["install-rocm", "--no-fallback"]) == cb.EXIT_FAILED

    def test_is_pinned_rocm(self, monkeypatch):
        monkeypatch.setattr(gpu, "installed_ct2_flavor",
                            lambda: ("rocm", cb.ROCM_VERSION))
        assert cb.main(["is-pinned-rocm"]) == 0
        monkeypatch.setattr(gpu, "installed_ct2_flavor", lambda: ("pypi", "4.9.1"))
        assert cb.main(["is-pinned-rocm"]) == 1


class TestDoctorFix:
    @pytest.fixture
    def rocm_report(self):
        device = gpu.GpuDevice(vendor="amd", name="RX 9060 XT", pci_id="1002:7590",
                               target="gfx1200", index=0, supported=True,
                               official=True)
        return gpu.GpuReport("amd", [device], True, "ROCm 7 runtime found",
                             "rocm", chosen=device)

    @pytest.fixture
    def stamp(self, tmp_path, monkeypatch):
        path = tmp_path / "installed-version"
        path.write_text("version=0.1.0\ncommit=abc\ngpu_backend=rocm\n")
        monkeypatch.setattr(gpu, "STAMP_FILE", str(path))
        monkeypatch.setattr(doctor, "run_doctor", lambda *a, **k: 0)
        return path

    def test_reinstalls_after_a_pip_upgrade(self, rocm_report, stamp, monkeypatch):
        monkeypatch.setattr(gpu, "installed_ct2_flavor", lambda: ("pypi", "4.9.1"))
        calls = []
        monkeypatch.setattr(cb, "install_rocm",
                            lambda **kw: calls.append(kw) or "rocm.whl")
        out = io.StringIO()
        doctor.run_fix({}, out=out, ask=lambda q: "y", report=rocm_report)
        assert len(calls) == 1
        text = stamp.read_text()
        assert "gpu_backend=rocm" in text and "ct2_wheel=rocm.whl" in text
        assert "commit=abc" in text  # other stamp lines kept

    def test_declining_changes_nothing(self, rocm_report, stamp, monkeypatch):
        monkeypatch.setattr(gpu, "installed_ct2_flavor", lambda: ("pypi", "4.9.1"))
        monkeypatch.setattr(cb, "install_rocm", lambda **kw: pytest.fail("ran"))
        before = stamp.read_text()
        doctor.run_fix({}, out=io.StringIO(), ask=lambda q: "", report=rocm_report)
        assert stamp.read_text() == before

    def test_eof_at_the_prompt_means_no(self, rocm_report, stamp, monkeypatch):
        monkeypatch.setattr(gpu, "installed_ct2_flavor", lambda: ("pypi", "4.9.1"))
        monkeypatch.setattr(cb, "install_rocm", lambda **kw: pytest.fail("ran"))

        def eof(question):
            raise EOFError
        doctor.run_fix({}, out=io.StringIO(), ask=eof, report=rocm_report)

    def test_failed_install_records_cpu(self, rocm_report, stamp, monkeypatch):
        monkeypatch.setattr(gpu, "installed_ct2_flavor", lambda: ("pypi", "4.9.1"))

        def fail(**kwargs):
            raise cb.BackendError("sees no GPU")
        monkeypatch.setattr(cb, "install_rocm", fail)
        out = io.StringIO()
        doctor.run_fix({}, out=out, ask=lambda q: "y", report=rocm_report)
        assert "gpu_backend=cpu" in stamp.read_text()
        assert "sees no GPU" in out.getvalue()
