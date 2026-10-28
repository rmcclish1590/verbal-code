import sys
import types

import numpy as np
import pytest

from verbal_code.transcriber import (
    AVAILABLE_MODELS,
    ParakeetTranscriber,
    SherpaOnnxTranscriber,
    TranscriberBase,
    VoskTranscriber,
    WhisperTranscriber,
    apply_selection,
    create_transcriber,
    current_selection,
    installed_engines,
    physical_core_count,
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

    def test_default_unload_is_a_no_op(self):
        self._Minimal().unload_model()


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

    def test_installed_engines_includes_core_engines_in_dev_env(self):
        # onnx-asr and sherpa-onnx are core dependencies (MCC-118).
        for engine in ("whisper", "parakeet", "sherpa"):
            assert engine in installed_engines()

    def test_available_models_cover_installed_engines(self):
        for engine in installed_engines():
            assert AVAILABLE_MODELS[engine]

    @pytest.mark.parametrize("engine", ["parakeet", "sherpa"])
    def test_new_engines_round_trip(self, engine):
        for model in AVAILABLE_MODELS[engine]:
            cfg: dict = {}
            apply_selection(cfg, engine, model)
            assert current_selection(cfg) == (engine, model)
            assert cfg["stt"][engine]["model"] == model

    @pytest.mark.parametrize("engine", list(AVAILABLE_MODELS))
    def test_default_model_is_first_listed(self, engine):
        cfg = {"stt": {"engine": engine}}
        assert current_selection(cfg) == (engine, AVAILABLE_MODELS[engine][0])


class TestCreateTranscriber:
    def test_parakeet_is_batch_only(self):
        t = create_transcriber(
            {"stt": {"engine": "parakeet", "parakeet": {"quantization": ""}}}
        )
        assert isinstance(t, ParakeetTranscriber)
        assert t.supports_live_streaming is False
        assert t.model_name == "nemo-parakeet-tdt-0.6b-v2"
        assert t.quantization is None

    def test_sherpa_streams_live(self):
        model = AVAILABLE_MODELS["sherpa"][1]
        t = create_transcriber(
            {
                "stt": {"engine": "sherpa", "sherpa": {"model": model}},
                "audio": {"sample_rate": 48000},
            }
        )
        assert isinstance(t, SherpaOnnxTranscriber)
        assert t.supports_live_streaming is True
        assert t.model_name == model
        assert t.sample_rate == 48000

    def test_existing_engines_unchanged(self):
        t = create_transcriber({"stt": {"engine": "vosk"}})
        assert isinstance(t, VoskTranscriber) and t.supports_live_streaming
        t = create_transcriber({"stt": {"whisper": {"model": "small.en"}}})
        assert isinstance(t, WhisperTranscriber)
        assert t.model_size == "small.en" and not t.supports_live_streaming


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


def _write_topology(root, cpu: int, package: int, core: int) -> None:
    topo = root / f"cpu{cpu}" / "topology"
    topo.mkdir(parents=True)
    (topo / "physical_package_id").write_text(f"{package}\n")
    (topo / "core_id").write_text(f"{core}\n")


class TestPhysicalCoreCount:
    def test_counts_smt_siblings_once(self, tmp_path):
        # 6 cores x 2 threads, like the Ryzen 5 5600G.
        for cpu in range(12):
            _write_topology(tmp_path, cpu, package=0, core=cpu % 6)
        assert physical_core_count(str(tmp_path)) == 6

    def test_falls_back_to_cpu_count_without_topology(self, tmp_path, monkeypatch):
        monkeypatch.setattr("os.cpu_count", lambda: 3)
        assert physical_core_count(str(tmp_path)) == 3


class _FakeParakeetModel:
    def __init__(self, text="Hello world."):
        self.text = text
        self.calls: list[int] = []  # sample count of each recognize() call

    def recognize(self, waveform, sample_rate=16000):
        assert waveform.dtype == np.float32
        assert sample_rate == 16000
        self.calls.append(len(waveform))
        return self.text


@pytest.fixture
def fake_onnx_asr(monkeypatch):
    """Stand-in onnx_asr module recording load_model() arguments."""
    module = types.SimpleNamespace(loads=[], model=_FakeParakeetModel())

    def load_model(name, **kwargs):
        module.loads.append((name, kwargs))
        return module.model

    module.load_model = load_model
    monkeypatch.setitem(sys.modules, "onnx_asr", module)
    return module


class TestParakeetTranscriber:
    def test_is_batch_only(self):
        assert ParakeetTranscriber.supports_live_streaming is False

    def test_load_model_configures_int8_cpu_threads(self, fake_onnx_asr):
        t = ParakeetTranscriber(cpu_threads=6)
        t.load_model()

        name, kwargs = fake_onnx_asr.loads[0]
        assert name == "nemo-parakeet-tdt-0.6b-v2"
        assert kwargs["quantization"] == "int8"
        assert kwargs["providers"] == ["CPUExecutionProvider"]
        assert kwargs["sess_options"].intra_op_num_threads == 6
        assert kwargs["sess_options"].inter_op_num_threads == 1

    def test_empty_quantization_loads_float_model(self, fake_onnx_asr):
        ParakeetTranscriber(quantization="", cpu_threads=2).load_model()
        assert fake_onnx_asr.loads[0][1]["quantization"] is None

    def test_cpu_threads_defaults_to_physical_cores(self, monkeypatch):
        monkeypatch.setattr(
            "verbal_code.transcriber.physical_core_count", lambda: 6
        )
        assert ParakeetTranscriber().cpu_threads == 6

    def test_empty_audio_returns_empty_without_inference(self, fake_onnx_asr):
        t = ParakeetTranscriber(cpu_threads=2)
        t.load_model()
        warmup_calls = len(fake_onnx_asr.model.calls)
        assert t.transcribe_batch(np.array([], dtype=np.float32)) == ""
        assert len(fake_onnx_asr.model.calls) == warmup_calls

    def test_short_clip_is_one_call(self, fake_onnx_asr):
        t = ParakeetTranscriber(cpu_threads=2)
        t.load_model()
        fake_onnx_asr.model.calls.clear()
        assert t.transcribe_batch(np.zeros(5 * 16000, dtype=np.float32)) == (
            "Hello world."
        )
        assert fake_onnx_asr.model.calls == [5 * 16000]

    def test_long_clip_is_chunked_and_joined(self, fake_onnx_asr):
        t = ParakeetTranscriber(cpu_threads=2)
        t.load_model()
        fake_onnx_asr.model.calls.clear()
        text = t.transcribe_batch(np.zeros(60 * 16000, dtype=np.float32))

        assert len(fake_onnx_asr.model.calls) == 3
        assert all(n <= 25 * 16000 for n in fake_onnx_asr.model.calls)
        assert sum(fake_onnx_asr.model.calls) == 60 * 16000
        assert text == "Hello world. Hello world. Hello world."

    def test_transcribe_loads_lazily(self, fake_onnx_asr):
        t = ParakeetTranscriber(cpu_threads=2)
        t.transcribe_batch(np.zeros(16000, dtype=np.float32))
        assert len(fake_onnx_asr.loads) == 1

    def test_unload_releases_model(self, fake_onnx_asr):
        t = ParakeetTranscriber(cpu_threads=2)
        t.load_model()
        t.unload_model()
        assert t._model is None
