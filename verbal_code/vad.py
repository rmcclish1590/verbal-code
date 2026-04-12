import logging
from typing import Any

import numpy as np

logger = logging.getLogger("verbal_code")

# Silero VAD requires exactly 512 samples per inference window at 16 kHz.
_SILERO_WINDOW_SIZE = 512


class VoiceActivityDetector:
    """Wraps the Silero VAD model to gate audio on detected speech.

    Audio chunks that contain no speech are discarded.  Once a speech segment
    ends (silence exceeds ``silence_ms``) the accumulated speech audio is
    returned as a single array.  If Silero is unavailable (torch not installed)
    the detector degrades gracefully: ``available`` is False and every chunk
    passes through unfiltered.
    """

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
        self._model: Any = None
        self._torch: Any = None
        self._available = False

        self._speech_chunks: list[np.ndarray] = []
        self._silence_samples: int = 0
        self._in_speech: bool = False

        self._min_speech_samples = int(min_speech_ms * sample_rate / 1000)
        self._silence_threshold_samples = int(silence_ms * sample_rate / 1000)

        self._load_model()

    def _load_model(self) -> None:
        try:
            import torch
            from silero_vad import load_silero_vad

            self._model = load_silero_vad()
            self._torch = torch
            self._available = True
            logger.info("Silero VAD loaded (threshold=%.2f)", self.threshold)
        except Exception as exc:  # noqa: BLE001 — optional dependency, degrade gracefully
            logger.warning("VAD unavailable (%s), all audio will pass through", exc)

    @property
    def available(self) -> bool:
        """True when the Silero model loaded successfully."""
        return self._available

    def is_speech(self, audio_chunk: np.ndarray) -> bool:
        """Return True if any 512-sample window in ``audio_chunk`` contains speech.

        Processes in fixed-size windows because Silero requires exactly
        ``_SILERO_WINDOW_SIZE`` samples per forward pass.
        """
        if not self._available:
            return True

        for i in range(0, len(audio_chunk), _SILERO_WINDOW_SIZE):
            window = audio_chunk[i : i + _SILERO_WINDOW_SIZE]
            if len(window) < _SILERO_WINDOW_SIZE:
                window = np.pad(window, (0, _SILERO_WINDOW_SIZE - len(window)))
            tensor = self._torch.from_numpy(window).float()
            prob: float = self._model(tensor, self.sample_rate).item()
            if prob > self.threshold:
                logger.debug("[vad] Speech detected (prob=%.2f)", prob)
                return True

        logger.debug("[vad] Silence detected")
        return False

    def process_chunk(self, chunk: np.ndarray) -> np.ndarray | None:
        """Feed ``chunk`` to the VAD state machine.

        Returns a concatenated speech segment when a complete utterance is
        detected (i.e. trailing silence exceeds the threshold), otherwise None.
        """
        if not self._available:
            return chunk

        if self.is_speech(chunk):
            self._speech_chunks.append(chunk)
            self._silence_samples = 0
            self._in_speech = True
            return None

        if self._in_speech:
            self._silence_samples += len(chunk)
            if self._silence_samples >= self._silence_threshold_samples:
                return self._finalise_segment()

        return None

    def _finalise_segment(self) -> np.ndarray | None:
        """Emit the current speech buffer if it meets the minimum length, else discard."""
        total_samples = sum(len(c) for c in self._speech_chunks)
        if total_samples >= self._min_speech_samples:
            result = np.concatenate(self._speech_chunks)
            logger.debug("[vad] Speech segment: %.1fs", len(result) / self.sample_rate)
        else:
            logger.debug("[vad] Speech too short, discarding")
            result = None  # type: ignore[assignment]
        self._reset_state()
        return result

    def _reset_state(self) -> None:
        self._speech_chunks = []
        self._silence_samples = 0
        self._in_speech = False

    def flush(self) -> np.ndarray | None:
        """Emit any buffered speech regardless of trailing silence.

        Call this when dictation ends to capture utterances that were still
        in-progress when the hotkey was released.
        """
        if not self._speech_chunks:
            self._reset_state()
            return None

        total_samples = sum(len(c) for c in self._speech_chunks)
        if total_samples >= self._min_speech_samples:
            result = np.concatenate(self._speech_chunks)
            logger.debug(
                "[vad] Flushing speech segment: %.1fs", len(result) / self.sample_rate
            )
            self._reset_state()
            return result

        self._reset_state()
        return None

    def reset(self) -> None:
        """Reset VAD state and Silero's internal GRU hidden states."""
        self._reset_state()
        if self._available:
            self._model.reset_states()
