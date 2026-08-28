"""Dictation orchestration tests (MCC-25) — bare VerbalCode with fakes.

Covers the _on_dictation_stop pipeline end to end: guard clauses, silence
trimming, transcription failure, successful injection, and the live-streaming
finish path.
"""

import threading

import numpy as np

from verbal_code.app import VerbalCode
from verbal_code.injector import TextProcessor


class _TrayState:
    class _S:
        def __init__(self, value):
            self.value = value

    IDLE = _S("idle")
    LISTENING = _S("listening")
    PROCESSING = _S("processing")
    ERROR = _S("error")


class _FakeTray:
    def __init__(self):
        self.states = []
        self.notifications = []

    def set_state(self, state):
        self.states.append(state.value)

    def notify(self, title, msg):
        self.notifications.append(msg)


class _FakeCapture:
    def __init__(self, audio):
        self.audio = audio
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        return self.audio

    def get_chunk(self, timeout=0.1):
        return None

    def get_all_chunks(self):
        return []


class _FakeTranscriber:
    supports_live_streaming = False

    def __init__(self, text="hello world", fail=False, tail=""):
        self.text = text
        self.fail = fail
        self.tail = tail
        self.batch_calls = 0

    def transcribe_batch(self, audio):
        self.batch_calls += 1
        if self.fail:
            raise RuntimeError("engine exploded")
        return self.text

    def stream_finalize(self):
        return self.tail

    def reset(self):
        return None


class _FakeInjector:
    def __init__(self):
        self.injected = []

    def inject(self, text):
        self.injected.append(text)


def _make_app(audio, transcriber, live=False):
    app = object.__new__(VerbalCode)
    app.config = {"audio": {"sample_rate": 16000}}
    app.capture = _FakeCapture(audio)
    app.transcriber = transcriber
    app.injector = _FakeInjector()
    app.text_processor = TextProcessor()
    app.tray = _FakeTray()
    app._TrayState = _TrayState
    app._dictation_lock = threading.Lock()
    app._recording = True
    app._record_start = 0.0
    app._stream_thread = None
    app._stream_stop = threading.Event()
    app._live_injection = live
    app._streaming_enabled = live
    app._trim_silence_enabled = True
    app._trim_threshold_db = -40.0
    app._log_transcripts = False
    app._max_record_seconds = 300.0
    app._max_record_timer = None
    return app


def _speech(seconds=1.0):
    t = np.arange(int(16000 * seconds)) / 16000
    return (0.5 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


class TestDictationStop:
    def test_happy_path_injects_processed_text(self):
        app = _make_app(_speech(), _FakeTranscriber(text="hello world"))
        app._on_dictation_stop()

        assert app.injector.injected == ["Hello world "]
        assert app.transcriber.batch_calls == 1
        assert app.tray.states[-1] == "idle"
        assert not app._recording
        assert app.capture.stopped

    def test_no_active_recording_is_a_noop(self):
        app = _make_app(_speech(), _FakeTranscriber())
        app._recording = False
        app._on_dictation_stop()

        assert app.transcriber.batch_calls == 0
        assert app.injector.injected == []

    def test_short_audio_skips_transcription(self):
        app = _make_app(_speech(seconds=0.1), _FakeTranscriber())
        app._on_dictation_stop()

        assert app.transcriber.batch_calls == 0
        assert app.injector.injected == []
        assert app.tray.states[-1] == "idle"

    def test_pure_silence_skips_transcription(self):
        silence = np.zeros(16000, dtype=np.float32)
        app = _make_app(silence, _FakeTranscriber())
        app._on_dictation_stop()

        assert app.transcriber.batch_calls == 0
        assert app.tray.states[-1] == "idle"

    def test_transcription_failure_sets_error_state(self):
        app = _make_app(_speech(), _FakeTranscriber(fail=True))
        app._on_dictation_stop()

        assert app.injector.injected == []
        assert app.tray.states[-1] == "error"
        assert any("failed" in n.lower() for n in app.tray.notifications)

    def test_empty_transcription_is_not_injected(self):
        app = _make_app(_speech(), _FakeTranscriber(text="   "))
        app._on_dictation_stop()

        assert app.injector.injected == []
        assert app.tray.states[-1] == "idle"

    def test_trim_disabled_passes_raw_audio(self):
        silence = np.zeros(16000, dtype=np.float32)
        app = _make_app(silence, _FakeTranscriber(text="ok"))
        app._trim_silence_enabled = False
        app._on_dictation_stop()

        assert app.transcriber.batch_calls == 1  # silence still transcribed


class TestLiveDictationStop:
    def test_live_path_flushes_tail_and_skips_batch(self):
        transcriber = _FakeTranscriber(tail="last words")
        transcriber.supports_live_streaming = True
        app = _make_app(_speech(), transcriber, live=True)
        app._on_dictation_stop()

        assert transcriber.batch_calls == 0
        assert app.injector.injected == ["Last words "]
        assert app.tray.states[-1] == "idle"

    def test_live_path_with_empty_tail_goes_idle(self):
        transcriber = _FakeTranscriber(tail="")
        transcriber.supports_live_streaming = True
        app = _make_app(_speech(), transcriber, live=True)
        app._on_dictation_stop()

        assert app.injector.injected == []
        assert app.tray.states[-1] == "idle"

    def test_live_path_joins_stream_thread(self):
        transcriber = _FakeTranscriber(tail="")
        transcriber.supports_live_streaming = True
        app = _make_app(_speech(), transcriber, live=True)
        ran = threading.Event()

        def _fake_stream():
            ran.wait(2.0)

        thread = threading.Thread(target=_fake_stream)
        thread.start()
        app._stream_thread = thread
        ran.set()
        app._on_dictation_stop()

        assert app._stream_thread is None
        assert not thread.is_alive()


class TestStreamingThreadGating:
    """MCC-42: streaming runs only when its text can be injected live.

    For engines with revisable partials the loop would re-transcribe the
    whole session every interval (O(n²) CPU) just to produce debug logs.
    """

    def test_no_stream_thread_without_live_injection(self):
        app = _make_app(_speech(), _FakeTranscriber())
        app._recording = False
        app._streaming_enabled = True  # on, but the engine can't inject live
        app._live_injection = False
        app._max_record_seconds = 0
        app._on_dictation_start()
        try:
            assert app._stream_thread is None
            assert app.capture.started
        finally:
            app._recording = False

    def test_stream_thread_starts_with_live_injection(self):
        transcriber = _FakeTranscriber()
        transcriber.supports_live_streaming = True
        app = _make_app(_speech(), transcriber, live=True)
        app._recording = False
        app._max_record_seconds = 0
        app._on_dictation_start()
        try:
            assert app._stream_thread is not None
        finally:
            app._join_stream_thread()
            app._recording = False


class TestMaxRecordingDuration:
    """MCC-41: a forgotten toggle-mode recording must not grow forever."""

    def test_watchdog_stops_recording_and_transcribes(self):
        app = _make_app(_speech(), _FakeTranscriber(text="captured anyway"))
        app._on_max_duration_reached()

        assert app.capture.stopped
        assert not app._recording
        assert app.transcriber.batch_calls == 1
        assert app.injector.injected == ["Captured anyway "]
        assert any(
            "Maximum recording length" in n for n in app.tray.notifications
        )

    def test_watchdog_is_a_noop_when_not_recording(self):
        app = _make_app(_speech(), _FakeTranscriber())
        app._recording = False
        app._on_max_duration_reached()

        assert not app.capture.stopped
        assert app.transcriber.batch_calls == 0
        assert app.tray.notifications == []

    def test_normal_stop_cancels_the_watchdog(self):
        app = _make_app(_speech(), _FakeTranscriber())
        timer = threading.Timer(3600, lambda: None)
        timer.daemon = True
        timer.start()
        app._max_record_timer = timer
        app._on_dictation_stop()

        assert app._max_record_timer is None
        timer.join(timeout=1.0)  # cancelled timer thread exits promptly
        assert not timer.is_alive()


class TestTranscriptLogging:
    """MCC-38: transcript content must stay out of the logs by default."""

    def test_transcript_text_not_logged_by_default(self, caplog):
        app = _make_app(_speech(), _FakeTranscriber(text="my secret password"))
        with caplog.at_level("DEBUG", logger="verbal_code"):
            app._on_dictation_stop()
        assert not any("secret password" in r.message for r in caplog.records)
        assert any(
            r.message == "Transcribed 19 chars" for r in caplog.records
        )  # "My secret password " after processing

    def test_transcript_text_logged_when_opted_in(self, caplog):
        app = _make_app(_speech(), _FakeTranscriber(text="hello world"))
        app._log_transcripts = True
        with caplog.at_level("INFO", logger="verbal_code"):
            app._on_dictation_stop()
        assert any("Hello world" in r.message for r in caplog.records)

    def test_stream_text_not_logged_by_default(self, caplog):
        app = _make_app(_speech(), _FakeTranscriber())
        app.transcriber.transcribe_stream = lambda chunk: iter(["stream secret"])
        with caplog.at_level("DEBUG", logger="verbal_code"):
            app._emit_stream_text(np.zeros(160, dtype=np.float32))
        assert not any("stream secret" in r.message for r in caplog.records)
        assert any("13 chars" in r.message for r in caplog.records)

    def test_stream_text_logged_when_opted_in(self, caplog):
        app = _make_app(_speech(), _FakeTranscriber())
        app._log_transcripts = True
        app.transcriber.transcribe_stream = lambda chunk: iter(["stream words"])
        with caplog.at_level("DEBUG", logger="verbal_code"):
            app._emit_stream_text(np.zeros(160, dtype=np.float32))
        assert any("stream words" in r.message for r in caplog.records)


class TestDictationLatencyLogging:
    def test_successful_cycle_logs_latency(self, caplog):
        app = _make_app(_speech(), _FakeTranscriber(text="hello"))
        with caplog.at_level("INFO", logger="verbal_code"):
            app._on_dictation_stop()
        lines = [
            r.message for r in caplog.records if "dictation_latency_ms=" in r.message
        ]
        assert len(lines) == 1
        latency = int(lines[0].split("=")[1])
        assert 0 <= latency < 60_000

    def test_skipped_cycle_logs_no_latency(self, caplog):
        app = _make_app(_speech(seconds=0.1), _FakeTranscriber())
        with caplog.at_level("INFO", logger="verbal_code"):
            app._on_dictation_stop()
        assert not any("dictation_latency_ms=" in r.message for r in caplog.records)

    def test_failed_transcription_logs_no_latency(self, caplog):
        app = _make_app(_speech(), _FakeTranscriber(fail=True))
        with caplog.at_level("INFO", logger="verbal_code"):
            app._on_dictation_stop()
        assert not any("dictation_latency_ms=" in r.message for r in caplog.records)

    def test_failed_injection_logs_no_latency(self, caplog):
        app = _make_app(_speech(), _FakeTranscriber(text="hello"))

        def _boom(text):
            raise RuntimeError("no display")

        app.injector.inject = _boom
        with caplog.at_level("INFO", logger="verbal_code"):
            app._on_dictation_stop()
        assert not any("dictation_latency_ms=" in r.message for r in caplog.records)

    def test_live_cycle_logs_latency(self, caplog):
        transcriber = _FakeTranscriber(tail="last words")
        transcriber.supports_live_streaming = True
        app = _make_app(_speech(), transcriber, live=True)
        with caplog.at_level("INFO", logger="verbal_code"):
            app._on_dictation_stop()
        assert any("dictation_latency_ms=" in r.message for r in caplog.records)

    def test_live_cycle_with_empty_tail_still_logs(self, caplog):
        transcriber = _FakeTranscriber(tail="")
        transcriber.supports_live_streaming = True
        app = _make_app(_speech(), transcriber, live=True)
        with caplog.at_level("INFO", logger="verbal_code"):
            app._on_dictation_stop()
        assert any("dictation_latency_ms=" in r.message for r in caplog.records)
