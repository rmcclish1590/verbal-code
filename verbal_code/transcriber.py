import gc
import glob
import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Generator
from typing import Any

import numpy as np

logger = logging.getLogger("verbal_code")

_DEFAULT_SAMPLE_RATE = 16000
_STREAM_INTERVAL_SECONDS = 1.5
_VOSK_PCM_CHUNK_SIZE = 4000
# Moonshine accepts 0.1s–64s per call; split long recordings into 30s windows.
_MOONSHINE_CHUNK_SECONDS = 30
_MOONSHINE_MIN_SECONDS = 0.1
# Parakeet's FastConformer attention is tuned for segments up to ~25-30s;
# longer recordings are cut at quiet points into windows of at most this.
_PARAKEET_CHUNK_SECONDS = 25
_PARAKEET_MIN_SECONDS = 0.1
# Silence appended before input_finished() so the transducer emits the
# trailing tokens still inside its lookahead window when the stream ends.
# Measured on the Kroko Zipformer: 0.6s (sherpa's usual example value)
# dropped the last words of an utterance that followed a mid-stream endpoint
# reset; 1.5s was the shortest padding that never did.
_SHERPA_TAIL_PADDING_SECONDS = 1.5
_PCM_MAX_AMPLITUDE = 32767
_PCM_MIN_AMPLITUDE = -32768
_SYSFS_CPU_ROOT = "/sys/devices/system/cpu"


def physical_core_count(sysfs_root: str = _SYSFS_CPU_ROOT) -> int:
    """Return the number of physical CPU cores, ignoring SMT siblings.

    ONNX Runtime and CTranslate2 inference saturates a core per thread, so
    running one thread per *physical* core is the sweet spot; SMT siblings
    share execution units and add contention rather than throughput.
    ``os.cpu_count()`` reports logical CPUs (12 on a 6-core Ryzen 5 5600G),
    so cores are counted from the sysfs topology instead, falling back to
    ``os.cpu_count()`` where that isn't readable.
    """
    cores: set[tuple[str, str]] = set()
    for topology in glob.glob(os.path.join(sysfs_root, "cpu[0-9]*", "topology")):
        try:
            with open(os.path.join(topology, "physical_package_id")) as f:
                package = f.read().strip()
            with open(os.path.join(topology, "core_id")) as f:
                core = f.read().strip()
        except OSError:
            continue
        cores.add((package, core))
    return len(cores) or os.cpu_count() or 4


class TranscriberBase(ABC):
    """Abstract interface for speech-to-text backends."""

    #: True when :meth:`transcribe_stream` yields only *final* text that the
    #: engine will never revise, making it safe to inject as it arrives.
    #: Engines whose partials are revisable (Whisper re-decodes the whole
    #: buffer each interval) must leave this False.
    supports_live_streaming: bool = False

    @abstractmethod
    def load_model(self) -> None:
        """Load the model into memory.  May take several seconds on first call."""
        ...

    @abstractmethod
    def transcribe_batch(self, audio: np.ndarray) -> str:
        """Transcribe a complete float32 audio array and return the text."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset any internal state between dictation sessions."""
        ...

    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str, None, None]:
        """Accumulate ``chunk`` and yield incremental text when available.

        The default implementation yields nothing; engines without streaming
        support fall back to batch transcription on hotkey release.
        """
        return
        yield  # unreachable — turns this method into a generator

    def stream_finalize(self) -> str:
        """Return text for audio still buffered when the stream ends."""
        return ""

    def unload_model(self) -> None:
        """Release the loaded model so its memory can be reclaimed.

        The default does nothing; engines that hold a model override it.
        """
        return


class WhisperTranscriber(TranscriberBase):
    """faster-whisper backed transcriber for push-to-talk dictation.

    Each dictation is transcribed in a single pass on release via
    :class:`~faster_whisper.BatchedInferencePipeline`, which segments the audio
    with Silero VAD and decodes the segments in parallel batches.  This is
    several times faster than a plain sequential ``transcribe`` on multi-segment
    audio and removes the need for a separate live-streaming pass.
    """

    def __init__(
        self,
        model_size: str = "distil-small.en",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "en",
        beam_size: int = 2,
        batch_size: int = 8,
        initial_prompt: str = "",
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        cpu_threads: int | None = None,
    ):
        self.model_size = model_size
        self.device = device
        # CTranslate2 defaults to 4 threads; one per physical core is faster
        # on anything bigger (6 on a Ryzen 5 5600G).
        self.cpu_threads = cpu_threads or physical_core_count()
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.batch_size = batch_size
        # faster-whisper expects None (not "") when there is no prompt.
        self.initial_prompt = initial_prompt or None
        self.sample_rate = sample_rate
        self._model: Any = None
        self._batched: Any = None
        self._lock = threading.Lock()
        self._stream_buffer: list[np.ndarray] = []
        self._stream_samples: int = 0
        self._last_transcribed_samples: int = 0
        self._last_stream_text: str = ""
        self._stream_interval_samples = int(_STREAM_INTERVAL_SECONDS * sample_rate)

    def load_model(self) -> None:
        """Download (if needed) and load the Whisper model, then warm it up."""
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        logger.info(
            "Loading Whisper model '%s' (device=%s, compute_type=%s, threads=%d)...",
            self.model_size,
            self.device,
            self.compute_type,
            self.cpu_threads,
        )
        t0 = time.monotonic()
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
            cpu_threads=self.cpu_threads,
        )
        self._batched = BatchedInferencePipeline(model=self._model)
        logger.info("Whisper model loaded in %.2fs", time.monotonic() - t0)
        self._warmup()

    def _warmup(self) -> None:
        """Run one throwaway inference so the first dictation isn't penalised by
        lazy init."""
        try:
            silence = np.zeros(self.sample_rate, dtype=np.float32)
            with self._lock:
                segments, _ = self._batched.transcribe(
                    silence,
                    language=self.language,
                    beam_size=1,
                    batch_size=self.batch_size,
                    vad_filter=True,
                )
                for _ in segments:  # segments are lazy; drain to force the work
                    pass
            logger.info("Whisper warmup complete")
        except Exception as exc:  # noqa: BLE001 — warmup is best-effort
            logger.debug("Warmup skipped: %s", exc)

    def transcribe_batch(self, audio: np.ndarray) -> str:
        """Run full-utterance transcription and return the joined text."""
        if self._model is None:
            self.load_model()

        duration = len(audio) / self.sample_rate
        logger.info("Transcribing %.2fs of audio...", duration)

        t0 = time.monotonic()
        with self._lock:
            segments, info = self._batched.transcribe(
                audio,
                language=self.language,
                beam_size=self.beam_size,
                batch_size=self.batch_size,
                # Short dictations have no coherent prior context; conditioning on
                # it is the main cause of Whisper repetition/hallucination loops.
                condition_on_previous_text=False,
                initial_prompt=self.initial_prompt,
                vad_filter=True,
            )
            text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())

        logger.info(
            "Transcription done in %.2fs (language=%s, prob=%.2f)",
            time.monotonic() - t0,
            info.language,
            info.language_probability,
        )
        return text

    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str, None, None]:
        """Accumulate ``chunk`` and yield a text delta when the buffer is large
        enough."""
        if self._model is None:
            self.load_model()

        self._stream_buffer.append(chunk)
        self._stream_samples += len(chunk)

        # Run inference at most once per interval of *new* audio; otherwise every
        # chunk after the first interval would re-transcribe the whole session.
        new_samples = self._stream_samples - self._last_transcribed_samples
        if new_samples < self._stream_interval_samples:
            return
        self._last_transcribed_samples = self._stream_samples

        audio = np.concatenate(self._stream_buffer)
        stream_beam = max(1, self.beam_size // 2)

        with self._lock:
            segments, _ = self._model.transcribe(
                audio,
                language=self.language,
                beam_size=stream_beam,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 300},
            )
            full_text = " ".join(
                seg.text.strip() for seg in segments if seg.text.strip()
            )

        if full_text and full_text != self._last_stream_text:
            delta = self._extract_delta(full_text)
            self._last_stream_text = full_text
            if delta:
                yield delta

    def _extract_delta(self, full_text: str) -> str:
        """Return the portion of ``full_text`` that follows the last emitted text."""
        if full_text.startswith(self._last_stream_text):
            return full_text[len(self._last_stream_text) :].strip()
        return full_text

    def reset(self) -> None:
        """Clear the streaming buffer for the next dictation session."""
        self._stream_buffer = []
        self._stream_samples = 0
        self._last_transcribed_samples = 0
        self._last_stream_text = ""


class VoskTranscriber(TranscriberBase):
    """Vosk-backed transcriber.  Lightweight; works offline without a GPU.

    Vosk's streaming recognizer finalises an utterance whenever it detects a
    pause; finalised text is never revised afterwards, so it can be injected
    live as each utterance completes.
    """

    supports_live_streaming = True

    def __init__(
        self,
        model_name: str = "vosk-model-small-en-us-0.15",
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
    ):
        self.model_name = model_name
        self.sample_rate = sample_rate
        self._model: Any = None
        self._recognizer: Any = None
        self._lock = threading.Lock()

    @staticmethod
    def _to_pcm(audio: np.ndarray) -> bytes:
        """Convert float32 audio to 16-bit PCM bytes expected by Vosk."""
        return (
            np.clip(audio * _PCM_MAX_AMPLITUDE, _PCM_MIN_AMPLITUDE, _PCM_MAX_AMPLITUDE)
            .astype(np.int16)
            .tobytes()
        )

    def load_model(self) -> None:
        """Load the Vosk model, downloading it first if not cached locally."""
        import vosk

        vosk.SetLogLevel(-1)

        model_dir = os.path.join(
            os.path.expanduser("~/.cache/verbal-code/models"), self.model_name
        )
        logger.info("Loading Vosk model '%s'...", self.model_name)
        t0 = time.monotonic()

        if os.path.isdir(model_dir):
            self._model = vosk.Model(model_path=model_dir)
        else:
            os.makedirs(os.path.dirname(model_dir), exist_ok=True)
            logger.info("Model not found locally, downloading...")
            self._model = vosk.Model(model_name=self.model_name)

        logger.info("Vosk model loaded in %.2fs", time.monotonic() - t0)
        self._new_recognizer()

    def _new_recognizer(self) -> None:
        import vosk

        self._recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate)
        self._recognizer.SetWords(True)

    def transcribe_batch(self, audio: np.ndarray) -> str:
        """Feed the full audio to the Vosk recognizer and return the final text."""
        if self._model is None:
            self.load_model()

        duration = len(audio) / self.sample_rate
        logger.info("Transcribing %.2fs of audio (Vosk)...", duration)

        t0 = time.monotonic()
        pcm = self._to_pcm(audio)

        with self._lock:
            self._new_recognizer()
            for i in range(0, len(pcm), _VOSK_PCM_CHUNK_SIZE):
                self._recognizer.AcceptWaveform(pcm[i : i + _VOSK_PCM_CHUNK_SIZE])
            result = json.loads(self._recognizer.FinalResult())

        text: str = result.get("text", "")
        logger.info("Vosk transcription done in %.2fs", time.monotonic() - t0)
        return text

    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str, None, None]:
        """Feed ``chunk`` to the recognizer; yield each utterance as it finalises."""
        if self._model is None:
            self.load_model()

        pcm = self._to_pcm(np.asarray(chunk, dtype=np.float32))
        with self._lock:
            finalised = self._recognizer.AcceptWaveform(pcm)
            text = (
                json.loads(self._recognizer.Result()).get("text", "")
                if finalised
                else ""
            )
        if text:
            yield text

    def stream_finalize(self) -> str:
        """Flush the utterance still open when the stream ended."""
        if self._model is None:
            return ""
        with self._lock:
            text: str = json.loads(self._recognizer.FinalResult()).get("text", "")
            self._new_recognizer()
        return text

    def reset(self) -> None:
        """Reset the Vosk recognizer state for a new dictation session."""
        if self._model is not None:
            self._new_recognizer()


class MoonshineTranscriber(TranscriberBase):
    """Moonshine (ONNX) backend — fast English-only ASR tuned for short audio.

    Runs on onnxruntime with no torch/CUDA dependency and is markedly faster
    than Whisper on short utterances, making it a strong fit for push-to-talk
    dictation on modest CPUs.  Moonshine accepts segments up to ~64s, so longer
    recordings are split into ``_MOONSHINE_CHUNK_SECONDS`` windows and rejoined.
    """

    def __init__(
        self,
        model_name: str = "moonshine/base",
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
    ):
        self.model_name = model_name
        self.sample_rate = sample_rate
        self._model: Any = None
        self._tokenizer: Any = None
        self._lock = threading.Lock()

    def load_model(self) -> None:
        """Load the Moonshine ONNX model and tokenizer, then warm them up."""
        from moonshine_onnx import MoonshineOnnxModel, load_tokenizer

        logger.info("Loading Moonshine model '%s'...", self.model_name)
        t0 = time.monotonic()
        self._model = MoonshineOnnxModel(model_name=self.model_name)
        self._tokenizer = load_tokenizer()
        logger.info("Moonshine model loaded in %.2fs", time.monotonic() - t0)
        self._warmup()

    def _warmup(self) -> None:
        """Run one throwaway inference so the first dictation isn't penalised by
        lazy init."""
        try:
            silence = np.zeros(self.sample_rate, dtype=np.float32)
            with self._lock:
                self._generate(silence)
            logger.info("Moonshine warmup complete")
        except Exception as exc:  # noqa: BLE001 — warmup is best-effort
            logger.debug("Warmup skipped: %s", exc)

    def _generate(self, segment: np.ndarray) -> str:
        """Transcribe a single in-range segment (caller holds the lock)."""
        tokens = self._model.generate(segment[None, ...])
        decoded: list[str] = self._tokenizer.decode_batch(tokens)
        return decoded[0].strip() if decoded else ""

    def transcribe_batch(self, audio: np.ndarray) -> str:
        """Transcribe ``audio``, segmenting recordings longer than the model limit."""
        if self._model is None:
            self.load_model()

        audio = np.asarray(audio, dtype=np.float32)
        duration = len(audio) / self.sample_rate
        logger.info("Transcribing %.2fs of audio (Moonshine)...", duration)
        if duration < _MOONSHINE_MIN_SECONDS:
            return ""

        t0 = time.monotonic()
        chunk_samples = _MOONSHINE_CHUNK_SECONDS * self.sample_rate
        parts: list[str] = []
        with self._lock:
            for start in range(0, len(audio), chunk_samples):
                segment = audio[start : start + chunk_samples]
                if len(segment) / self.sample_rate < _MOONSHINE_MIN_SECONDS:
                    continue
                text = self._generate(segment)
                if text:
                    parts.append(text)

        logger.info("Moonshine transcription done in %.2fs", time.monotonic() - t0)
        return " ".join(parts)

    def reset(self) -> None:
        """No persistent per-session state; retained for interface compatibility."""
        return


class ParakeetTranscriber(TranscriberBase):
    """NVIDIA Parakeet TDT via onnx-asr — INT8 on onnxruntime, batch only.

    Parakeet decodes a whole utterance in one pass (well under a second for a
    typical dictation on a desktop CPU) and emits punctuated, capitalised text.
    It has no incremental output, so like Whisper it transcribes once on
    hotkey release.  Recordings longer than ``_PARAKEET_CHUNK_SECONDS`` are cut
    at quiet points and the pieces rejoined.
    """

    def __init__(
        self,
        model_name: str = "nemo-parakeet-tdt-0.6b-v2",
        quantization: str | None = "int8",
        cpu_threads: int | None = None,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
    ):
        self.model_name = model_name
        # onnx-asr expects None (not "") for the unquantized float model.
        self.quantization = quantization or None
        self.cpu_threads = cpu_threads or physical_core_count()
        self.sample_rate = sample_rate
        self._model: Any = None
        self._lock = threading.Lock()

    def load_model(self) -> None:
        """Download (if needed) and load the Parakeet model, then warm it up."""
        import onnx_asr
        import onnxruntime as ort

        logger.info(
            "Loading Parakeet model '%s' (quantization=%s, threads=%d)...",
            self.model_name,
            self.quantization,
            self.cpu_threads,
        )
        t0 = time.monotonic()
        sess_options = ort.SessionOptions()
        sess_options.intra_op_num_threads = self.cpu_threads
        # One utterance at a time: parallelism comes from intra-op threads.
        sess_options.inter_op_num_threads = 1
        self._model = onnx_asr.load_model(
            self.model_name,
            quantization=self.quantization,
            sess_options=sess_options,
            providers=["CPUExecutionProvider"],
        )
        logger.info("Parakeet model loaded in %.2fs", time.monotonic() - t0)
        self._warmup()

    def _warmup(self) -> None:
        """Run one throwaway inference so the first dictation isn't penalised by
        lazy init."""
        try:
            silence = np.zeros(self.sample_rate, dtype=np.float32)
            with self._lock:
                self._model.recognize(silence, sample_rate=self.sample_rate)
            logger.info("Parakeet warmup complete")
        except Exception as exc:  # noqa: BLE001 — warmup is best-effort
            logger.debug("Warmup skipped: %s", exc)

    def transcribe_batch(self, audio: np.ndarray) -> str:
        """Transcribe ``audio``, splitting recordings longer than the model's
        comfortable window at quiet points."""
        from verbal_code.audio import split_at_quiet_points

        if self._model is None:
            self.load_model()

        audio = np.asarray(audio, dtype=np.float32)
        duration = len(audio) / self.sample_rate
        logger.info("Transcribing %.2fs of audio (Parakeet)...", duration)
        if duration < _PARAKEET_MIN_SECONDS:
            return ""

        t0 = time.monotonic()
        parts: list[str] = []
        with self._lock:
            for segment in split_at_quiet_points(
                audio, self.sample_rate, _PARAKEET_CHUNK_SECONDS
            ):
                if len(segment) / self.sample_rate < _PARAKEET_MIN_SECONDS:
                    continue
                text = self._model.recognize(segment, sample_rate=self.sample_rate)
                if text and text.strip():
                    parts.append(text.strip())

        logger.info("Parakeet transcription done in %.2fs", time.monotonic() - t0)
        return " ".join(parts)

    def reset(self) -> None:
        """No persistent per-session state; retained for interface compatibility."""
        return

    def unload_model(self) -> None:
        """Drop the onnxruntime sessions so their memory can be reclaimed."""
        with self._lock:
            self._model = None
        gc.collect()


class SherpaOnnxTranscriber(TranscriberBase):
    """True live-streaming transducer STT via sherpa-onnx.

    Runs streaming Zipformer / Nemotron transducers.  Endpoint detection ends
    an utterance after a pause; the text is then final and the stream is
    reset, so every yielded utterance is new text the engine will never
    revise (no duplicated prefixes) and is safe to inject live.  Models are
    downloaded on first use and checksum-verified (see
    :mod:`verbal_code.sherpa_models`).
    """

    supports_live_streaming = True

    def __init__(
        self,
        model_name: str = "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06",
        cpu_threads: int | None = None,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
        cache_dir: str | None = None,
    ):
        self.model_name = model_name
        self.cpu_threads = cpu_threads or physical_core_count()
        # Capture rate of the audio we're fed; sherpa-onnx resamples it to
        # the model's 16 kHz feature rate internally.
        self.sample_rate = sample_rate
        self.cache_dir = cache_dir
        self._recognizer: Any = None
        self._stream: Any = None
        self._lock = threading.Lock()

    def load_model(self) -> None:
        """Download (if needed) and load the transducer, then open a stream."""
        import sherpa_onnx

        from verbal_code.sherpa_models import (
            DEFAULT_SHERPA_CACHE_DIR,
            ensure_sherpa_model_downloaded,
            resolve_transducer_files,
        )

        logger.info(
            "Loading sherpa-onnx model '%s' (threads=%d)...",
            self.model_name,
            self.cpu_threads,
        )
        t0 = time.monotonic()
        model_dir = ensure_sherpa_model_downloaded(
            self.model_name, self.cache_dir or DEFAULT_SHERPA_CACHE_DIR
        )
        encoder, decoder, joiner, tokens = resolve_transducer_files(model_dir)
        recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=tokens,
            encoder=encoder,
            decoder=decoder,
            joiner=joiner,
            num_threads=self.cpu_threads,
            sample_rate=_DEFAULT_SAMPLE_RATE,
            feature_dim=80,
            enable_endpoint_detection=True,
            # An utterance ends after 2.4s of silence with nothing decoded,
            # 1.2s of silence after speech, or at 20s regardless.
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=1.2,
            rule3_min_utterance_length=20.0,
            decoding_method="greedy_search",
            provider="cpu",
        )
        with self._lock:
            self._recognizer = recognizer
            self._stream = recognizer.create_stream()
        logger.info("sherpa-onnx model loaded in %.2fs", time.monotonic() - t0)

    def _decode_ready(self, stream: Any) -> None:
        """Decode every frame the stream has buffered (caller holds the lock)."""
        while self._recognizer.is_ready(stream):
            self._recognizer.decode_stream(stream)

    def _finish(self, stream: Any) -> str:
        """Pad, close, and fully decode ``stream``; return its text (caller
        holds the lock)."""
        tail = np.zeros(
            int(_SHERPA_TAIL_PADDING_SECONDS * self.sample_rate), dtype=np.float32
        )
        stream.accept_waveform(self.sample_rate, tail)
        stream.input_finished()
        self._decode_ready(stream)
        text: str = self._recognizer.get_result(stream).strip()
        return text

    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str, None, None]:
        """Feed ``chunk``; yield an utterance each time an endpoint is detected."""
        if self._recognizer is None:
            self.load_model()

        samples = np.asarray(chunk, dtype=np.float32)
        text = ""
        with self._lock:
            self._stream.accept_waveform(self.sample_rate, samples)
            self._decode_ready(self._stream)
            if self._recognizer.is_endpoint(self._stream):
                text = self._recognizer.get_result(self._stream).strip()
                # Start the next utterance from scratch so its text never
                # repeats what was just yielded.
                self._recognizer.reset(self._stream)
        if text:
            yield text

    def stream_finalize(self) -> str:
        """Flush the utterance still open when the stream ended."""
        if self._recognizer is None:
            return ""
        with self._lock:
            text = self._finish(self._stream)
            # input_finished() is one-way, so the next recording needs a
            # fresh stream rather than a reset of this one.
            self._stream = self._recognizer.create_stream()
        return text

    def transcribe_batch(self, audio: np.ndarray) -> str:
        """Decode a complete recording on a fresh one-shot stream."""
        if self._recognizer is None:
            self.load_model()

        audio = np.asarray(audio, dtype=np.float32)
        duration = len(audio) / self.sample_rate
        logger.info("Transcribing %.2fs of audio (sherpa-onnx)...", duration)
        t0 = time.monotonic()
        with self._lock:
            stream = self._recognizer.create_stream()
            stream.accept_waveform(self.sample_rate, audio)
            text = self._finish(stream)
        logger.info("sherpa-onnx transcription done in %.2fs", time.monotonic() - t0)
        return text

    def reset(self) -> None:
        """Open a fresh stream so a new dictation never inherits buffered audio."""
        with self._lock:
            if self._recognizer is not None:
                self._stream = self._recognizer.create_stream()

    def unload_model(self) -> None:
        """Drop the recognizer and stream so their memory can be reclaimed."""
        with self._lock:
            self._stream = None
            self._recognizer = None
        gc.collect()


# Model choices offered in the tray's quick-switch menu, per engine.  The
# first entry of each list is that engine's default model.
AVAILABLE_MODELS: dict[str, list[str]] = {
    "parakeet": [
        # Best English accuracy; punctuated and capitalised output.
        "nemo-parakeet-tdt-0.6b-v2",
        # Multilingual (25 European languages + English).
        "nemo-parakeet-tdt-0.6b-v3",
    ],
    "sherpa": [
        # Lightweight live streaming (~57 MB download).
        "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06",
        # More accurate live streaming (~464 MB download, INT8).
        "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25",
    ],
    "whisper": [
        "distil-small.en",
        # Between distil-small.en and distil-large-v3.5 in size and accuracy.
        "distil-medium.en",
        # Faster than large-v3-turbo on short clips, with similar accuracy.
        "distil-large-v3.5",
        "base.en",
        "small.en",
        "large-v3-turbo",
    ],
    "moonshine": ["moonshine/base", "moonshine/tiny"],
    "vosk": ["vosk-model-small-en-us-0.15"],
}

_ENGINE_PACKAGES: dict[str, str] = {
    "parakeet": "onnx_asr",
    "sherpa": "sherpa_onnx",
    "whisper": "faster_whisper",
    "moonshine": "moonshine_onnx",
    "vosk": "vosk",
}

# Where each engine's model name lives in the config: stt.<section>.<key>.
_MODEL_CONFIG_KEYS: dict[str, tuple[str, str]] = {
    "parakeet": ("parakeet", "model"),
    "sherpa": ("sherpa", "model"),
    "whisper": ("whisper", "model"),
    "moonshine": ("moonshine", "model"),
    "vosk": ("vosk", "model_name"),
}


def installed_engines() -> list[str]:
    """Return the engines whose Python packages are importable."""
    import importlib.util

    return [
        engine
        for engine, package in _ENGINE_PACKAGES.items()
        if importlib.util.find_spec(package) is not None
    ]


def _model_key(engine: str) -> tuple[str, str, str]:
    """Return (section, key, default model) for ``engine``; unknown engines
    resolve like whisper, matching :func:`create_transcriber`."""
    if engine not in _MODEL_CONFIG_KEYS:
        engine = "whisper"
    section, key = _MODEL_CONFIG_KEYS[engine]
    return section, key, AVAILABLE_MODELS[engine][0]


def current_selection(config: dict) -> tuple[str, str]:
    """Return the (engine, model) pair the config currently selects."""
    stt_cfg = config.get("stt", {})
    engine: str = stt_cfg.get("engine", "whisper")
    section, key, default = _model_key(engine)
    model: str = stt_cfg.get(section, {}).get(key, default)
    return engine, model


def apply_selection(config: dict, engine: str, model: str) -> None:
    """Write an (engine, model) choice into ``config`` in place."""
    stt_cfg = config.setdefault("stt", {})
    stt_cfg["engine"] = engine
    section, key, _ = _model_key(engine)
    stt_cfg.setdefault(section, {})[key] = model


def create_transcriber(config: dict) -> TranscriberBase:
    """Instantiate and return the transcriber specified by ``config['stt']['engine']``.

    Supported engines: ``"whisper"`` (default), ``"parakeet"``, ``"sherpa"``,
    ``"moonshine"``, and ``"vosk"``.
    """
    stt_cfg = config.get("stt", {})
    engine: str = stt_cfg.get("engine", "whisper")
    sample_rate: int = config.get("audio", {}).get("sample_rate", _DEFAULT_SAMPLE_RATE)
    # Inference threads for the engines that expose it; None means one per
    # physical core (see physical_core_count).
    cpu_threads: int | None = stt_cfg.get("cpu_threads")
    _, model = current_selection(config)

    if engine == "parakeet":
        return ParakeetTranscriber(
            model_name=model,
            quantization=stt_cfg.get("parakeet", {}).get("quantization", "int8"),
            cpu_threads=cpu_threads,
            sample_rate=sample_rate,
        )

    if engine == "sherpa":
        return SherpaOnnxTranscriber(
            model_name=model, cpu_threads=cpu_threads, sample_rate=sample_rate
        )

    if engine == "vosk":
        return VoskTranscriber(model_name=model, sample_rate=sample_rate)

    if engine == "moonshine":
        return MoonshineTranscriber(model_name=model, sample_rate=sample_rate)

    whisper_cfg = stt_cfg.get("whisper", {})
    return WhisperTranscriber(
        model_size=model,
        device=whisper_cfg.get("device", "auto"),
        compute_type=whisper_cfg.get("compute_type", "int8"),
        language=whisper_cfg.get("language", "en"),
        beam_size=whisper_cfg.get("beam_size", 2),
        batch_size=whisper_cfg.get("batch_size", 8),
        initial_prompt=whisper_cfg.get("initial_prompt", ""),
        sample_rate=sample_rate,
        cpu_threads=cpu_threads,
    )
