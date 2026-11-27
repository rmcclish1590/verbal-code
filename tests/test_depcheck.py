"""Which dependency conflicts are Verbal Code's (MCC-202). Fake metadata and
fake ``pip check`` output; no network, no real environment."""

from __future__ import annotations

import subprocess
from importlib import metadata
from pathlib import Path

import pytest

from verbal_code import depcheck

REPO = Path(__file__).resolve().parent.parent

# Linux Mint 22's distro packages, seen through --system-site-packages.
MINT = ("yt-dlp 2024.4.9 has requirement websockets>=12.0, but you have "
        "websockets 10.4.")
OWN = ("faster-whisper 1.2.1 has requirement ctranslate2<5,>=4.0, but you "
       "have ctranslate2 5.0.0.")


def _requires(table: dict[str, list[str]]):
    def requires(name: str):
        key = depcheck.normalize(name)
        if key not in table:
            raise metadata.PackageNotFoundError(name)
        return table[key]
    return requires


METADATA = {
    "verbal-code": [
        "faster-whisper<2,>=1.0.0",
        "onnx-asr[cpu,hub]<0.13,>=0.12",
        "Ruamel.YAML<0.19,>=0.18",
        'vosk<0.4,>=0.3.45; extra == "vosk"',
        'useful-moonshine-onnx>=20251121; extra == "moonshine"',  # not installed
        'tomli>=2; python_version < "3.0"',  # never applies
    ],
    "faster-whisper": ["ctranslate2<5,>=4.0", "tokenizers<1,>=0.13"],
    "ctranslate2": ["numpy", "pyyaml<7,>=5.3"],
    "tokenizers": ['huggingface-hub<2.0,>=0.16.4', 'pytest; extra == "testing"'],
    "huggingface-hub": ["filelock", 'InquirerPy==0.3.4; extra == "cli"'],
    "onnx-asr": [
        "numpy",
        'onnxruntime>=1.18; extra == "cpu"',
        'huggingface-hub; extra == "hub"',
        'onnx; extra == "dev"',
    ],
    "onnxruntime": ["protobuf"],
    "ruamel-yaml": [
        'ruamel.yaml.clib>=0.2.7; platform_python_implementation=="CPython"'],
    "ruamel-yaml-clib": [],
    "vosk": ["cffi>=1.0"],
    "cffi": ["pycparser"],
    "numpy": [], "pyyaml": [], "filelock": [], "protobuf": [], "pycparser": [],
    "pytest": ["pluggy"], "pluggy": [], "inquirerpy": [], "onnx": [],
    "tomli": [],
    # Outside the tree.
    "yt-dlp": ["websockets>=12.0", "brotli"],
    "websockets": [], "brotli": [],
}


class TestDependencyTree:
    @pytest.fixture
    def tree(self):
        return depcheck.dependency_tree(requires=_requires(METADATA))

    def test_follows_requirements_transitively(self, tree):
        assert {"verbal-code", "faster-whisper", "ctranslate2", "numpy", "pyyaml",
                "tokenizers", "huggingface-hub", "filelock"} <= tree

    def test_requested_extras_are_followed(self, tree):
        # onnx-asr[cpu,hub]: onnxruntime and protobuf behind it.
        assert {"onnx-asr", "onnxruntime", "protobuf"} <= tree

    def test_extras_nobody_asked_for_are_not(self, tree):
        assert "onnx" not in tree  # onnx-asr[dev]
        assert "inquirerpy" not in tree  # huggingface-hub[cli]
        assert "pytest" not in tree and "pluggy" not in tree  # tokenizers[testing]

    def test_installed_optional_engines_count(self, tree):
        assert {"vosk", "cffi", "pycparser"} <= tree

    def test_uninstalled_and_inapplicable_requirements_are_skipped(self, tree):
        assert "useful-moonshine-onnx" not in tree
        assert "tomli" not in tree

    def test_names_are_normalized(self, tree):
        assert {"ruamel-yaml", "ruamel-yaml-clib"} <= tree

    def test_distro_packages_are_outside(self, tree):
        assert not {"yt-dlp", "websockets", "brotli"} & tree

    def test_not_installed_root_gives_an_empty_tree(self):
        assert depcheck.dependency_tree(requires=_requires({})) == set()

    def test_a_cycle_terminates(self):
        tree = depcheck.dependency_tree(requires=_requires(
            {"verbal-code": ["a"], "a": ["b"], "b": ["a"]}))
        assert tree == {"verbal-code", "a", "b"}

    def test_real_environment_includes_core_dependencies(self):
        """This interpreter has verbal-code installed (editable)."""
        tree = depcheck.dependency_tree()
        assert {"verbal-code", "faster-whisper", "numpy"} <= tree


class TestParse:
    @pytest.mark.parametrize("line, owner, needs", [
        (MINT, "yt-dlp", "websockets>=12.0"),
        ("yt-dlp 2024.4.9 requires websockets>=12.0, but you have websockets "
         "10.4 which is incompatible.", "yt-dlp", "websockets>=12.0"),
        ("Faster_Whisper 1.2.1 requires av, which is not installed.",
         "faster-whisper", "av"),
        ("onnxruntime 1.23.0 is not supported on this platform", "onnxruntime", ""),
    ])
    def test_pip_formats(self, line, owner, needs):
        (conflict,) = depcheck.parse_conflicts(line + "\n")
        assert (conflict.owner, conflict.needs) == (owner, needs)

    def test_other_lines_are_ignored(self):
        text = "No broken requirements found.\nWARNING: something\n"
        assert depcheck.parse_conflicts(text) == []


TREE = {"verbal-code", "faster-whisper", "ctranslate2"}


def _pip_check(stdout: str, code: int | None = None):
    def run(cmd, **kwargs):
        assert cmd[1:] == ["-m", "pip", "check"]
        assert kwargs["cwd"] == "/"
        rc = (1 if stdout else 0) if code is None else code
        return subprocess.CompletedProcess(cmd, rc, stdout, "")
    return run


class TestCheck:
    def test_clean(self):
        report = depcheck.check(run=_pip_check(""), tree=TREE)
        assert report.ok and not report.unrelated and report.note() == ""

    def test_unrelated_conflict_passes_with_a_note(self):
        report = depcheck.check(run=_pip_check(MINT + "\n"), tree=TREE)
        assert report.ok
        assert report.note() == (
            "Other Python packages on this system have conflicting requirements "
            "(yt-dlp wants websockets>=12.0). Verbal Code doesn't use them and "
            "isn't affected.")

    def test_own_conflict_fails(self):
        report = depcheck.check(run=_pip_check(f"{MINT}\n{OWN}\n"), tree=TREE)
        assert not report.ok
        assert report.failure() == (
            "Verbal Code's dependencies conflict: faster-whisper 1.2.1 has "
            "requirement ctranslate2<5,>=4.0, but you have ctranslate2 5.0.0")
        assert [c.owner for c in report.unrelated] == ["yt-dlp"]

    def test_note_lists_at_most_three(self):
        lines = "\n".join(f"pkg{i} 1.0 requires dep{i}, which is not installed."
                          for i in range(5))
        note = depcheck.check(run=_pip_check(lines), tree=TREE).note()
        assert "pkg0 wants dep0; pkg1 wants dep1; pkg2 wants dep2; 2 more" in note

    def test_pip_failing_without_conflicts_is_an_error(self):
        def run(cmd, **kwargs):
            return subprocess.CompletedProcess(cmd, 2, "", "No module named pip\n")
        report = depcheck.check(run=run, tree=TREE)
        assert not report.ok and "No module named pip" in report.failure()

    def test_pip_not_starting_is_an_error(self):
        def run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 120)
        assert "did not run" in depcheck.check(run=run, tree=TREE).error


class TestMain:
    @pytest.fixture(autouse=True)
    def tree(self, monkeypatch):
        monkeypatch.setattr(depcheck, "dependency_tree", lambda: set(TREE))

    def _main(self, monkeypatch, stdout, *args):
        monkeypatch.setattr(depcheck.subprocess, "run", _pip_check(stdout))
        return depcheck.main(list(args))

    def test_unrelated_exits_0_with_note(self, monkeypatch, capsys):
        assert self._main(monkeypatch, MINT) == 0
        assert "yt-dlp wants websockets>=12.0" in capsys.readouterr().out

    def test_no_note(self, monkeypatch, capsys):
        assert self._main(monkeypatch, MINT, "--no-note") == 0
        assert capsys.readouterr().out == ""

    def test_own_exits_1(self, monkeypatch, capsys):
        assert self._main(monkeypatch, OWN) == 1
        assert "faster-whisper 1.2.1" in capsys.readouterr().err

    def test_not_installed_exits_2(self, monkeypatch, capsys):
        monkeypatch.setattr(depcheck, "dependency_tree", lambda: set())
        assert self._main(monkeypatch, "") == 2
        assert "verbal-code is not installed" in capsys.readouterr().err


def test_resolver_block_is_stripped_and_the_rest_kept():
    """install-lib.sh's filter for pip's stderr."""
    stderr = (
        "  BuildBackendWarning: Editable installation.\n"
        "ERROR: pip's dependency resolver does not currently take into account "
        "all the packages that are installed. This behaviour is the source of "
        "the following dependency conflicts.\n"
        "yt-dlp 2024.4.9 requires websockets>=12.0, but you have websockets 10.4 "
        "which is incompatible.\n"
        "foo 1.0 requires bar, which is not installed.\n"
        "WARNING: something else pip said\n"
    )
    out = subprocess.run(
        ["bash", "-c", f'source "{REPO}/scripts/install-lib.sh"; '
         "strip_resolver_conflicts"],
        input=stderr, capture_output=True, text=True, check=True,
    ).stdout
    assert out == ("  BuildBackendWarning: Editable installation.\n"
                   "WARNING: something else pip said\n")
