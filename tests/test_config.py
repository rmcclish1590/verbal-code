import os
import tempfile

import pytest

from verbal_code.app import load_config, validate_config


class TestLoadConfig:
    def test_loads_from_explicit_path(self, tmp_path):
        cfg_file = tmp_path / "test.yaml"
        cfg_file.write_text("hotkey:\n  key: x\n")
        config = load_config(str(cfg_file))
        assert config["hotkey"]["key"] == "x"

    def test_returns_empty_dict_when_no_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        assert config == {}

    def test_explicit_path_takes_priority(self, tmp_path):
        cfg1 = tmp_path / "first.yaml"
        cfg1.write_text("stt:\n  engine: whisper\n")
        cfg2 = tmp_path / "second.yaml"
        cfg2.write_text("stt:\n  engine: vosk\n")
        config = load_config(str(cfg1))
        assert config["stt"]["engine"] == "whisper"

    def test_empty_yaml_returns_empty_dict(self, tmp_path):
        cfg_file = tmp_path / "empty.yaml"
        cfg_file.write_text("")
        config = load_config(str(cfg_file))
        assert config == {}


class TestValidateConfig:
    def test_warns_on_unknown_sections(self, caplog):
        config = {"hotkey": {}, "stt": {"engine": "whisper"}, "audio": {}, "bogus": {}}
        with caplog.at_level("WARNING"):
            try:
                validate_config(config)
            except SystemExit:
                pass
        assert "Unknown config sections" in caplog.text
        assert "bogus" in caplog.text

    def test_warns_on_missing_required_sections(self, caplog):
        config = {"stt": {"engine": "whisper"}}
        with caplog.at_level("WARNING"):
            try:
                validate_config(config)
            except SystemExit:
                pass
        assert "Missing config section" in caplog.text
