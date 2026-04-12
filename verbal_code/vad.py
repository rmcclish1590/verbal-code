import logging

import numpy as np

logger = logging.getLogger("verbal_code")


class VoiceActivityDetector:
    def __init__(
        self,
        threshold: float = 0.5,
        min_speech_ms: int = 250,
        silence_ms: int = 500,
        sample_rate: int = 16000,
    ):
        self.threshold = threshold
        self.min_speech_ms = min_speech_ms
        self.silence_ms = silence_ms
        self.sample_rate = sample_rate
        self._model = None
        self._available = False

        self._speech_chunks: list[np.ndarray] = []
        self._silence_samples = 0
        self._in_speech = False

        self._min_speech_samples = int(min_speech_ms * sample_rate / 1000)
        self._silence_threshold_samples = int(silence_ms * sample_rate / 1000)

        self._load_model()

    def _load_model(self) -> None:
        try:
            import torch
            model, _ = torch.hub.load(
                "snakers4/silero-vad", "silero_vad", trust_repo=True,
            )
            self._model = model
            self._torch = torch
            self._available = True
            logger.info("Silero VAD loaded (threshold=%.2f)", self.threshold)
        except Exception as e:
            logger.warning("VAD unavailable (%s), all audio will pass through", e)

    @property
    def available(self) -> bool:
        return self._available

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        if not self._available:
            return True

        # Silero expects 512-sample chunks at 16kHz
        # Process in 512-sample windows and return True if any window has speech
        chunk_size = 512
        for i in range(0, len(audio_chunk), chunk_size):
            window = audio_chunk[i:i + chunk_size]
            if len(window) < chunk_size:
                window = np.pad(window, (0, chunk_size - len(window)))
            tensor = self._torch.from_numpy(window).float()
            prob = self._model(tensor, self.sample_rate).item()
            if prob > self.threshold:
                logger.debug("[vad] Speech detected (prob=%.2f)", prob)
                return True

        logger.debug("[vad] Silence detected")
        return False

    def process_chunk(self, chunk: np.ndarray) -> np.ndarray | None:
        if not self._available:
            return chunk

        speech = self.is_speech(chunk)

        if speech:
            self._speech_chunks.append(chunk)
            self._silence_samples = 0
            if not self._in_speech:
                self._in_speech = True
            return None

        if self._in_speech:
            self._silence_samples += len(chunk)
            if self._silence_samples >= self._silence_threshold_samples:
                total_samples = sum(len(c) for c in self._speech_chunks)
                if total_samples >= self._min_speech_samples:
                    result = np.concatenate(self._speech_chunks)
                    duration = len(result) / self.sample_rate
                    logger.debug("[vad] Speech segment: %.1fs", duration)
                    self._speech_chunks = []
                    self._silence_samples = 0
                    self._in_speech = False
                    return result
                else:
                    logger.debug("[vad] Speech too short, discarding")
                    self._speech_chunks = []
                    self._silence_samples = 0
                    self._in_speech = False

        return None

    def flush(self) -> np.ndarray | None:
        if self._speech_chunks:
            total_samples = sum(len(c) for c in self._speech_chunks)
            if total_samples >= self._min_speech_samples:
                result = np.concatenate(self._speech_chunks)
                duration = len(result) / self.sample_rate
                logger.debug("[vad] Flushing speech segment: %.1fs", duration)
                self._speech_chunks = []
                self._in_speech = False
                self._silence_samples = 0
                return result
        self._speech_chunks = []
        self._in_speech = False
        self._silence_samples = 0
        return None

    def reset(self) -> None:
        self._speech_chunks = []
        self._silence_samples = 0
        self._in_speech = False
        if self._available:
            self._model.reset_states()
