import logging
import queue
import threading
import wave
from typing import Any

import numpy as np
import sounddevice as sd

logger = logging.getLogger("verbal_code")

_PCM_MAX_AMPLITUDE = 32767
_PCM_MIN_AMPLITUDE = -32768
_PCM_SAMPLE_WIDTH = 2


class AudioCapture:
    """Captures audio from a sounddevice input stream into an in-memory queue.

    Chunks are accumulated per-session so the full recording can be retrieved
    on stop.  Thread-safe: start/stop are protected by an internal lock.
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

        self._queue: queue.Queue[np.ndarray] = queue.Queue()
        self._session_chunks: list[np.ndarray] = []
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
        self._queue.put(chunk)
        self._session_chunks.append(chunk)

    def start(self) -> None:
        """Open the input stream and begin collecting audio chunks."""
        with self._lock:
            if self._running:
                return
            self._queue = queue.Queue()
            self._session_chunks = []
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
            logger.info(
                "Audio capture stopped, %d chunks recorded",
                len(self._session_chunks),
            )
            if self._session_chunks:
                return np.concatenate(self._session_chunks)
            return np.array([], dtype=np.float32)

    def get_chunk(self, timeout: float = 0.1) -> np.ndarray | None:
        """Return the next available chunk, or None if the queue is empty."""
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_all_chunks(self) -> list[np.ndarray]:
        """Drain and return all chunks currently in the queue."""
        chunks = []
        while True:
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                break
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
