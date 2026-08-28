"""Config persistence must not destroy the user's file (MCC-40).

Covers comment preservation through both save paths (tray model switch and
hotkey editor), atomic replacement, and failure hygiene.
"""

import os

import pytest
import yaml

from verbal_code.config_store import update_config
from verbal_code.hotkey_editor import save_hotkey_config
from verbal_code.transcriber import apply_selection

_COMMENTED_CONFIG = """\
# Top-of-file documentation the user relies on.
hotkey:
  modifiers: ["super", "alt"]
  key: "space"  # trailing comment on the key
stt:
  engine: "whisper"  # which backend to use
audio:
  sample_rate: 16000
"""


class TestUpdateConfig:
    def test_comments_survive_a_rewrite(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(_COMMENTED_CONFIG)

        update_config(str(path), lambda cfg: apply_selection(cfg, "vosk", "m"))

        text = path.read_text()
        assert "# Top-of-file documentation the user relies on." in text
        assert "# trailing comment on the key" in text
        assert "# which backend to use" in text
        cfg = yaml.safe_load(text)
        assert cfg["stt"]["engine"] == "vosk"
        assert cfg["hotkey"]["key"] == "space"

    def test_missing_file_is_created(self, tmp_path):
        path = tmp_path / "sub" / "config.yaml"

        update_config(str(path), lambda cfg: cfg.update({"a": 1}))

        assert yaml.safe_load(path.read_text()) == {"a": 1}

    def test_write_leaves_no_temp_files(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(_COMMENTED_CONFIG)

        update_config(str(path), lambda cfg: None)

        assert os.listdir(tmp_path) == ["config.yaml"]

    def test_failed_mutation_leaves_file_untouched(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(_COMMENTED_CONFIG)

        def _boom(cfg):
            raise RuntimeError("mutator exploded")

        with pytest.raises(RuntimeError):
            update_config(str(path), _boom)

        assert path.read_text() == _COMMENTED_CONFIG
        assert os.listdir(tmp_path) == ["config.yaml"]

    def test_file_permissions_are_preserved(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(_COMMENTED_CONFIG)
        os.chmod(path, 0o600)

        update_config(str(path), lambda cfg: None)

        assert (path.stat().st_mode & 0o777) == 0o600


class TestHotkeySavePreservesComments:
    def test_save_hotkey_config_keeps_comments(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text(_COMMENTED_CONFIG)

        save_hotkey_config(str(path), ["ctrl", "shift"], "d")

        text = path.read_text()
        assert "# which backend to use" in text
        cfg = yaml.safe_load(text)
        assert cfg["hotkey"]["modifiers"] == ["ctrl", "shift"]
        assert cfg["hotkey"]["key"] == "d"
        assert cfg["audio"]["sample_rate"] == 16000
