import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

import numpy as np

logger = logging.getLogger("verbal_code")

_DEFAULT_SAMPLE_RATE = 16000
_VOSK_PCM_CHUNK_SIZE = 4000
# Moonshine accepts 0.1s–64s per call; split long recordings into 30s windows.
_MOONSHINE_CHUNK_SECONDS = 30
_MOONSHINE_MIN_SECONDS = 0.1
_PCM_MAX_AMPLITUDE = 32767
_PCM_MIN_AMPLITUDE = -32768


class TranscriberBase(ABC):
    """Abstract interface for speech-to-text backends."""

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
        beam_size: int = 5,
        batch_size: int = 8,
        initial_prompt: str = "",
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
    ):
        self.model_size = model_size
        self.device = device
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

    def load_model(self) -> None:
        """Download (if needed) and load the Whisper model, then warm it up."""
        from faster_whisper import BatchedInferencePipeline, WhisperModel

        logger.info(
            "Loading Whisper model '%s' (device=%s, compute_type=%s)...",
            self.model_size,
            self.device,
            self.compute_type,
        )
        t0 = time.monotonic()
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        self._batched = BatchedInferencePipeline(model=self._model)
        logger.info("Whisper model loaded in %.2fs", time.monotonic() - t0)
        self._warmup()

    def _warmup(self) -> None:
        """Run one throwaway inference so the first dictation isn't penalised by lazy init."""
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

    def reset(self) -> None:
        """No persistent per-session state; retained for interface compatibility."""
        return


class VoskTranscriber(TranscriberBase):
    """Vosk-backed transcriber.  Lightweight; works offline without a GPU."""

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
        """Run one throwaway inference so the first dictation isn't penalised by lazy init."""
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


def create_transcriber(config: dict) -> TranscriberBase:
    """Instantiate and return the transcriber specified by ``config['stt']['engine']``.

    Supported engines: ``"whisper"`` (default), ``"moonshine"``, and ``"vosk"``.
    """
    stt_cfg = config.get("stt", {})
    engine: str = stt_cfg.get("engine", "whisper")

    if engine == "vosk":
        vosk_cfg = stt_cfg.get("vosk", {})
        return VoskTranscriber(
            model_name=vosk_cfg.get("model_name", "vosk-model-small-en-us-0.15"),
            sample_rate=config.get("audio", {}).get("sample_rate", _DEFAULT_SAMPLE_RATE),
        )

    if engine == "moonshine":
        moonshine_cfg = stt_cfg.get("moonshine", {})
        return MoonshineTranscriber(
            model_name=moonshine_cfg.get("model", "moonshine/base"),
            sample_rate=config.get("audio", {}).get("sample_rate", _DEFAULT_SAMPLE_RATE),
        )

    whisper_cfg = stt_cfg.get("whisper", {})
    return WhisperTranscriber(
        model_size=whisper_cfg.get("model", "distil-small.en"),
        device=whisper_cfg.get("device", "auto"),
        compute_type=whisper_cfg.get("compute_type", "int8"),
        language=whisper_cfg.get("language", "en"),
        beam_size=whisper_cfg.get("beam_size", 5),
        batch_size=whisper_cfg.get("batch_size", 8),
        initial_prompt=whisper_cfg.get("initial_prompt", ""),
        sample_rate=config.get("audio", {}).get("sample_rate", _DEFAULT_SAMPLE_RATE),
    )
