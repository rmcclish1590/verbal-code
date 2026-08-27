import contextlib
import logging
import sys

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
        with caplog.at_level("WARNING"), contextlib.suppress(SystemExit):
            validate_config(config)
        assert "Unknown config sections" in caplog.text
        assert "bogus" in caplog.text

    def test_warns_on_missing_required_sections(self, caplog):
        config = {"stt": {"engine": "whisper"}}
        with caplog.at_level("WARNING"), contextlib.suppress(SystemExit):
            validate_config(config)
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


class TestNumericConfigValidation:
    """Numeric config values are bounds-checked at startup (MCC-8)."""

    @staticmethod
    def _config(**overrides):
        config = {
            "hotkey": {},
            "stt": {"engine": "whisper", "whisper": {}},
            "audio": {"sample_rate": 16000},
            "injection": {},
            "vad": {},
        }
        for dotted, value in overrides.items():
            section, key = dotted.rsplit("__", 1)
            target = config
            for part in section.split("__"):
                target = target.setdefault(part, {})
            target[key] = value
        return config

    def test_valid_config_passes(self):
        validate_config(
            self._config(
                audio__chunk_size=1024,
                stt__whisper__beam_size=5,
                stt__whisper__batch_size=8,
                injection__delay_ms=0,
                vad__trim_threshold_db=-40.0,
            )
        )

    @pytest.mark.parametrize(
        "overrides",
        [
            {"audio__sample_rate": "16000"},  # string, not int
            {"audio__sample_rate": True},  # bool is not a count
            {"audio__sample_rate": 4000},  # below range
            {"audio__channels": 0},
            {"audio__chunk_size": 63},
            {"audio__chunk_size": 10**9},  # resource exhaustion
            {"audio__chunk_size": 1024.5},  # float for int field
            {"stt__whisper__beam_size": 0},
            {"stt__whisper__beam_size": 100},
            {"stt__whisper__batch_size": 0},
            {"injection__delay_ms": -1},
            {"injection__delay_ms": 5000},
            {"vad__trim_threshold_db": 3},  # positive dBFS is nonsense
            {"vad__trim_threshold_db": "loud"},
        ],
    )
    def test_bad_values_exit(self, overrides):
        with pytest.raises(SystemExit):
            validate_config(self._config(**overrides))

    def test_missing_values_use_defaults(self):
        validate_config({"stt": {"engine": "whisper"}, "audio": {}, "hotkey": {}})

    def test_error_names_the_offending_key(self, caplog):
        with caplog.at_level("ERROR"), pytest.raises(SystemExit):
            validate_config(self._config(stt__whisper__beam_size=100))
        assert "stt.whisper.beam_size" in caplog.text


class TestSetupLogging:
    """logging.file is sanitized before reaching FileHandler (MCC-9)."""

    @pytest.fixture(autouse=True)
    def _restore_root_logger(self):
        root = logging.getLogger()
        saved = (root.handlers[:], root.level)
        yield
        for handler in root.handlers[:]:
            if handler not in saved[0]:
                handler.close()
        root.handlers, root.level = saved

    @staticmethod
    def _file_handlers():
        root = logging.getLogger()
        return [h for h in root.handlers if isinstance(h, logging.FileHandler)]

    def test_valid_path_adds_file_handler(self, tmp_path):
        log_file = tmp_path / "app.log"
        app.setup_logging({"logging": {"file": str(log_file)}})
        handlers = self._file_handlers()
        assert len(handlers) == 1
        assert handlers[0].baseFilename == str(log_file)

    def test_tilde_is_expanded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        app.setup_logging({"logging": {"file": "~/app.log"}})
        handlers = self._file_handlers()
        assert len(handlers) == 1
        assert handlers[0].baseFilename == str(tmp_path / "app.log")

    def test_missing_parent_directory_degrades_to_console(self, tmp_path, capsys):
        log_file = tmp_path / "nonexistent" / "app.log"
        app.setup_logging({"logging": {"file": str(log_file)}})
        assert self._file_handlers() == []
        assert "does not exist" in capsys.readouterr().err

    def test_symlink_is_refused(self, tmp_path, capsys):
        target = tmp_path / "target.log"
        target.write_text("")
        link = tmp_path / "link.log"
        link.symlink_to(target)
        app.setup_logging({"logging": {"file": str(link)}})
        assert self._file_handlers() == []
        assert "symlink" in capsys.readouterr().err

    def test_directory_is_refused(self, tmp_path, capsys):
        app.setup_logging({"logging": {"file": str(tmp_path)}})
        assert self._file_handlers() == []
        assert "directory" in capsys.readouterr().err

    def test_no_file_configured_is_console_only(self):
        app.setup_logging({})
        assert self._file_handlers() == []


class TestMainValidatesBeforeTestModes:
    """validate_config must run before the diagnostic modes (MCC-6)."""

    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))

    @pytest.mark.parametrize(
        "flag", ["--test-audio", "--test-transcribe", "--test-inject"]
    )
    def test_test_modes_run_after_validation(self, monkeypatch, flag):
        runner = "_run" + flag.replace("--", "_").replace("-", "_")
        monkeypatch.setattr("sys.argv", ["verbal-code", flag])
        monkeypatch.setattr(app, "validate_config", lambda config: sys.exit(1))
        monkeypatch.setattr(
            app,
            runner,
            lambda config: pytest.fail(f"{runner} ran before validate_config"),
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
