import numpy as np

from verbal_code.audio import trim_silence

SAMPLE_RATE = 16000


def _tone(seconds: float, amplitude: float = 0.5) -> np.ndarray:
    t = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    return (amplitude * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def _silence(seconds: float, amplitude: float = 0.001) -> np.ndarray:
    rng = np.random.default_rng(0)
    n = int(SAMPLE_RATE * seconds)
    return (amplitude * rng.standard_normal(n)).astype(np.float32)


class TestTrimSilence:
    def test_trims_leading_and_trailing_silence(self):
        audio = np.concatenate([_silence(1.0), _tone(0.5), _silence(1.0)])
        trimmed = trim_silence(audio, SAMPLE_RATE)
        # Speech plus at most the padding on each side survives.
        assert len(trimmed) < len(audio)
        assert len(trimmed) >= int(SAMPLE_RATE * 0.5)
        assert np.max(np.abs(trimmed)) == np.max(np.abs(audio))

    def test_keeps_padding_around_speech(self):
        audio = np.concatenate([_silence(1.0), _tone(0.5), _silence(1.0)])
        trimmed = trim_silence(audio, SAMPLE_RATE, padding_ms=150)
        # 0.5s of tone + up to 150ms padding each side (+ frame rounding).
        assert len(trimmed) <= int(SAMPLE_RATE * (0.5 + 2 * 0.15)) + 2 * 480

    def test_all_speech_left_untouched(self):
        audio = _tone(1.0)
        trimmed = trim_silence(audio, SAMPLE_RATE)
        assert len(trimmed) == len(audio)

    def test_pure_silence_returns_empty(self):
        audio = _silence(2.0)
        trimmed = trim_silence(audio, SAMPLE_RATE)
        assert len(trimmed) == 0

    def test_audio_shorter_than_one_frame_unchanged(self):
        audio = _tone(0.001)  # 16 samples, below the 30ms frame
        trimmed = trim_silence(audio, SAMPLE_RATE)
        assert np.array_equal(trimmed, audio)

    def test_empty_input_unchanged(self):
        audio = np.array([], dtype=np.float32)
        trimmed = trim_silence(audio, SAMPLE_RATE)
        assert len(trimmed) == 0

    def test_threshold_is_configurable(self):
        quiet_speech = _tone(0.5, amplitude=0.005)  # ~-46 dBFS
        audio = np.concatenate([_silence(1.0, amplitude=0.0001), quiet_speech])
        assert len(trim_silence(audio, SAMPLE_RATE, threshold_db=-40.0)) == 0
        assert len(trim_silence(audio, SAMPLE_RATE, threshold_db=-50.0)) > 0


class _FakeStatus:
    def __bool__(self):
        return False


def _push(capture, samples):
    """Feed a chunk through the sounddevice callback path."""
    indata = samples.reshape(-1, 1)
    capture._callback(indata, len(samples), None, _FakeStatus())


def _make_capture():
    from verbal_code.audio import AudioCapture

    capture = AudioCapture()
    capture._running = True  # buffer logic only; no real stream
    return capture


class TestSingleBufferCapture:
    def test_chunks_stored_once_and_read_in_order(self):
        capture = _make_capture()
        first = np.ones(4, dtype=np.float32)
        second = np.full(4, 2, dtype=np.float32)
        _push(capture, first)
        _push(capture, second)

        assert np.array_equal(capture.get_chunk(timeout=0), first)
        assert np.array_equal(capture.get_chunk(timeout=0), second)
        assert len(capture._chunks) == 2  # still in place for the batch path

    def test_get_chunk_returns_none_when_drained(self):
        capture = _make_capture()
        _push(capture, np.ones(4, dtype=np.float32))
        capture.get_chunk(timeout=0)
        assert capture.get_chunk(timeout=0) is None

    def test_get_all_chunks_returns_only_unread(self):
        capture = _make_capture()
        for value in (1, 2, 3):
            _push(capture, np.full(4, value, dtype=np.float32))
        capture.get_chunk(timeout=0)  # consume the first

        remaining = capture.get_all_chunks()
        assert [chunk[0] for chunk in remaining] == [2, 3]
        assert capture.get_all_chunks() == []

    def test_reading_does_not_affect_full_session_audio(self):
        capture = _make_capture()
        for value in (1, 2):
            _push(capture, np.full(4, value, dtype=np.float32))
        capture.get_chunk(timeout=0)
        capture.get_all_chunks()

        with capture._chunk_ready:
            session = np.concatenate(capture._chunks)
        assert len(session) == 8  # both chunks intact for batch transcription

    def test_get_chunk_wakes_on_new_chunk(self):
        import threading

        capture = _make_capture()
        result = []

        def reader():
            result.append(capture.get_chunk(timeout=2.0))

        thread = threading.Thread(target=reader)
        thread.start()
        _push(capture, np.full(4, 7, dtype=np.float32))
        thread.join(timeout=3.0)
        assert not thread.is_alive()
        assert result and result[0] is not None and result[0][0] == 7
