import numpy as np

from verbal_code.transcriber import (
    AVAILABLE_MODELS,
    TranscriberBase,
    VoskTranscriber,
    WhisperTranscriber,
    apply_selection,
    current_selection,
    installed_engines,
)


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


class _FakeKaldiRecognizer:
    """Finalises an utterance every ``finalize_every`` chunks."""

    def __init__(self, finalize_every: int = 2):
        self.finalize_every = finalize_every
        self.chunks = 0
        self.utterances = 0
        self.final_flushed = False

    def AcceptWaveform(self, pcm: bytes) -> bool:
        self.chunks += 1
        return self.chunks % self.finalize_every == 0

    def Result(self) -> str:
        self.utterances += 1
        return f'{{"text": "utterance {self.utterances}"}}'

    def FinalResult(self) -> str:
        self.final_flushed = True
        return '{"text": "trailing words"}'

    def SetWords(self, value: bool) -> None:
        pass


def _make_vosk() -> VoskTranscriber:
    t = VoskTranscriber()
    t._model = object()  # sentinel: skips load_model()
    t._recognizer = _FakeKaldiRecognizer()
    t._new_recognizer = lambda: None  # replaced recognizer needs no vosk import
    return t


class TestVoskStreaming:
    def test_declares_live_streaming_support(self):
        assert VoskTranscriber.supports_live_streaming is True
        assert WhisperTranscriber.supports_live_streaming is False

    def test_yields_only_finalised_utterances(self):
        t = _make_vosk()
        chunk = np.zeros(1024, dtype=np.float32)
        texts = [text for _ in range(4) for text in t.transcribe_stream(chunk)]
        assert texts == ["utterance 1", "utterance 2"]

    def test_stream_finalize_flushes_open_utterance(self):
        t = _make_vosk()
        assert t.stream_finalize() == "trailing words"
        assert t._recognizer.final_flushed

    def test_stream_finalize_without_model_returns_empty(self):
        t = VoskTranscriber()
        assert t.stream_finalize() == ""


class TestTranscriberBaseStreamingDefaults:
    class _Minimal(TranscriberBase):
        def load_model(self):
            pass

        def transcribe_batch(self, audio):
            return ""

        def reset(self):
            pass

    def test_default_stream_yields_nothing(self):
        t = self._Minimal()
        assert list(t.transcribe_stream(np.zeros(10, dtype=np.float32))) == []

    def test_default_finalize_is_empty(self):
        t = self._Minimal()
        assert t.stream_finalize() == ""
        assert TranscriberBase.supports_live_streaming is False


class TestModelSelectionHelpers:
    def test_current_selection_defaults(self):
        assert current_selection({}) == ("whisper", "distil-small.en")

    def test_current_selection_per_engine(self):
        cfg = {
            "stt": {
                "engine": "vosk",
                "vosk": {"model_name": "vosk-model-small-en-us-0.15"},
            }
        }
        assert current_selection(cfg) == ("vosk", "vosk-model-small-en-us-0.15")
        cfg = {"stt": {"engine": "moonshine", "moonshine": {"model": "moonshine/tiny"}}}
        assert current_selection(cfg) == ("moonshine", "moonshine/tiny")

    def test_apply_selection_round_trips(self):
        cfg: dict = {}
        apply_selection(cfg, "whisper", "small.en")
        assert current_selection(cfg) == ("whisper", "small.en")
        apply_selection(cfg, "moonshine", "moonshine/base")
        assert current_selection(cfg) == ("moonshine", "moonshine/base")

    def test_apply_selection_preserves_other_settings(self):
        cfg = {"stt": {"whisper": {"beam_size": 3}}}
        apply_selection(cfg, "whisper", "base.en")
        assert cfg["stt"]["whisper"]["beam_size"] == 3
        assert cfg["stt"]["whisper"]["model"] == "base.en"

    def test_installed_engines_includes_whisper_in_dev_env(self):
        assert "whisper" in installed_engines()

    def test_available_models_cover_installed_engines(self):
        for engine in ("whisper", "moonshine", "vosk"):
            assert AVAILABLE_MODELS[engine]


class TestWhisperStreamDelta:
    def test_delta_is_suffix_when_text_extends(self):
        t = _make_transcriber()
        t._last_stream_text = "hello world"
        assert t._extract_delta("hello world how are you") == "how are you"

    def test_revision_returns_full_text(self):
        # Whisper revised an earlier word: no common prefix, so the full
        # corrected text is returned (callers must not blind-append).
        t = _make_transcriber()
        t._last_stream_text = "hello wold"
        assert t._extract_delta("hello world how") == "hello world how"

    def test_first_delta_is_entire_text(self):
        t = _make_transcriber()
        assert t._extract_delta("hello") == "hello"
