import os
import sys
import tempfile

import pytest

from verbal_code import app
from verbal_code.app import load_config, main, validate_config


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

    def test_whisper_rejects_non_16k_sample_rate(self):
        config = {
            "hotkey": {},
            "stt": {"engine": "whisper"},
            "audio": {"sample_rate": 48000},
        }
        with pytest.raises(SystemExit):
            validate_config(config)

    def test_whisper_accepts_16k_sample_rate(self):
        config = {
            "hotkey": {},
            "stt": {"engine": "whisper"},
            "audio": {"sample_rate": 16000},
        }
        validate_config(config)


class TestMainValidatesBeforeTestModes:
    """validate_config must run before the diagnostic modes (MCC-6)."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))

    @pytest.mark.parametrize("flag", ["--test-audio", "--test-transcribe", "--test-inject"])
    def test_test_modes_run_after_validation(self, monkeypatch, flag):
        runner = "_run" + flag.replace("--", "_").replace("-", "_")
        monkeypatch.setattr("sys.argv", ["verbal-code", flag])
        monkeypatch.setattr(app, "validate_config", lambda config: sys.exit(1))
        monkeypatch.setattr(
            app, runner, lambda config: pytest.fail(f"{runner} ran before validate_config")
        )
        with pytest.raises(SystemExit):
            main()

    def test_list_devices_skips_validation(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["verbal-code", "--list-devices"])
        monkeypatch.setattr(
            app,
            "validate_config",
            lambda config: pytest.fail("validate_config ran for --list-devices"),
        )
        monkeypatch.setattr(app, "_run_list_devices", lambda: None)
        with pytest.raises(SystemExit):
            main()
