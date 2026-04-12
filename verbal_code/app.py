import argparse
import logging
import os
import signal
import sys
import threading
import time

import yaml

from verbal_code import __version__

logger = logging.getLogger("verbal_code")

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True


def load_config(path: str | None = None) -> dict:
    """Load config from explicit path, ~/.config/verbal-code/config.yaml, or ./config.yaml."""
    candidates = []
    if path:
        candidates.append(path)
    candidates.append(os.path.expanduser("~/.config/verbal-code/config.yaml"))
    candidates.append(os.path.join(os.getcwd(), "config.yaml"))

    for candidate in candidates:
        if os.path.isfile(candidate):
            with open(candidate, "r") as f:
                cfg = yaml.safe_load(f) or {}
            logger.debug("Loaded config from %s", candidate)
            return cfg

    logger.warning("No config file found, using defaults")
    return {}


def setup_logging(config: dict) -> None:
    log_cfg = config.get("logging", {})
    level = log_cfg.get("level", "INFO").upper()
    log_file = log_cfg.get("file")

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


class VerbalCode:
    MIN_AUDIO_SECONDS = 0.3

    def __init__(self, config: dict):
        from verbal_code.audio import AudioCapture
        from verbal_code.hotkeys import HotkeyListener
        from verbal_code.injector import TextProcessor, create_injector
        from verbal_code.transcriber import create_transcriber

        self.config = config
        audio_cfg = config.get("audio", {})
        hotkey_cfg = config.get("hotkey", {})

        self.capture = AudioCapture(
            sample_rate=audio_cfg.get("sample_rate", 16000),
            channels=audio_cfg.get("channels", 1),
            chunk_size=audio_cfg.get("chunk_size", 1024),
            device_index=audio_cfg.get("device"),
        )
        self.transcriber = create_transcriber(config)
        self.injector = create_injector(config)
        self.text_processor = TextProcessor()
        self.hotkey = HotkeyListener(
            modifiers=hotkey_cfg.get("modifiers", ["ctrl", "super", "alt"]),
            key=hotkey_cfg.get("key", "d"),
            on_activate=self._on_dictation_start,
            on_deactivate=self._on_dictation_stop,
        )
        self._dictation_lock = threading.Lock()
        self._recording = False
        self._record_start: float = 0

    def start(self) -> None:
        logger.info("Loading transcription model...")
        self.transcriber.load_model()
        self.hotkey.start()
        logger.info("Starting Verbal Code v%s", __version__)
        mods = "+".join(self.config.get("hotkey", {}).get("modifiers", ["ctrl", "super", "alt"]))
        key = self.config.get("hotkey", {}).get("key", "d")
        print(f"Verbal Code v{__version__} ready — hold {mods}+{key} to dictate")

    def stop(self) -> None:
        self.hotkey.stop()
        if self._recording:
            self.capture.stop()
        logger.info("Shutting down")

    def _on_dictation_start(self) -> None:
        with self._dictation_lock:
            if self._recording:
                return
            self._recording = True
            self._record_start = time.monotonic()
            self.text_processor.reset()
            self.transcriber.reset()
            self.capture.start()
            logger.info("Dictation started")

    def _on_dictation_stop(self) -> None:
        with self._dictation_lock:
            if not self._recording:
                return
            self._recording = False
            audio = self.capture.stop()
            duration = len(audio) / self.config.get("audio", {}).get("sample_rate", 16000)
            logger.info("Dictation stopped (%.2fs of audio)", duration)

        if duration < self.MIN_AUDIO_SECONDS:
            logger.info("Audio too short (%.2fs), skipping transcription", duration)
            return

        text = self.transcriber.transcribe_batch(audio)
        if not text.strip():
            logger.info("No speech detected")
            return

        text = self.text_processor.process(text)
        logger.info("Transcribed: %s", text)
        time.sleep(0.05)
        self.injector.inject(text)
        logger.info("Text injected")


def main():
    parser = argparse.ArgumentParser(
        prog="verbal-code",
        description="Voice-to-text input for Linux",
    )
    parser.add_argument("-c", "--config", help="Path to config.yaml")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument("--test-audio", action="store_true", help="Record 3 seconds of audio and save to WAV")
    parser.add_argument("--test-transcribe", action="store_true", help="Record 5 seconds, transcribe, and print result")
    parser.add_argument("--test-inject", action="store_true", help="Inject test text into focused window after 3s delay")
    parser.add_argument("--version", action="version", version=f"Verbal Code {__version__}")
    args = parser.parse_args()

    config = load_config(args.config)
    setup_logging(config)

    if args.list_devices:
        from verbal_code.audio import AudioCapture
        print(AudioCapture.list_devices())
        sys.exit(0)

    if args.test_audio:
        from verbal_code.audio import AudioCapture
        audio_cfg = config.get("audio", {})
        capture = AudioCapture(
            sample_rate=audio_cfg.get("sample_rate", 16000),
            channels=audio_cfg.get("channels", 1),
            chunk_size=audio_cfg.get("chunk_size", 1024),
            device_index=audio_cfg.get("device"),
        )
        print("Recording 3 seconds...")
        capture.start()
        time.sleep(3)
        audio = capture.stop()
        out_path = "/tmp/verbal_code_test.wav"
        AudioCapture.save_wav(out_path, audio, sample_rate=audio_cfg.get("sample_rate", 16000))
        duration = len(audio) / audio_cfg.get("sample_rate", 16000)
        print(f"Saved {duration:.2f}s of audio to {out_path}")
        sys.exit(0)

    if args.test_transcribe:
        from verbal_code.audio import AudioCapture
        from verbal_code.transcriber import create_transcriber

        audio_cfg = config.get("audio", {})
        capture = AudioCapture(
            sample_rate=audio_cfg.get("sample_rate", 16000),
            channels=audio_cfg.get("channels", 1),
            chunk_size=audio_cfg.get("chunk_size", 1024),
            device_index=audio_cfg.get("device"),
        )
        transcriber = create_transcriber(config)
        transcriber.load_model()
        print("Recording 5 seconds... speak now!")
        capture.start()
        time.sleep(5)
        audio = capture.stop()
        text = transcriber.transcribe_batch(audio)
        print(f"\nTranscription: {text}")
        sys.exit(0)

    if args.test_inject:
        from verbal_code.injector import create_injector
        injector = create_injector(config)
        print("Click into a text field... injecting in 3 seconds")
        time.sleep(3)
        injector.inject("Hello from Verbal Code! This is a test.")
        print("Done!")
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    app = VerbalCode(config)
    app.start()

    while not _shutdown:
        try:
            time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit):
            break

    app.stop()
