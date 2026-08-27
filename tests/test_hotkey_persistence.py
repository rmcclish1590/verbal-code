"""Hotkey persistence tests (MCC-32).

Proves the full cycle: the editor's save lands in the config file, a restart
(load_config) resolves the saved combo, and malformed saved values fall back
to the defaults instead of breaking startup.
"""

import os

import pytest

from verbal_code.app import (
    DEFAULT_HOTKEY_KEY,
    DEFAULT_HOTKEY_MODIFIERS,
    load_config,
    resolve_config_path,
    resolve_hotkey_config,
)
from verbal_code.hotkey_editor import save_hotkey_config


@pytest.fixture
def xdg_config(tmp_path, monkeypatch):
    """Isolated HOME with an XDG config file, as a normal install has."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".config" / "verbal-code"
    cfg_dir.mkdir(parents=True)
    cfg_path = cfg_dir / "config.yaml"
    cfg_path.write_text(
        "hotkey:\n  modifiers: [super, alt]\n  key: space\nstt:\n  engine: whisper\n"
    )
    return str(cfg_path)


class TestPersistenceRoundtrip:
    def test_saved_hotkey_survives_restart(self, xdg_config):
        # The editor's Save writes to the config file...
        save_hotkey_config(xdg_config, ["alt", "ctrl"], "super")

        # ...and a fresh start resolves the same combo.
        assert resolve_config_path(None) == xdg_config
        config = load_config(None)
        modifiers, key = resolve_hotkey_config(config)
        assert modifiers == ["alt", "ctrl"]
        assert key == "super"

    def test_save_preserves_unrelated_settings(self, xdg_config):
        save_hotkey_config(xdg_config, ["ctrl"], "d")
        config = load_config(None)
        assert config["stt"]["engine"] == "whisper"

    def test_save_creates_config_when_none_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cfg_path = str(tmp_path / ".config" / "verbal-code" / "config.yaml")

        save_hotkey_config(cfg_path, ["super"], "v")

        assert os.path.isfile(cfg_path)
        modifiers, key = resolve_hotkey_config(load_config(None))
        assert (modifiers, key) == (["super"], "v")


class TestResolveHotkeyConfig:
    def test_no_saved_hotkey_uses_defaults(self):
        modifiers, key = resolve_hotkey_config({})
        assert modifiers == DEFAULT_HOTKEY_MODIFIERS
        assert key == DEFAULT_HOTKEY_KEY

    def test_valid_saved_combo_is_used(self):
        config = {"hotkey": {"modifiers": ["Ctrl", "SUPER"], "key": "Alt"}}
        modifiers, key = resolve_hotkey_config(config)
        assert modifiers == ["ctrl", "super"]  # normalised to lowercase
        assert key == "alt"

    @pytest.mark.parametrize(
        "hotkey",
        [
            {"modifiers": "ctrl", "key": "d"},  # string, not a list
            {"modifiers": ["ctrl", "hyper"], "key": "d"},  # unknown modifier
            {"modifiers": [], "key": "d"},  # empty combo
            {"modifiers": ["ctrl", 3], "key": "d"},  # non-string entry
            {"modifiers": ["ctrl"], "key": 7},  # numeric key
            {"modifiers": ["ctrl"], "key": "  "},  # blank key
        ],
    )
    def test_malformed_saved_combo_falls_back(self, hotkey, caplog):
        with caplog.at_level("WARNING"):
            modifiers, key = resolve_hotkey_config({"hotkey": hotkey})
        assert modifiers == DEFAULT_HOTKEY_MODIFIERS
        assert key == DEFAULT_HOTKEY_KEY
        assert "invalid" in caplog.text.lower()

    def test_fallback_returns_a_copy(self):
        modifiers, _ = resolve_hotkey_config({})
        modifiers.append("shift")
        assert DEFAULT_HOTKEY_MODIFIERS == ["super", "alt"]
