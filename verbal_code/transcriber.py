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
    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str, None, None]:
        """Process an incremental audio chunk and yield any new text delta."""
        ...

    @abstractmethod
    def reset(self) -> None:
        """Reset any internal streaming state between dictation sessions."""
        ...


class WhisperTranscriber(TranscriberBase):
    """faster-whisper backed transcriber with batch and streaming support.

    Streaming accumulates audio into a rolling buffer and runs inference every
    ``_STREAM_INTERVAL_SECONDS`` seconds.  Only the text delta since the last
    emission is yielded so callers do not see duplicate prefixes.
    """

    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "en",
        beam_size: int = 5,
        sample_rate: int = _DEFAULT_SAMPLE_RATE,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self.sample_rate = sample_rate
        self._model: Any = None
        self._lock = threading.Lock()
        self._stream_buffer: list[np.ndarray] = []
        self._stream_samples: int = 0
        self._last_stream_text: str = ""
        self._stream_interval_samples = int(_STREAM_INTERVAL_SECONDS * sample_rate)

    def load_model(self) -> None:
        """Download (if needed) and load the Whisper model into memory."""
        from faster_whisper import WhisperModel

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
        logger.info("Whisper model loaded in %.2fs", time.monotonic() - t0)

    def transcribe_batch(self, audio: np.ndarray) -> str:
        """Run full-utterance transcription and return the joined text."""
        if self._model is None:
            self.load_model()

        duration = len(audio) / self.sample_rate
        logger.info("Transcribing %.2fs of audio...", duration)

        t0 = time.monotonic()
        with self._lock:
            segments, info = self._model.transcribe(
                audio,
                language=self.language,
                beam_size=self.beam_size,
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
        """Accumulate ``chunk`` and yield a text delta when the buffer is large enough."""
        if self._model is None:
            self.load_model()

        self._stream_buffer.append(chunk)
        self._stream_samples += len(chunk)

        if self._stream_samples < self._stream_interval_samples:
            return

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
        self._last_stream_text = ""


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

    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str, None, None]:
        """Pass ``chunk`` through the Vosk recognizer and yield complete utterances."""
        if self._model is None:
            self.load_model()

        pcm = self._to_pcm(chunk)
        with self._lock:
            if self._recognizer.AcceptWaveform(pcm):
                result = json.loads(self._recognizer.Result())
                text: str = result.get("text", "")
                if text:
                    yield text

    def reset(self) -> None:
        """Reset the Vosk recognizer state for a new dictation session."""
        if self._model is not None:
            self._new_recognizer()


def create_transcriber(config: dict) -> TranscriberBase:
    """Instantiate and return the transcriber specified by ``config['stt']['engine']``.

    Supported engines: ``"whisper"`` (default) and ``"vosk"``.
    """
    stt_cfg = config.get("stt", {})
    engine: str = stt_cfg.get("engine", "whisper")

    if engine == "vosk":
        vosk_cfg = stt_cfg.get("vosk", {})
        return VoskTranscriber(
            model_name=vosk_cfg.get("model_name", "vosk-model-small-en-us-0.15"),
            sample_rate=config.get("audio", {}).get("sample_rate", _DEFAULT_SAMPLE_RATE),
        )

    whisper_cfg = stt_cfg.get("whisper", {})
    return WhisperTranscriber(
        model_size=whisper_cfg.get("model", "base"),
        device=whisper_cfg.get("device", "auto"),
        compute_type=whisper_cfg.get("compute_type", "int8"),
        language=whisper_cfg.get("language", "en"),
        beam_size=whisper_cfg.get("beam_size", 5),
        sample_rate=config.get("audio", {}).get("sample_rate", _DEFAULT_SAMPLE_RATE),
    )
