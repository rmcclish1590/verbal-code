import logging
import queue
import threading
import wave

import numpy as np
import sounddevice as sd

logger = logging.getLogger("verbal_code")


class AudioCapture:
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

    def _callback(self, indata, frames, time_info, status):
        if status:
            logger.warning("Audio callback status: %s", status)
        chunk = indata[:, 0].copy()
        self._queue.put(chunk)
        self._session_chunks.append(chunk)

    def start(self) -> None:
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
            logger.info("Audio capture started (rate=%d, device=%s)", self.sample_rate, self.device_index)

    def stop(self) -> np.ndarray:
        with self._lock:
            if not self._running:
                return np.array([], dtype=np.float32)
            self._stream.stop()
            self._stream.close()
            self._stream = None
            self._running = False
            logger.info("Audio capture stopped, %d chunks recorded", len(self._session_chunks))
            if self._session_chunks:
                return np.concatenate(self._session_chunks)
            return np.array([], dtype=np.float32)

    def get_chunk(self, timeout: float = 0.1) -> np.ndarray | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    def get_all_chunks(self) -> list[np.ndarray]:
        chunks = []
        while True:
            try:
                chunks.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return chunks

    @staticmethod
    def list_devices() -> str:
        return str(sd.query_devices())

    @staticmethod
    def save_wav(path: str, audio: np.ndarray, sample_rate: int = 16000) -> None:
        pcm = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(pcm.tobytes())
