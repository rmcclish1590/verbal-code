import logging
import threading
import wave
from typing import Any

import numpy as np
import sounddevice as sd

logger = logging.getLogger("verbal_code")

_PCM_MAX_AMPLITUDE = 32767
_PCM_MIN_AMPLITUDE = -32768
_PCM_SAMPLE_WIDTH = 2


def trim_silence(
    audio: np.ndarray,
    sample_rate: int,
    threshold_db: float = -40.0,
    frame_ms: int = 30,
    padding_ms: int = 150,
) -> np.ndarray:
    """Trim leading and trailing silence from float32 audio in [-1, 1].

    Frames of ``frame_ms`` are classified by RMS energy against
    ``threshold_db`` (relative to full scale); everything before the first and
    after the last voiced frame is dropped, keeping ``padding_ms`` of context
    on each side so soft utterance onsets aren't clipped.  Returns an empty
    array when no frame crosses the threshold, and the input unchanged when it
    is shorter than one frame.
    """
    frame_len = max(1, int(sample_rate * frame_ms / 1000))
    n_frames = len(audio) // frame_len
    if n_frames == 0:
        return audio

    frames = audio[: n_frames * frame_len].reshape(n_frames, frame_len)
    rms = np.sqrt(np.mean(frames.astype(np.float64) ** 2, axis=1))
    threshold = 10.0 ** (threshold_db / 20.0)
    voiced = np.flatnonzero(rms > threshold)
    if voiced.size == 0:
        return audio[:0]

    padding = int(sample_rate * padding_ms / 1000)
    start = max(0, int(voiced[0]) * frame_len - padding)
    end = min(len(audio), (int(voiced[-1]) + 1) * frame_len + padding)
    return audio[start:end]


class AudioCapture:
    """Captures audio from a sounddevice input stream into a single buffer.

    Chunks are appended once per callback; a read cursor lets the streaming
    consumer walk the same list the batch path concatenates on stop, so
    nothing is stored twice.  Thread-safe: buffer access is guarded by a
    condition, start/stop by a lock.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        channels: int = 1,
        chunk_size: int = 1024,
        device_index: int | None = None,
    ):
        self.sample_rate = sample_rate
        self.channels = channels
        self.chunk_size = chunk_size
        self.device_index = device_index

        self._chunks: list[np.ndarray] = []
        self._read_pos = 0
        self._chunk_ready = threading.Condition()
        self._stream: sd.InputStream | None = None
        self._lock = threading.Lock()
        self._running = False

    def _callback(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: Any,
        status: sd.CallbackFlags,
    ) -> None:
        if status:
            logger.warning("Audio callback status: %s", status)
        chunk = indata[:, 0].copy()
        with self._chunk_ready:
            self._chunks.append(chunk)
            self._chunk_ready.notify_all()

    def start(self) -> None:
        """Open the input stream and begin collecting audio chunks."""
        with self._lock:
            if self._running:
                return
            with self._chunk_ready:
                self._chunks = []
                self._read_pos = 0
            self._stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=self.channels,
                blocksize=self.chunk_size,
                device=self.device_index,
                dtype="float32",
                callback=self._callback,
            )
            self._stream.start()
            self._running = True
            logger.info(
                "Audio capture started (rate=%d, device=%s)",
                self.sample_rate,
                self.device_index,
            )

    def stop(self) -> np.ndarray:
        """Stop the stream and return all captured audio as a single array."""
        with self._lock:
            if not self._running:
                return np.array([], dtype=np.float32)
            self._stream.stop()  # type: ignore[union-attr]
            self._stream.close()  # type: ignore[union-attr]
            self._stream = None
            self._running = False
            with self._chunk_ready:
                chunks = list(self._chunks)
            logger.info("Audio capture stopped, %d chunks recorded", len(chunks))
            if chunks:
                return np.concatenate(chunks)
            return np.array([], dtype=np.float32)

    def get_chunk(self, timeout: float = 0.1) -> np.ndarray | None:
        """Return the next unread chunk, or None if none arrives in time.

        Reading advances a cursor over the session buffer; the chunks stay in
        place for the batch concatenation on stop.
        """
        with self._chunk_ready:
            if self._read_pos >= len(self._chunks):
                self._chunk_ready.wait(timeout)
            if self._read_pos >= len(self._chunks):
                return None
            chunk = self._chunks[self._read_pos]
            self._read_pos += 1
            return chunk

    def get_all_chunks(self) -> list[np.ndarray]:
        """Return all currently unread chunks and advance past them."""
        with self._chunk_ready:
            chunks = self._chunks[self._read_pos :]
            self._read_pos = len(self._chunks)
            return chunks

    @staticmethod
    def list_devices() -> str:
        """Return a human-readable string of available audio devices."""
        return str(sd.query_devices())

    @staticmethod
    def save_wav(path: str, audio: np.ndarray, sample_rate: int = 16000) -> None:
        """Write a mono float32 array to a 16-bit PCM WAV file at ``path``."""
        pcm = np.clip(
            audio * _PCM_MAX_AMPLITUDE,
            _PCM_MIN_AMPLITUDE,
            _PCM_MAX_AMPLITUDE,
        ).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(_PCM_SAMPLE_WIDTH)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
