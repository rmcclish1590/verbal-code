import numpy as np

from verbal_code.transcriber import WhisperTranscriber


class _FakeSegment:
    def __init__(self, text: str):
        self.text = text


class _FakeModel:
    """Counts transcribe() calls so tests can assert inference frequency."""

    def __init__(self):
        self.calls = 0

    def transcribe(self, audio, **kwargs):
        self.calls += 1
        return [_FakeSegment(f"text after {self.calls} calls")], None


def _make_transcriber() -> WhisperTranscriber:
    t = WhisperTranscriber(sample_rate=16000)
    t._model = _FakeModel()
    return t


_HALF_SECOND = np.zeros(8000, dtype=np.float32)  # 0.5s at 16 kHz


class TestStreamGating:
    def test_no_inference_before_first_interval(self):
        t = _make_transcriber()
        list(t.transcribe_stream(_HALF_SECOND))
        list(t.transcribe_stream(_HALF_SECOND))
        assert t._model.calls == 0

    def test_inference_once_per_interval_not_per_chunk(self):
        t = _make_transcriber()
        for _ in range(3):  # 1.5s accumulated -> first inference
            list(t.transcribe_stream(_HALF_SECOND))
        assert t._model.calls == 1
        for _ in range(2):  # only 1.0s of new audio -> no inference yet
            list(t.transcribe_stream(_HALF_SECOND))
        assert t._model.calls == 1
        list(t.transcribe_stream(_HALF_SECOND))  # 1.5s of new audio -> second
        assert t._model.calls == 2

    def test_reset_restarts_gating(self):
        t = _make_transcriber()
        for _ in range(3):
            list(t.transcribe_stream(_HALF_SECOND))
        assert t._model.calls == 1
        t.reset()
        list(t.transcribe_stream(_HALF_SECOND))
        assert t._model.calls == 1
