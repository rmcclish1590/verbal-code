import logging
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Generator

import numpy as np

logger = logging.getLogger("verbal_code")


class TranscriberBase(ABC):
    @abstractmethod
    def load_model(self) -> None: ...

    @abstractmethod
    def transcribe_batch(self, audio: np.ndarray) -> str: ...

    @abstractmethod
    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str]: ...

    @abstractmethod
    def reset(self) -> None: ...


class WhisperTranscriber(TranscriberBase):
    def __init__(
        self,
        model_size: str = "base",
        device: str = "auto",
        compute_type: str = "int8",
        language: str = "en",
        beam_size: int = 5,
    ):
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self.beam_size = beam_size
        self._model = None
        self._lock = threading.Lock()

    def load_model(self) -> None:
        from faster_whisper import WhisperModel

        logger.info(
            "Loading Whisper model '%s' (device=%s, compute_type=%s)...",
            self.model_size, self.device, self.compute_type,
        )
        t0 = time.monotonic()
        self._model = WhisperModel(
            self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        elapsed = time.monotonic() - t0
        logger.info("Whisper model loaded in %.2fs", elapsed)

    def transcribe_batch(self, audio: np.ndarray) -> str:
        if self._model is None:
            self.load_model()

        duration = len(audio) / 16000
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

        elapsed = time.monotonic() - t0
        logger.info(
            "Transcription done in %.2fs (language=%s, prob=%.2f)",
            elapsed, info.language, info.language_probability,
        )
        return text

    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str]:
        yield ""

    def reset(self) -> None:
        pass


def create_transcriber(config: dict) -> TranscriberBase:
    stt_cfg = config.get("stt", {})
    whisper_cfg = stt_cfg.get("whisper", {})
    return WhisperTranscriber(
        model_size=whisper_cfg.get("model", "base"),
        device=whisper_cfg.get("device", "auto"),
        compute_type=whisper_cfg.get("compute_type", "int8"),
        language=whisper_cfg.get("language", "en"),
        beam_size=whisper_cfg.get("beam_size", 5),
    )
