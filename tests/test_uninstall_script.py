"""uninstall.sh's dictionary choice and install's dictionary detection
(MCC-200), against a scratch HOME.

Non-interactive runs pipe stdin. Interactive runs give uninstall.sh a
pseudo-terminal as stdin, so ``[ -t 0 ]`` holds and ``read`` prompts; the
answers are typed into it up front, one line per prompt.
"""

from __future__ import annotations

import json
import os
import pty
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

ENTRIES = {"entries": [{"term": "liatrio"}, {"term": "Kaeden"}]}


class Box:
    def __init__(self, tmp: Path) -> None:
        self.home = tmp / "home"
        self.repo = tmp / "repo"
        for rel in ("uninstall.sh", "scripts/install-lib.sh"):
            dest = self.repo / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO / rel, dest)
        self.fakebin = tmp / "fakebin"
        self.fakebin.mkdir()
        for tool in ("gtk-update-icon-cache", "update-desktop-database"):
            exe = self.fakebin / tool
            exe.write_text("#!/usr/bin/env bash\nexit 0\n")
            exe.chmod(0o755)
        self.config_dir = self.home / ".config/verbal-code"
        self.data_dir = self.home / ".local/share/verbal-code"
        self.dictionary = self.config_dir / "dictionary.json"

    def install(self, dictionary: object = ENTRIES, config: str = "") -> None:
        (self.data_dir / "venv/bin").mkdir(parents=True)
        self.config_dir.mkdir(parents=True)
        default = "stt:\n  engine: parakeet\n"
        (self.config_dir / "config.yaml").write_text(config or default)
        (self.config_dir / "vc.log").write_text("INFO started\n")
        if dictionary is not None:
            text = dictionary if isinstance(dictionary, str) else json.dumps(dictionary)
            self.dictionary.write_text(text)

    def env(self) -> dict[str, str]:
        return {**os.environ, "HOME": str(self.home),
                "PATH": f"{self.fakebin}:{os.environ['PATH']}"}

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.repo / "uninstall.sh"), *args],
            env=self.env(), stdin=subprocess.DEVNULL, capture_output=True,
            text=True, timeout=60,
        )

    def run_tty(self, *answers: str, args: tuple[str, ...] = ()) -> tuple[int, str]:
        """Run with a terminal as stdin, typing ``answers`` (one per prompt)."""
        master, slave = pty.openpty()
        try:
            proc = subprocess.Popen(
                ["bash", str(self.repo / "uninstall.sh"), *args],
                env=self.env(), stdin=slave, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True,
            )
            os.close(slave)
            os.write(master, "".join(a + "\n" for a in answers).encode())
            out, _ = proc.communicate(timeout=60)
        finally:
            os.close(master)
        return proc.returncode, out


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def _out(result: subprocess.CompletedProcess[str]) -> str:
    return result.stdout + result.stderr


class TestNonInteractive:
    def test_no_arguments_changes_nothing_and_keeps_the_dictionary(self, box):
        box.install()
        result = box.run()
        assert result.returncode != 0
        assert "--force" in _out(result)
        assert json.loads(box.dictionary.read_text()) == ENTRIES
        assert (box.config_dir / "config.yaml").exists()
        assert box.data_dir.exists()

    @pytest.mark.parametrize("args", [("--force",), ("--force", "--keep-dictionary")])
    def test_force_keeps_the_dictionary(self, box, args):
        box.install()
        result = box.run(*args)
        assert result.returncode == 0, _out(result)
        assert json.loads(box.dictionary.read_text()) == ENTRIES
        assert sorted(p.name for p in box.config_dir.iterdir()) == ["dictionary.json"]
        assert not box.data_dir.exists()
        assert ("Kept your dictionary: ~/.config/verbal-code/dictionary.json "
                "(2 entries, last changed") in _out(result)

    @pytest.mark.parametrize("flag", ["--purge-dictionary", "--purge"])
    def test_purge_dictionary_deletes_it(self, box, flag):
        box.install()
        result = box.run("--force", flag)
        assert result.returncode == 0, _out(result)
        assert not box.dictionary.exists()
        assert not box.config_dir.exists()
        out = _out(result)
        assert "Deleted your dictionary: ~/.config/verbal-code/dictionary.json" in out
        assert "can't be undone" in out

    def test_conflicting_flags_are_refused(self, box):
        box.install()
        result = box.run("--force", "--keep-dictionary", "--purge-dictionary")
        assert result.returncode == 2
        assert box.dictionary.exists() and box.data_dir.exists()

    def test_unknown_option_is_refused(self, box):
        box.install()
        result = box.run("--force", "--purge-dictonary")  # typo
        assert result.returncode == 2
        assert box.dictionary.exists() and box.data_dir.exists()

    def test_custom_dictionary_path_outside_the_config_dir(self, box):
        custom = box.home / "notes/terms.json"
        box.install(dictionary=None,
                    config=f"dictionary:\n  path: {custom}\n")
        custom.parent.mkdir()
        custom.write_text(json.dumps(ENTRIES))
        result = box.run("--force")
        assert result.returncode == 0, _out(result)
        assert custom.exists() and not box.config_dir.exists()
        assert "Kept your dictionary: ~/notes/terms.json (2 entries" in _out(result)

        box.install(dictionary=None, config=f"dictionary:\n  path: {custom}\n")
        result = box.run("--force", "--purge-dictionary")
        assert result.returncode == 0, _out(result)
        assert not custom.exists()
        assert "Deleted your dictionary: ~/notes/terms.json" in _out(result)

    def test_no_dictionary_is_reported(self, box):
        box.install(dictionary=None)
        result = box.run("--force")
        assert result.returncode == 0, _out(result)
        expected = "No dictionary found at ~/.config/verbal-code/dictionary.json"
        assert expected in _out(result)

    def test_unreadable_dictionary_is_kept(self, box):
        box.install(dictionary="{not json")
        result = box.run("--force")
        assert result.returncode == 0, _out(result)
        assert box.dictionary.read_text() == "{not json"
        assert "unreadable: not valid JSON" in _out(result)


class TestInteractive:
    def test_enter_keeps_the_dictionary(self, box):
        box.install()
        code, out = box.run_tty("", "y")  # keep (default), then continue
        assert code == 0, out
        assert json.loads(box.dictionary.read_text()) == ENTRIES
        assert ("Your dictionary: ~/.config/verbal-code/dictionary.json "
                "(2 entries") in out
        assert "Kept your dictionary" in out
        assert not box.data_dir.exists()

    def test_explicit_delete_after_confirmation(self, box):
        box.install()
        code, out = box.run_tty("d", "delete", "y")
        assert code == 0, out
        assert not box.dictionary.exists()
        assert f"permanently deletes your dictionary: {box.dictionary}" in out
        assert "cannot be undone" in out
        assert "Deleted your dictionary" in out

    @pytest.mark.parametrize("confirmation", ["", "y", "yes", "DELETE"])
    def test_anything_but_typed_delete_keeps_it(self, box, confirmation):
        box.install()
        code, out = box.run_tty("d", confirmation, "y")
        assert code == 0, out
        assert json.loads(box.dictionary.read_text()) == ENTRIES
        assert "Keeping your dictionary." in out
        assert "Kept your dictionary" in out

    def test_purge_flag_still_confirms_interactively(self, box):
        box.install()
        code, out = box.run_tty("", "y", args=("--purge-dictionary",))
        assert code == 0, out
        assert box.dictionary.exists()  # Enter at the confirmation = keep
        assert "cannot be undone" in out

    def test_keep_flag_skips_the_dictionary_prompt(self, box):
        box.install()
        code, out = box.run_tty("y", args=("--keep-dictionary",))
        assert code == 0, out
        assert box.dictionary.exists()
        assert "[K]eep / [d]elete" not in out

    def test_declining_the_uninstall_changes_nothing(self, box):
        box.install()
        code, out = box.run_tty("d", "delete", "n")
        assert code == 0, out
        assert "Nothing was removed" in out
        assert json.loads(box.dictionary.read_text()) == ENTRIES
        assert box.data_dir.exists()


# ── install-lib.sh's detection, as install.sh uses it ──

def _inspect(box: Box) -> dict[str, str]:
    script = (
        f'set -euo pipefail; source "{box.repo}/scripts/install-lib.sh"; '
        'p=$(dictionary_path); inspect_dictionary "$p"; '
        'echo "state=$DICT_STATE"; echo "entries=$DICT_ENTRIES"; '
        'echo "modified=$DICT_MODIFIED"; echo "problem=$DICT_PROBLEM"; '
        'echo "path=$p"; '
        '[ "$DICT_STATE" = ok ] && echo "summary=$(describe_dictionary "$p")"; true'
    )
    out = subprocess.run(["bash", "-c", script], env=box.env(), check=True,
                         capture_output=True, text=True).stdout
    return dict(line.split("=", 1) for line in out.splitlines())


class TestDetection:
    def test_reports_path_count_and_date(self, box):
        box.install()
        os.utime(box.dictionary, (1_700_000_000, 1_700_000_000))
        info = _inspect(box)
        assert info["state"] == "ok" and info["entries"] == "2"
        assert info["modified"].startswith("2023-11-1")
        assert info["summary"].startswith(
            "~/.config/verbal-code/dictionary.json (2 entries, last changed 2023-11-1")

    @pytest.mark.parametrize("text", ["{bad", "", '{"entries": [{"x": 1}]}', "[1]"])
    def test_unparseable_is_invalid_and_untouched(self, box, text):
        box.install(dictionary=text)
        info = _inspect(box)
        assert info["state"] == "invalid" and info["problem"]
        assert box.dictionary.read_text() == text

    def test_missing(self, box):
        box.install(dictionary=None)
        assert _inspect(box)["state"] == "missing"

    def test_custom_path_from_config(self, box):
        custom = box.home / "terms.json"
        box.install(dictionary=None, config=f"dictionary:\n  path: {custom}\n")
        custom.write_text(json.dumps({"entries": [{"term": "a"}]}))
        info = _inspect(box)
        assert info["path"] == str(custom) and info["entries"] == "1"
        assert "(1 entry," in info["summary"]
