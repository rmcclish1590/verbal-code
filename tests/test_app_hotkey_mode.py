"""hotkey.mode dispatch tests (MCC-13) — bare VerbalCode instance, no GTK/audio."""

import pytest

from verbal_code.app import VerbalCode, validate_config


class _Recorder:
    def __init__(self):
        self.calls: list[str] = []


def _make_app(mode: str, recording: bool = False):
    app = object.__new__(VerbalCode)
    app._hotkey_mode = mode
    app._recording = recording
    rec = _Recorder()
    app._on_dictation_start = lambda: rec.calls.append("start")
    app._on_dictation_stop = lambda: rec.calls.append("stop")
    return app, rec


class TestHoldMode:
    def test_press_starts_release_stops(self):
        app, rec = _make_app("hold")
        app._on_hotkey_pressed()
        app._on_hotkey_released()
        assert rec.calls == ["start", "stop"]


class TestToggleMode:
    def test_press_starts_when_idle(self):
        app, rec = _make_app("toggle", recording=False)
        app._on_hotkey_pressed()
        assert rec.calls == ["start"]

    def test_press_stops_when_recording(self):
        app, rec = _make_app("toggle", recording=True)
        app._on_hotkey_pressed()
        assert rec.calls == ["stop"]

    def test_release_is_ignored(self):
        app, rec = _make_app("toggle", recording=True)
        app._on_hotkey_released()
        assert rec.calls == []


class TestModeValidation:
    def test_invalid_mode_exits(self):
        config = {
            "hotkey": {"mode": "sometimes"},
            "stt": {"engine": "whisper"},
            "audio": {"sample_rate": 16000},
        }
        with pytest.raises(SystemExit):
            validate_config(config)

    @pytest.mark.parametrize("mode", ["hold", "toggle"])
    def test_valid_modes_pass(self, mode):
        config = {
            "hotkey": {"mode": mode},
            "stt": {"engine": "whisper"},
            "audio": {"sample_rate": 16000},
        }
        validate_config(config)
