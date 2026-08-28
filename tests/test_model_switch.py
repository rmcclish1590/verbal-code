"""Tray model-switch flow tests (MCC-16) — bare VerbalCode, fake tray/transcriber."""

import threading

import yaml

from verbal_code.app import VerbalCode


class _FakeTray:
    def __init__(self):
        self.states: list[str] = []
        self.notifications: list[str] = []
        self.model: tuple[str, str] | None = None

    def set_state(self, state):
        self.states.append(getattr(state, "value", str(state)))

    def notify(self, title, msg):
        self.notifications.append(msg)

    def set_model(self, engine, model):
        self.model = (engine, model)


class _FakeTrayState:
    class _S:
        def __init__(self, value):
            self.value = value

    IDLE = _S("idle")
    LISTENING = _S("listening")
    PROCESSING = _S("processing")
    ERROR = _S("error")


class _FakeTranscriber:
    supports_live_streaming = False

    def __init__(self, fail=False):
        self.fail = fail
        self.loaded = False

    def load_model(self):
        if self.fail:
            raise RuntimeError("model download failed")
        self.loaded = True


def _make_app(tmp_path, fail_load=False, recording=False, monkeypatch=None):
    app = object.__new__(VerbalCode)
    app.config = {"stt": {"engine": "whisper", "whisper": {"model": "distil-small.en"}}}
    app._config_path = str(tmp_path / "config.yaml")
    app.tray = _FakeTray()
    app._TrayState = _FakeTrayState
    app._recording = recording
    app._streaming_enabled = False
    app._live_injection = False
    app._model_switch_lock = threading.Lock()
    app._dictation_lock = threading.Lock()
    app.transcriber = _FakeTranscriber()
    if monkeypatch is not None:
        import verbal_code.transcriber as transcriber_module

        monkeypatch.setattr(
            transcriber_module,
            "create_transcriber",
            lambda config: _FakeTranscriber(fail=fail_load),
        )
    return app


class TestModelSwitch:
    def test_switch_swaps_transcriber_and_persists(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path, monkeypatch=monkeypatch)
        old = app.transcriber
        app._switch_model("whisper", "small.en")

        assert app.transcriber is not old
        assert app.transcriber.loaded
        assert app.config["stt"]["whisper"]["model"] == "small.en"
        assert app.tray.model == ("whisper", "small.en")
        assert app.tray.states[-1] == "idle"

        with open(app._config_path) as f:
            saved = yaml.safe_load(f)
        assert saved["stt"]["engine"] == "whisper"
        assert saved["stt"]["whisper"]["model"] == "small.en"

    def test_failed_load_keeps_old_transcriber(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path, fail_load=True, monkeypatch=monkeypatch)
        old = app.transcriber
        app._switch_model("whisper", "small.en")

        assert app.transcriber is old
        assert app.tray.states[-1] == "error"
        assert app.tray.model is None

    def test_dictation_during_load_cancels_swap(self, tmp_path, monkeypatch):
        """MCC-44: a dictation started mid-load must keep its transcriber."""
        import os

        import verbal_code.transcriber as transcriber_module

        app = _make_app(tmp_path)
        old = app.transcriber

        class _RacingTranscriber(_FakeTranscriber):
            def load_model(self):
                app._recording = True  # dictation starts while loading
                super().load_model()

        monkeypatch.setattr(
            transcriber_module,
            "create_transcriber",
            lambda config: _RacingTranscriber(),
        )
        app._switch_model("whisper", "small.en")

        assert app.transcriber is old
        assert app.config["stt"]["whisper"]["model"] == "distil-small.en"
        assert not os.path.isfile(app._config_path)  # nothing persisted
        assert app.tray.model is None
        assert app.tray.states[-1] == "listening"
        assert any("cancelled" in n for n in app.tray.notifications)

    def test_switch_refused_while_recording(self, tmp_path, monkeypatch):
        app = _make_app(tmp_path, recording=True, monkeypatch=monkeypatch)
        old = app.transcriber
        app._switch_model("vosk", "vosk-model-small-en-us-0.15")

        assert app.transcriber is old
        assert any("Finish" in n for n in app.tray.notifications)
