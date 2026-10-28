"""Engine hot-swap and per-engine dictation flow (MCC-125).

Swaps run through the real ``_switch_model`` with the real transcriber
classes from ``create_transcriber`` — only ``load_model`` is stubbed (no
downloads), so each engine's real ``unload_model`` runs.  The dictation
tests drive ``_on_dictation_start``/``_on_dictation_stop`` with a spy
transcriber that carries each engine's real ``supports_live_streaming``.
"""

import os
import tempfile
import threading

import numpy as np
import pytest

import verbal_code.transcriber as transcriber_module
from verbal_code.app import VerbalCode
from verbal_code.dictionary import DictionaryStore
from verbal_code.dictionary_corrector import DictionaryCorrector
from verbal_code.injector import TextProcessor
from verbal_code.transcriber import AVAILABLE_MODELS, create_transcriber

ENGINES = ["parakeet", "sherpa", "whisper", "moonshine", "vosk"]
LIVE = {"sherpa", "vosk"}

# The attribute(s) each engine's load_model fills and unload_model clears.
_MODEL_ATTRS = {
    transcriber_module.ParakeetTranscriber: ("_model",),
    transcriber_module.SherpaOnnxTranscriber: ("_recognizer", "_stream"),
    transcriber_module.WhisperTranscriber: ("_model", "_batched"),
    transcriber_module.MoonshineTranscriber: ("_model", "_tokenizer"),
    transcriber_module.VoskTranscriber: ("_model", "_recognizer"),
}


class _State:
    def __init__(self, value):
        self.value = value


class _TrayState:
    IDLE = _State("idle")
    LISTENING = _State("listening")
    PROCESSING = _State("processing")
    ERROR = _State("error")


class _FakeTray:
    def __init__(self):
        self.states: list[str] = []
        self.notifications: list[str] = []
        self.model: tuple[str, str] | None = None

    def set_state(self, state):
        self.states.append(state.value)

    def notify(self, title, msg):
        self.notifications.append(msg)

    def set_model(self, engine, model):
        self.model = (engine, model)


@pytest.fixture
def events(monkeypatch):
    """Stub every engine's load_model and record load/unload order."""
    log: list[tuple[str, object]] = []

    for cls, attrs in _MODEL_ATTRS.items():
        real_unload = cls.unload_model

        def fake_load(self, attrs=attrs):
            for attr in attrs:
                setattr(self, attr, object())
            log.append(("load", self))

        def spy_unload(self, real_unload=real_unload):
            log.append(("unload", self))
            real_unload(self)

        monkeypatch.setattr(cls, "load_model", fake_load)
        monkeypatch.setattr(cls, "unload_model", spy_unload)
    return log


def _is_loaded(transcriber) -> bool:
    attrs = _MODEL_ATTRS[type(transcriber)]
    return all(getattr(transcriber, attr) is not None for attr in attrs)


def _make_switch_app(tmp_path, engine="whisper", streaming=True):
    app = object.__new__(VerbalCode)
    app.config = {"stt": {"engine": engine, "streaming_enabled": streaming}}
    app._config_path = str(tmp_path / "config.yaml")
    app.tray = _FakeTray()
    app._TrayState = _TrayState
    app._recording = False
    app._processing = False
    app._streaming_enabled = streaming
    app._model_switch_lock = threading.Lock()
    app._dictation_lock = threading.Lock()
    app.transcriber = create_transcriber(app.config)
    app.transcriber.load_model()
    app._live_injection = streaming and app.transcriber.supports_live_streaming
    return app


class TestHotSwapAcrossEngines:
    def test_cycle_through_every_engine(self, tmp_path, events):
        app = _make_switch_app(tmp_path)  # starts on whisper
        # Visits every engine and crosses batch->live and live->batch.
        for engine in ["parakeet", "sherpa", "moonshine", "vosk", "whisper"]:
            previous = app.transcriber
            model = AVAILABLE_MODELS[engine][-1]
            events.clear()

            app._switch_model(engine, model)

            current = app.transcriber
            assert current is not previous
            assert app.tray.model == (engine, model)
            assert app.config["stt"]["engine"] == engine
            assert app.tray.states[-1] == "idle"
            # New model loaded first; the old one unloaded only after commit,
            # so a failed or cancelled switch would still have had it.
            assert events == [("load", current), ("unload", previous)]
            assert _is_loaded(current)
            assert not any(
                getattr(previous, attr) for attr in _MODEL_ATTRS[type(previous)]
            )
            assert app._live_injection is (engine in LIVE)

    def test_failed_load_unloads_partial_model_and_keeps_old(
        self, tmp_path, events, monkeypatch
    ):
        app = _make_switch_app(tmp_path)
        old = app.transcriber
        events.clear()

        def failing_load(self):
            self._model = object()  # something loaded before the failure
            raise RuntimeError("download interrupted")

        monkeypatch.setattr(
            transcriber_module.ParakeetTranscriber, "load_model", failing_load
        )
        app._switch_model("parakeet", AVAILABLE_MODELS["parakeet"][0])

        assert app.transcriber is old and _is_loaded(old)
        assert [kind for kind, _ in events] == ["unload"]
        assert events[0][1] is not old
        assert app.tray.states[-1] == "error"

    @pytest.mark.parametrize(
        "busy, tray_state",
        [("_recording", "listening"), ("_processing", "processing")],
    )
    def test_dictation_during_load_cancels_and_unloads_new_model(
        self, tmp_path, events, monkeypatch, busy, tray_state
    ):
        """A dictation that started — or is still being transcribed after
        release — keeps its transcriber, which therefore must not be
        unloaded (MCC-44, extended by MCC-125)."""
        app = _make_switch_app(tmp_path)
        old = app.transcriber
        events.clear()
        real_load = transcriber_module.SherpaOnnxTranscriber.load_model

        def load_during_dictation(self):
            setattr(app, busy, True)
            real_load(self)

        monkeypatch.setattr(
            transcriber_module.SherpaOnnxTranscriber,
            "load_model",
            load_during_dictation,
        )
        app._switch_model("sherpa", AVAILABLE_MODELS["sherpa"][0])

        assert app.transcriber is old and _is_loaded(old)
        new = events[0][1]
        assert events == [("load", new), ("unload", new)]
        assert not _is_loaded(new)
        assert app.config["stt"]["engine"] == "whisper"
        assert not os.path.exists(app._config_path)
        assert app.tray.states[-1] == tray_state
        assert any("cancelled" in n for n in app.tray.notifications)

    def test_unload_failure_does_not_fail_the_switch(
        self, tmp_path, events, monkeypatch
    ):
        app = _make_switch_app(tmp_path)

        def broken_unload(self):
            raise RuntimeError("driver error")

        monkeypatch.setattr(
            transcriber_module.WhisperTranscriber, "unload_model", broken_unload
        )
        app._switch_model("parakeet", AVAILABLE_MODELS["parakeet"][0])

        assert isinstance(app.transcriber, transcriber_module.ParakeetTranscriber)
        assert app.tray.states[-1] == "idle"


# --- Per-engine dictation flow ------------------------------------------------

_CHUNK = 1024
_SILENCE = np.zeros(8000, dtype=np.float32)  # 0.5s, trimmed before batch


def _speech(seconds=1.0):
    t = np.arange(int(16000 * seconds)) / 16000
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


class _ChunkedCapture:
    """Serves a recording chunk by chunk, like AudioCapture's read cursor."""

    def __init__(self, audio):
        self.audio = audio
        self._chunks = [audio[i : i + _CHUNK] for i in range(0, len(audio), _CHUNK)]
        self._pos = 0
        self._lock = threading.Lock()

    def start(self):
        pass

    def stop(self):
        return self.audio

    def get_chunk(self, timeout=0.1):
        with self._lock:
            if self._pos < len(self._chunks):
                self._pos += 1
                return self._chunks[self._pos - 1]
        threading.Event().wait(timeout)
        return None

    def get_all_chunks(self):
        with self._lock:
            rest = self._chunks[self._pos :]
            self._pos = len(self._chunks)
            return rest

    @property
    def chunk_count(self):
        return len(self._chunks)


class _SpyTranscriber:
    def __init__(self, supports_live_streaming):
        self.supports_live_streaming = supports_live_streaming
        self.stream_chunks = 0
        self.finalize_calls = 0
        self.batch_audio: list[np.ndarray] = []
        self.resets = 0

    def reset(self):
        self.resets += 1

    def transcribe_stream(self, chunk):
        self.stream_chunks += 1
        return iter(())

    def stream_finalize(self):
        self.finalize_calls += 1
        return "tail words"

    def transcribe_batch(self, audio):
        self.batch_audio.append(audio)
        return "batch words"


class _FakeInjector:
    def __init__(self):
        self.injected: list[str] = []

    def inject(self, text):
        self.injected.append(text)


def _make_dictation_app(engine, audio):
    real_flag = type(create_transcriber({"stt": {"engine": engine}}))
    app = object.__new__(VerbalCode)
    app.config = {"audio": {"sample_rate": 16000}}
    app.capture = _ChunkedCapture(audio)
    app.transcriber = _SpyTranscriber(real_flag.supports_live_streaming)
    app.injector = _FakeInjector()
    app.text_processor = TextProcessor()
    app.tray = _FakeTray()
    app._TrayState = _TrayState
    app._dictation_lock = threading.Lock()
    app._recording = False
    app._processing = False
    app._record_start = 0.0
    app._stream_thread = None
    app._stream_stop = threading.Event()
    app._streaming_enabled = True
    app._live_injection = app.transcriber.supports_live_streaming
    app._trim_silence_enabled = True
    app._trim_threshold_db = -40.0
    app._log_transcripts = False
    app._max_record_seconds = 0  # no watchdog timer thread
    app._max_record_timer = None
    app._dictionary_enabled = False
    app.dictionary_corrector = DictionaryCorrector(
        DictionaryStore(os.path.join(tempfile.mkdtemp(), "dictionary.json"))
    )
    return app


@pytest.mark.parametrize("engine", ENGINES)
def test_dictation_follows_engine_streaming_contract(engine):
    audio = np.concatenate([_SILENCE, _speech(), _SILENCE])
    app = _make_dictation_app(engine, audio)
    spy = app.transcriber

    app._on_dictation_start()
    thread = app._stream_thread
    if engine in LIVE:
        assert thread is not None and thread.is_alive()
    else:
        assert thread is None  # MCC-42: no streaming loop for batch engines
    app._on_dictation_stop()

    # No orphaned streaming thread or busy state survives the dictation.
    assert app._stream_thread is None
    assert thread is None or not thread.is_alive()
    assert app._processing is False and app._recording is False
    assert spy.resets == 1

    if engine in LIVE:
        assert spy.stream_chunks == app.capture.chunk_count  # every chunk fed
        assert spy.finalize_calls == 1
        assert spy.batch_audio == []
        assert app.injector.injected == ["Tail words "]
    else:
        assert spy.stream_chunks == 0
        assert spy.finalize_calls == 0
        assert len(spy.batch_audio) == 1
        # trim_silence ran first: the leading/trailing silence is gone.
        assert len(spy.batch_audio[0]) < len(audio)
        assert app.injector.injected == ["Batch words "]
    assert app.tray.states[-1] == "idle"


def test_processing_flag_clears_when_transcription_fails():
    app = _make_dictation_app("parakeet", _speech())

    def explode(audio):
        raise RuntimeError("engine exploded")

    app.transcriber.transcribe_batch = explode
    app._on_dictation_start()
    app._on_dictation_stop()

    assert app._processing is False
    assert app.tray.states[-1] == "error"
