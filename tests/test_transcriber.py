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

    @pytest.mark.parametrize("engine", ["parakeet", "sherpa", "whisper"])
    def test_cpu_threads_reaches_engine(self, engine):
        t = create_transcriber({"stt": {"engine": engine, "cpu_threads": 3}})
        assert t.cpu_threads == 3

    @pytest.mark.parametrize("engine", ["parakeet", "sherpa", "whisper"])
    def test_cpu_threads_unset_uses_physical_cores(self, engine, monkeypatch):
        monkeypatch.setattr(
            "verbal_code.transcriber.physical_core_count", lambda: 6
        )
        assert create_transcriber({"stt": {"engine": engine}}).cpu_threads == 6

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
        self.sample_rates: list[int] = []

    def recognize(self, waveform, sample_rate=16000):
        assert waveform.dtype == np.float32
        self.calls.append(len(waveform))
        self.sample_rates.append(sample_rate)
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

    def test_capture_rate_is_passed_for_resampling(self, fake_onnx_asr):
        # onnx-asr resamples from the rate it is told; claiming 16 kHz for
        # 48 kHz capture would garble the audio (MCC-124).
        t = ParakeetTranscriber(cpu_threads=2, sample_rate=48000)
        t.load_model()
        t.transcribe_batch(np.zeros(48000, dtype=np.float32))
        assert set(fake_onnx_asr.model.sample_rates) == {48000}

    def test_transcribe_loads_lazily(self, fake_onnx_asr):
        t = ParakeetTranscriber(cpu_threads=2)
        t.transcribe_batch(np.zeros(16000, dtype=np.float32))
        assert len(fake_onnx_asr.loads) == 1

    def test_unload_releases_model(self, fake_onnx_asr):
        t = ParakeetTranscriber(cpu_threads=2)
        t.load_model()
        t.unload_model()
        assert t._model is None

    def test_110m_model_loads_from_its_hugging_face_repo(self, fake_onnx_asr):
        # onnx-asr has no alias for the 110M model (MCC-130).
        ParakeetTranscriber("nemo-parakeet-tdt_ctc-110m", cpu_threads=2).load_model()
        assert fake_onnx_asr.loads[0][0] == (
            "OpenVoiceOS/nvidia-parakeet-tdt_ctc-110m-onnx"
        )


@pytest.fixture
def fake_resolver(monkeypatch):
    """Stand-in onnx_asr.loader whose resolver records calls and can report
    files as missing from the local cache."""
    loader = types.SimpleNamespace(calls=[], cached=True)

    class Resolver:
        def __init__(self, model, offline):
            self.model, self.offline = model, offline

        def resolve_model(self, *, quantization):
            loader.calls.append((self.model, self.offline, quantization))
            if self.offline and not loader.cached:
                raise FileNotFoundError("encoder-model.int8.onnx")
            return {}

    loader.create_asr_resolver = lambda model, offline=None: Resolver(model, offline)
    monkeypatch.setitem(sys.modules, "onnx_asr", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "onnx_asr.loader", loader)
    return loader


class TestParakeetDownload:
    """install.sh pre-downloads the model via these (MCC-130)."""

    def test_cached_model_is_reported_downloaded_offline(self, fake_resolver):
        assert ParakeetTranscriber(cpu_threads=2).is_model_downloaded() is True
        assert fake_resolver.calls == [("nemo-parakeet-tdt-0.6b-v2", True, "int8")]

    def test_missing_files_mean_not_downloaded(self, fake_resolver):
        fake_resolver.cached = False
        assert ParakeetTranscriber(cpu_threads=2).is_model_downloaded() is False

    def test_download_fetches_only_the_selected_quantization(self, fake_resolver):
        ParakeetTranscriber(
            "nemo-parakeet-tdt_ctc-110m", quantization="", cpu_threads=2
        ).download_model()
        assert fake_resolver.calls == [
            ("OpenVoiceOS/nvidia-parakeet-tdt_ctc-110m-onnx", None, None)
        ]


class TestDefaultDownload:
    def test_loads_then_releases_the_model(self):
        events = []

        class Engine(TranscriberBase):
            def load_model(self):
                events.append("load")

            def unload_model(self):
                events.append("unload")

            def transcribe_batch(self, audio):
                return ""

            def reset(self):
                pass

        engine = Engine()
        assert engine.is_model_downloaded() is False
        engine.download_model()
        assert events == ["load", "unload"]


class TestWhisperThreads:
    @pytest.fixture
    def fake_faster_whisper(self, monkeypatch):
        module = types.SimpleNamespace(constructed=[])

        class WhisperModel:
            def __init__(self, model_size, **kwargs):
                module.constructed.append((model_size, kwargs))

        class BatchedInferencePipeline:
            def __init__(self, model):
                self.model = model

            def transcribe(self, audio, **kwargs):
                return [], None

        module.WhisperModel = WhisperModel
        module.BatchedInferencePipeline = BatchedInferencePipeline
        monkeypatch.setitem(sys.modules, "faster_whisper", module)
        # No GPU, no install marker: the CPU path, independent of the host.
        monkeypatch.setattr("verbal_code.transcriber.cuda_device_count",
                            lambda: (0, ""))
        monkeypatch.setattr("verbal_code.transcriber._replaced_rocm_reason",
                            lambda: None)
        return module

    def test_load_model_passes_cpu_threads(self, fake_faster_whisper):
        WhisperTranscriber(cpu_threads=6).load_model()
        model_size, kwargs = fake_faster_whisper.constructed[0]
        assert model_size == "distil-small.en"
        assert kwargs["cpu_threads"] == 6

    def test_cpu_threads_defaults_to_physical_cores(self, monkeypatch):
        monkeypatch.setattr(
            "verbal_code.transcriber.physical_core_count", lambda: 6
        )
        assert WhisperTranscriber().cpu_threads == 6

    def test_menu_models_are_known_to_faster_whisper(self):
        from faster_whisper import available_models

        assert {"distil-medium.en", "distil-large-v3.5"} <= set(
            AVAILABLE_MODELS["whisper"]
        )
        assert set(AVAILABLE_MODELS["whisper"]) <= set(available_models())


# The MCC-42 contract in one table: only engines whose streamed text is final
# may claim live streaming, since the app injects that text as it arrives.
_LIVE_STREAMING_CONTRACT = {
    "parakeet": False,
    "sherpa": True,
    "whisper": False,
    "moonshine": False,
    "vosk": True,
}


class TestEngineContract:
    def test_every_engine_has_a_declared_contract(self):
        assert set(_LIVE_STREAMING_CONTRACT) == set(AVAILABLE_MODELS)

    @pytest.mark.parametrize("engine", list(_LIVE_STREAMING_CONTRACT))
    def test_live_streaming_flag(self, engine):
        t = create_transcriber({"stt": {"engine": engine}})
        assert isinstance(t, TranscriberBase)
        assert t.supports_live_streaming is _LIVE_STREAMING_CONTRACT[engine]

    @pytest.mark.parametrize("engine", list(_LIVE_STREAMING_CONTRACT))
    def test_every_engine_can_unload(self, engine):
        # Constructed but never loaded: unloading must still be safe, since
        # a model switch may unload a transcriber whatever its state.
        create_transcriber({"stt": {"engine": engine}}).unload_model()


class _GpuFakeWhisper:
    """A faster_whisper stand-in whose GPU path can be made to fail."""

    def __init__(self):
        self.constructed: list[tuple[str, dict]] = []
        self.fail_construct_on_cuda = False
        self.fail_warmup_on_cuda = False
        self.fail_transcribe_on_cuda = False
        fake = self

        class WhisperModel:
            def __init__(self, model_size, **kwargs):
                fake.constructed.append((model_size, kwargs))
                self.device = kwargs["device"]
                if self.device == "cuda" and fake.fail_construct_on_cuda:
                    raise RuntimeError("HIP error: out of memory\nmore detail")

        class BatchedInferencePipeline:
            def __init__(self, model):
                self.model = model

            def transcribe(self, audio, **kwargs):
                on_cuda = self.model.device == "cuda"
                warmup = kwargs.get("beam_size") == 1
                if on_cuda and warmup and fake.fail_warmup_on_cuda:
                    raise RuntimeError("hipErrorNoBinaryForGpu")
                if on_cuda and not warmup and fake.fail_transcribe_on_cuda:
                    raise RuntimeError("HIP error: an illegal memory access")
                info = types.SimpleNamespace(language="en", language_probability=1.0)
                return [_FakeSegment(f"heard on {self.model.device}")], info

        self.module = types.SimpleNamespace(
            WhisperModel=WhisperModel, BatchedInferencePipeline=BatchedInferencePipeline
        )

    def devices(self) -> list[str]:
        return [kwargs["device"] for _, kwargs in self.constructed]


@pytest.fixture
def gpu_whisper(monkeypatch):
    fake = _GpuFakeWhisper()
    monkeypatch.setitem(sys.modules, "faster_whisper", fake.module)
    monkeypatch.setattr("verbal_code.transcriber.cuda_device_count", lambda: (1, ""))
    monkeypatch.setattr("verbal_code.transcriber._replaced_rocm_reason",
                        lambda: None)
    monkeypatch.setattr(WhisperTranscriber, "_gpu_label",
                        lambda self: f"rocm, gfx1200, idx {self.device_index}")
    fake.vram = {"total": 16 * 1024**3, "used": 1024**3}
    _fake_detect(monkeypatch, fake.vram)
    return fake


def _fake_detect(monkeypatch, vram):
    """gpu.detect() answering with one RX 9060 XT at index 0 (and 1)."""
    from verbal_code import gpu

    def detect(**kwargs):
        devices = [
            gpu.GpuDevice(vendor="amd", name="RX 9060 XT", pci_id="1002:7590",
                          target="gfx1200", vram_total=vram["total"],
                          vram_used=vram["used"], index=i, supported=True)
            for i in (0, 1)
        ]
        return gpu.GpuReport("amd", devices, True, "ok", "rocm", chosen=devices[0])
    monkeypatch.setattr(gpu, "detect", detect)


def _warnings(caplog):
    return [r for r in caplog.records if r.levelname in ("WARNING", "ERROR")]


class TestWhisperGpu:
    def test_auto_uses_the_gpu_with_float16(self, gpu_whisper, caplog):
        t = WhisperTranscriber(cpu_threads=6)
        with caplog.at_level("INFO"):
            t.load_model()
        assert (t.device, t.compute_type) == ("cuda", "float16")
        assert gpu_whisper.constructed[0][1]["compute_type"] == "float16"
        assert t.fallback_reason is None
        assert ("Whisper: model=distil-small.en device=cuda(rocm, gfx1200, idx 0) "
                "compute_type=float16") in caplog.text

    def test_gpu_construct_failure_falls_back_to_cpu_int8(self, gpu_whisper, caplog):
        gpu_whisper.fail_construct_on_cuda = True
        t = WhisperTranscriber(cpu_threads=6)
        with caplog.at_level("INFO"):
            t.load_model()
        assert gpu_whisper.devices() == ["cuda", "cpu"]
        assert gpu_whisper.constructed[1][1]["compute_type"] == "int8"
        assert (t.device, t.compute_type) == ("cpu", "int8")
        assert t.fallback_reason == (
            "GPU load failed (RuntimeError: HIP error: out of memory)"
        )
        warnings = _warnings(caplog)
        assert len(warnings) == 1 and warnings[0].levelname == "WARNING"
        assert "falling back to CPU int8" in warnings[0].getMessage()
        assert "verbal-code --doctor" in warnings[0].getMessage()
        assert not t.fallback_notify  # auto: logged, no tray notification

    def test_warmup_failure_on_gpu_falls_back(self, gpu_whisper):
        gpu_whisper.fail_warmup_on_cuda = True
        t = WhisperTranscriber()
        t.load_model()
        assert gpu_whisper.devices() == ["cuda", "cpu"]
        assert t.device == "cpu"
        assert "hipErrorNoBinaryForGpu" in t.fallback_reason

    def test_explicit_cuda_fallback_is_an_error_and_notifies(self, gpu_whisper,
                                                             caplog):
        gpu_whisper.fail_construct_on_cuda = True
        t = WhisperTranscriber(device="cuda")
        with caplog.at_level("INFO"):
            t.load_model()
        assert t.device == "cpu"
        assert [r.levelname for r in _warnings(caplog)] == ["ERROR"]
        assert t.fallback_notify

    def test_no_gpu_under_auto_is_info_only(self, gpu_whisper, monkeypatch, caplog):
        monkeypatch.setattr("verbal_code.transcriber.cuda_device_count",
                            lambda: (0, ""))
        t = WhisperTranscriber()
        with caplog.at_level("INFO"):
            t.load_model()
        assert gpu_whisper.devices() == ["cpu"]
        assert (t.device, t.compute_type) == ("cpu", "int8")
        assert _warnings(caplog) == []
        assert not t.fallback_notify

    def test_explicit_int8_is_respected_on_gpu(self, gpu_whisper):
        t = WhisperTranscriber(compute_type="int8")
        t.load_model()
        assert (t.device, t.compute_type) == ("cuda", "int8")

    def test_gpu_only_compute_type_becomes_int8_on_fallback(self, gpu_whisper):
        gpu_whisper.fail_construct_on_cuda = True
        t = WhisperTranscriber(compute_type="float16")
        t.load_model()
        assert (t.device, t.compute_type) == ("cpu", "int8")

    def test_cpu_valid_compute_type_survives_fallback(self, gpu_whisper):
        gpu_whisper.fail_construct_on_cuda = True
        t = WhisperTranscriber(compute_type="float32")
        t.load_model()
        assert (t.device, t.compute_type) == ("cpu", "float32")

    def test_device_cpu_never_touches_the_gpu(self, gpu_whisper, monkeypatch):
        monkeypatch.setattr("verbal_code.transcriber.cuda_device_count",
                            lambda: pytest.fail("probed the GPU"))
        t = WhisperTranscriber(device="cpu")
        t.load_model()
        assert gpu_whisper.devices() == ["cpu"]
        assert t.fallback_reason is None

    def test_device_index_is_passed_through(self, gpu_whisper, monkeypatch):
        monkeypatch.setattr("verbal_code.transcriber.cuda_device_count",
                            lambda: (2, ""))
        t = WhisperTranscriber(device_index=1)
        t.load_model()
        assert gpu_whisper.constructed[0][1]["device_index"] == 1
        assert t.device == "cuda"

    def test_device_index_beyond_the_visible_gpus_uses_cpu(self, gpu_whisper):
        t = WhisperTranscriber(device_index=3)
        t.load_model()
        assert t.device == "cpu"
        assert "device_index is 3" in t.fallback_reason

    def test_mid_session_gpu_failure_retries_on_cpu(self, gpu_whisper, caplog):
        gpu_whisper.fail_transcribe_on_cuda = True
        t = WhisperTranscriber()
        t.load_model()
        assert t.device == "cuda"
        audio = np.zeros(16000, dtype=np.float32)
        with caplog.at_level("INFO"):
            assert t.transcribe_batch(audio) == "heard on cpu"
        assert t.device == "cpu" and t.fallback_notify
        assert len(_warnings(caplog)) == 1
        # The rest of the session stays on CPU.
        assert t.transcribe_batch(audio) == "heard on cpu"
        assert gpu_whisper.devices() == ["cuda", "cpu"]

    def test_cpu_failure_is_not_retried(self, gpu_whisper, monkeypatch):
        monkeypatch.setattr("verbal_code.transcriber.cuda_device_count",
                            lambda: (0, ""))
        t = WhisperTranscriber()
        t.load_model()
        t._batched = types.SimpleNamespace(
            transcribe=lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))
        )
        with pytest.raises(RuntimeError, match="boom"):
            t.transcribe_batch(np.zeros(16000, dtype=np.float32))

    def test_config_defaults_for_missing_keys(self):
        t = create_transcriber({"stt": {"engine": "whisper"}})
        assert (t.requested_device, t.requested_compute_type, t.device_index) == (
            "auto", "auto", 0
        )


def test_pip_replaced_rocm_wheel_warns_once(monkeypatch, caplog):
    """R4.17: marker rocm, PyPI build installed, no device: CPU and one
    WARNING pointing at --doctor --fix. Uses the real check."""
    from verbal_code import gpu

    fake = _GpuFakeWhisper()
    monkeypatch.setitem(sys.modules, "faster_whisper", fake.module)
    monkeypatch.setattr("verbal_code.transcriber.cuda_device_count", lambda: (0, ""))
    monkeypatch.setattr(gpu, "read_marker", lambda: "rocm")
    monkeypatch.setattr(gpu, "installed_ct2_flavor", lambda: ("pypi", "4.9.1"))
    t = WhisperTranscriber()
    with caplog.at_level("INFO"):
        t.load_model()
    warnings = _warnings(caplog)
    assert len(warnings) == 1
    assert "replaced by a pip upgrade" in warnings[0].getMessage()
    assert "--doctor --fix" in warnings[0].getMessage()
    assert t.device == "cpu"


class TestVramPrecheck:
    """MCC-198: a GPU whose memory another app holds is skipped up front."""

    def test_low_free_vram_warns_and_uses_cpu(self, gpu_whisper, caplog):
        gpu_whisper.vram["used"] = 16 * 1024**3 - 200 * 1024**2  # 200 MiB free
        t = WhisperTranscriber()
        with caplog.at_level("INFO"):
            t.load_model()
        assert gpu_whisper.devices() == ["cpu"]  # the GPU load isn't attempted
        assert t.device == "cpu"
        warnings = _warnings(caplog)
        assert len(warnings) == 1 and warnings[0].levelname == "WARNING"
        message = warnings[0].getMessage()
        assert "200 MiB free" in message and "Ollama" in message
        assert "ollama stop" in message and "OLLAMA_KEEP_ALIVE" in message

    def test_unreadable_vram_never_blocks_the_gpu(self, gpu_whisper):
        gpu_whisper.vram.update(total=None, used=None)
        t = WhisperTranscriber()
        t.load_model()
        assert t.device == "cuda"

    def test_enough_vram_loads_on_gpu(self, gpu_whisper):
        t = WhisperTranscriber(model_size="large-v3-turbo")
        t.load_model()
        assert t.device == "cuda"

    def test_estimates_scale_with_model_and_precision(self):
        from verbal_code.transcriber import whisper_vram_estimate

        small = whisper_vram_estimate("distil-small.en", "float16")
        assert whisper_vram_estimate("large-v3-turbo", "float16") > small
        assert whisper_vram_estimate("distil-small.en", "int8") < small
        assert 0.5 * 1024**3 < small < 1024**3
