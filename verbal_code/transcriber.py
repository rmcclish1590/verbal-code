import logging
import os
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
        self._stream_buffer: list[np.ndarray] = []
        self._stream_samples = 0
        self._last_stream_text = ""
        self._stream_interval_samples = int(1.5 * 16000)

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
            full_text = " ".join(seg.text.strip() for seg in segments if seg.text.strip())

        if full_text and full_text != self._last_stream_text:
            delta = full_text[len(self._last_stream_text):].strip() if full_text.startswith(self._last_stream_text) else full_text
            self._last_stream_text = full_text
            if delta:
                yield delta

    def reset(self) -> None:
        self._stream_buffer = []
        self._stream_samples = 0
        self._last_stream_text = ""


class VoskTranscriber(TranscriberBase):
    def __init__(self, model_name: str = "vosk-model-small-en-us-0.15", sample_rate: int = 16000):
        self.model_name = model_name
        self.sample_rate = sample_rate
        self._model = None
        self._recognizer = None
        self._lock = threading.Lock()

    @staticmethod
    def _to_pcm(audio: np.ndarray) -> bytes:
        return np.clip(audio * 32767, -32768, 32767).astype(np.int16).tobytes()

    def load_model(self) -> None:
        import vosk

        vosk.SetLogLevel(-1)

        model_dir = os.path.join(os.path.expanduser("~/.cache/verbal-code/models"), self.model_name)
        logger.info("Loading Vosk model '%s'...", self.model_name)
        t0 = time.monotonic()

        if os.path.isdir(model_dir):
            self._model = vosk.Model(model_path=model_dir)
        else:
            os.makedirs(os.path.dirname(model_dir), exist_ok=True)
            logger.info("Model not found locally, downloading...")
            self._model = vosk.Model(model_name=self.model_name)

        elapsed = time.monotonic() - t0
        logger.info("Vosk model loaded in %.2fs", elapsed)
        self._new_recognizer()

    def _new_recognizer(self) -> None:
        import vosk
        self._recognizer = vosk.KaldiRecognizer(self._model, self.sample_rate)
        self._recognizer.SetWords(True)

    def transcribe_batch(self, audio: np.ndarray) -> str:
        if self._model is None:
            self.load_model()

        duration = len(audio) / self.sample_rate
        logger.info("Transcribing %.2fs of audio (Vosk)...", duration)

        t0 = time.monotonic()
        pcm = self._to_pcm(audio)
        chunk_size = 4000

        with self._lock:
            self._new_recognizer()
            for i in range(0, len(pcm), chunk_size):
                self._recognizer.AcceptWaveform(pcm[i:i + chunk_size])

            import json
            result = json.loads(self._recognizer.FinalResult())

        elapsed = time.monotonic() - t0
        text = result.get("text", "")
        logger.info("Vosk transcription done in %.2fs", elapsed)
        return text

    def transcribe_stream(self, chunk: np.ndarray) -> Generator[str]:
        if self._model is None:
            self.load_model()

        import json
        pcm = self._to_pcm(chunk)
        with self._lock:
            if self._recognizer.AcceptWaveform(pcm):
                result = json.loads(self._recognizer.Result())
                text = result.get("text", "")
                if text:
                    yield text

    def reset(self) -> None:
        if self._model is not None:
            self._new_recognizer()


def create_transcriber(config: dict) -> TranscriberBase:
    stt_cfg = config.get("stt", {})
    engine = stt_cfg.get("engine", "whisper")

    if engine == "vosk":
        vosk_cfg = stt_cfg.get("vosk", {})
        return VoskTranscriber(
            model_name=vosk_cfg.get("model_name", "vosk-model-small-en-us-0.15"),
            sample_rate=config.get("audio", {}).get("sample_rate", 16000),
        )

    whisper_cfg = stt_cfg.get("whisper", {})
    return WhisperTranscriber(
        model_size=whisper_cfg.get("model", "base"),
        device=whisper_cfg.get("device", "auto"),
        compute_type=whisper_cfg.get("compute_type", "int8"),
        language=whisper_cfg.get("language", "en"),
        beam_size=whisper_cfg.get("beam_size", 5),
    )
