"""Transcription-model persistence tests (MCC-33).

Proves the full cycle: switching models via the tray writes the choice to
the config file, and a restart (load_config) resolves that saved model
instead of falling back to the default.
"""

import threading

import pytest

from verbal_code.app import VerbalCode, load_config, resolve_config_path
from verbal_code.transcriber import current_selection


@pytest.fixture
def xdg_config(tmp_path, monkeypatch):
    """Isolated HOME with an XDG config file, as a normal install has."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.chdir(tmp_path)
    cfg_dir = tmp_path / ".config" / "verbal-code"
    cfg_dir.mkdir(parents=True)
    cfg_path = cfg_dir / "config.yaml"
    cfg_path.write_text(
        "hotkey:\n  modifiers: [super, alt]\n  key: space\n"
        "stt:\n  engine: whisper\n  whisper:\n    model: distil-small.en\n"
    )
    return str(cfg_path)


class _FakeTray:
    def __init__(self):
        self.model = None

    def set_state(self, state):
        pass

    def notify(self, title, msg):
        pass

    def set_model(self, engine, model):
        self.model = (engine, model)


class _FakeTrayState:
    class _S:
        def __init__(self, value):
            self.value = value

    IDLE = _S("idle")
    PROCESSING = _S("processing")
    ERROR = _S("error")


class _FakeTranscriber:
    supports_live_streaming = False

    def load_model(self):
        pass


def _make_app(config_path, config):
    app = object.__new__(VerbalCode)
    app.config = config
    app._config_path = config_path
    app.tray = _FakeTray()
    app._TrayState = _FakeTrayState
    app._recording = False
    app._streaming_enabled = False
    app._live_injection = False
    app._model_switch_lock = threading.Lock()
    app._dictation_lock = threading.Lock()
    app.transcriber = _FakeTranscriber()
    return app


class TestPersistenceRoundtrip:
    def test_switched_model_survives_restart(self, xdg_config, monkeypatch):
        import verbal_code.transcriber as transcriber_module

        monkeypatch.setattr(
            transcriber_module, "create_transcriber", lambda cfg: _FakeTranscriber()
        )

        # The tray's quick-switch writes to the config file...
        app = _make_app(xdg_config, load_config(None))
        app._switch_model("whisper", "small.en")

        # ...and a fresh start resolves the same model.
        assert resolve_config_path(None) == xdg_config
        restarted_config = load_config(None)
        assert current_selection(restarted_config) == ("whisper", "small.en")

    def test_switch_preserves_unrelated_settings(self, xdg_config, monkeypatch):
        import verbal_code.transcriber as transcriber_module

        monkeypatch.setattr(
            transcriber_module, "create_transcriber", lambda cfg: _FakeTranscriber()
        )

        app = _make_app(xdg_config, load_config(None))
        app._switch_model("whisper", "small.en")

        config = load_config(None)
        assert config["hotkey"]["key"] == "space"

    def test_switch_creates_config_when_none_exists(self, tmp_path, monkeypatch):
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        cfg_path = str(tmp_path / ".config" / "verbal-code" / "config.yaml")

        import verbal_code.transcriber as transcriber_module

        monkeypatch.setattr(
            transcriber_module, "create_transcriber", lambda cfg: _FakeTranscriber()
        )

        app = _make_app(cfg_path, {})
        app._switch_model("vosk", "vosk-model-small-en-us-0.15")

        assert current_selection(load_config(None)) == (
            "vosk",
            "vosk-model-small-en-us-0.15",
        )


class TestCurrentSelectionNoSavedChoice:
    def test_no_saved_selection_uses_default(self):
        assert current_selection({}) == ("whisper", "distil-small.en")
