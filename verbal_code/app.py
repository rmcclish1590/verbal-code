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

# Brief pause before injection gives the focused window time to settle after the
# hotkey release so modifiers are not misinterpreted as part of the typed text.
_PRE_INJECT_DELAY_SECONDS = 0.05

_KNOWN_CONFIG_SECTIONS = {"hotkey", "stt", "audio", "injection", "vad", "tray", "logging"}

_shutdown = False


def _handle_signal(signum: int, frame: object) -> None:
    global _shutdown
    _shutdown = True


def load_config(path: str | None = None) -> dict:
    """Load config from an explicit path, the XDG location, or the CWD.

    Search order:
    1. ``path`` (if provided)
    2. ``~/.config/verbal-code/config.yaml``
    3. ``./config.yaml``
    """
    candidates: list[str] = []
    if path:
        candidates.append(path)
    candidates.append(os.path.expanduser("~/.config/verbal-code/config.yaml"))
    candidates.append(os.path.join(os.getcwd(), "config.yaml"))

    for candidate in candidates:
        if os.path.isfile(candidate):
            with open(candidate) as f:
                cfg = yaml.safe_load(f) or {}
            logger.debug("Loaded config from %s", candidate)
            return cfg

    logger.warning("No config file found, using defaults")
    return {}


def validate_config(config: dict) -> None:
    """Warn on unknown sections and verify the selected STT engine is installed.

    Exits with a non-zero status if the required STT library is missing, because
    the application cannot function at all without a transcription backend.
    """
    unknown = set(config.keys()) - _KNOWN_CONFIG_SECTIONS
    if unknown:
        logger.warning("Unknown config sections: %s", ", ".join(sorted(unknown)))

    for section in ("hotkey", "stt", "audio"):
        if section not in config:
            logger.warning("Missing config section '%s', using defaults", section)

    _assert_stt_engine_available(config.get("stt", {}).get("engine", "whisper"))


def _assert_stt_engine_available(engine: str) -> None:
    """Exit with a helpful message if the required STT package is not installed."""
    if engine == "whisper":
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            logger.error(
                "faster-whisper is not installed. Install it with:\n"
                "  pip install faster-whisper\n"
                "Or run ./install.sh to set up everything."
            )
            sys.exit(1)
    elif engine == "vosk":
        try:
            import vosk  # noqa: F401
        except ImportError:
            logger.error(
                "vosk is not installed. Install it with:\n"
                "  pip install vosk\n"
                "Or run ./install.sh to set up everything."
            )
            sys.exit(1)


def setup_logging(config: dict) -> None:
    """Configure the root logger from the ``logging`` section of ``config``."""
    log_cfg = config.get("logging", {})
    level = log_cfg.get("level", "INFO").upper()
    log_file: str | None = log_cfg.get("file")

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )


class VerbalCode:
    """Top-level application object that wires together all subsystems.

    Owns the audio capture, VAD, transcriber, text injector, hotkey listener,
    and system tray.  Dictation sessions are driven by hotkey callbacks that
    run on daemon threads.
    """

    MIN_AUDIO_SECONDS = 0.3

    def __init__(self, config: dict):
        # Deferred imports keep startup fast and avoid circular dependencies
        # at module load time — all subsystems import from each other indirectly.
        from verbal_code.audio import AudioCapture
        from verbal_code.hotkeys import HotkeyListener
        from verbal_code.injector import TextProcessor, create_injector
        from verbal_code.transcriber import create_transcriber
        from verbal_code.tray import SystemTray, TrayState
        from verbal_code.vad import VoiceActivityDetector

        self._TrayState = TrayState
        self.config = config

        audio_cfg = config.get("audio", {})
        hotkey_cfg = config.get("hotkey", {})
        tray_cfg = config.get("tray", {})
        vad_cfg = config.get("vad", {})

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
        self._tray_enabled: bool = tray_cfg.get("enabled", True)
        self.tray = SystemTray(
            on_quit=self._on_tray_quit,
            notifications=tray_cfg.get("notifications", True),
        )
        self._vad_enabled: bool = vad_cfg.get("enabled", True)
        self.vad = (
            VoiceActivityDetector(
                threshold=vad_cfg.get("threshold", 0.5),
                min_speech_ms=vad_cfg.get("min_speech_ms", 250),
                silence_ms=vad_cfg.get("silence_ms", 500),
                sample_rate=audio_cfg.get("sample_rate", 16000),
            )
            if self._vad_enabled
            else None
        )
        self._dictation_lock = threading.Lock()
        self._recording = False
        self._record_start: float = 0.0
        self._stream_stop = threading.Event()
        self._stream_thread: threading.Thread | None = None

    def start(self) -> None:
        """Load the model, start subsystems, and print the ready banner."""
        logger.info("Loading transcription model...")
        self.transcriber.load_model()
        if self._tray_enabled:
            self.tray.start()
        self.hotkey.start()
        logger.info("Starting Verbal Code v%s", __version__)
        hotkey_cfg = self.config.get("hotkey", {})
        mods = "+".join(hotkey_cfg.get("modifiers", ["ctrl", "super", "alt"]))
        key = hotkey_cfg.get("key", "d")
        print(f"Verbal Code v{__version__} ready \u2014 hold {mods}+{key} to dictate")

    def stop(self) -> None:
        """Gracefully shut down all subsystems."""
        self.hotkey.stop()
        if self._recording:
            self.capture.stop()
        if self._tray_enabled:
            self.tray.stop()
        logger.info("Shutting down")

    def _on_tray_quit(self) -> None:
        global _shutdown
        _shutdown = True

    def _on_dictation_start(self) -> None:
        with self._dictation_lock:
            if self._recording:
                return
            self._recording = True
            self._record_start = time.monotonic()
            self.text_processor.reset()
            self.transcriber.reset()
            if self.vad:
                self.vad.reset()
            self._stream_stop.clear()
            self.capture.start()
            self._stream_thread = threading.Thread(
                target=self._streaming_loop, daemon=True
            )
            self._stream_thread.start()
            self.tray.set_state(self._TrayState.LISTENING)
            logger.info("Dictation started")

    def _streaming_loop(self) -> None:
        while not self._stream_stop.is_set():
            chunk = self.capture.get_chunk(timeout=0.1)
            if chunk is None:
                continue

            if self.vad and self.vad.available:
                speech = self.vad.process_chunk(chunk)
                if speech is None:
                    continue
                chunk = speech

            for text in self.transcriber.transcribe_stream(chunk):
                if text:
                    logger.debug("[stream] %s", text)
                    # Uncomment to enable live injection of partial results:
                    # self.injector.inject(self.text_processor.process(text))

    def _on_dictation_stop(self) -> None:
        audio, duration = self._stop_recording()
        if audio is None:
            return

        if duration < self.MIN_AUDIO_SECONDS:
            logger.info("Audio too short (%.2fs), skipping transcription", duration)
            self.tray.set_state(self._TrayState.IDLE)
            return

        text = self._run_transcription(audio)
        if text is None:
            return

        self._inject_text(text)

    def _stop_recording(self) -> tuple[object, float]:
        """Stop the audio stream and streaming thread; return (audio, duration).

        Returns (None, 0.0) if no recording was active so callers can guard
        early without duplicating the lock check.
        """
        with self._dictation_lock:
            if not self._recording:
                return None, 0.0
            self._recording = False
            self._stream_stop.set()
            audio = self.capture.stop()
            sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)
            duration = len(audio) / sample_rate
            self.tray.set_state(self._TrayState.PROCESSING)
            logger.info("Dictation stopped (%.2fs of audio)", duration)

        if self._stream_thread is not None:
            self._stream_thread.join(timeout=2.0)
            self._stream_thread = None

        return audio, duration

    def _run_transcription(self, audio: object) -> str | None:
        """Run batch transcription; return the processed text or None on failure."""
        try:
            raw = self.transcriber.transcribe_batch(audio)  # type: ignore[arg-type]
        except Exception as exc:
            logger.error("Transcription failed: %s", exc)
            self.tray.set_state(self._TrayState.ERROR)
            self.tray.notify("Verbal Code", "Transcription failed \u2014 check logs for details")
            return None

        if not raw.strip():
            logger.info("No speech detected")
            self.tray.set_state(self._TrayState.IDLE)
            return None

        text = self.text_processor.process(raw)
        logger.info("Transcribed: %s", text)
        return text

    def _inject_text(self, text: str) -> None:
        """Inject ``text`` into the focused window after a brief settle delay."""
        time.sleep(_PRE_INJECT_DELAY_SECONDS)
        try:
            self.injector.inject(text)
            logger.info("Text injected")
            self.tray.set_state(self._TrayState.IDLE)
        except Exception as exc:
            logger.error("Injection failed: %s", exc)
            self.tray.set_state(self._TrayState.ERROR)
            self.tray.notify("Verbal Code", "Injection failed \u2014 check logs for details")


# ---------------------------------------------------------------------------
# CLI helpers — each --test-* branch is extracted into its own function so
# main() stays within the 30-line limit and each scenario is independently
# testable.
# ---------------------------------------------------------------------------


def _run_list_devices() -> None:
    from verbal_code.audio import AudioCapture

    print(AudioCapture.list_devices())


def _run_test_audio(config: dict) -> None:
    from verbal_code.audio import AudioCapture

    audio_cfg = config.get("audio", {})
    sample_rate: int = audio_cfg.get("sample_rate", 16000)
    capture = AudioCapture(
        sample_rate=sample_rate,
        channels=audio_cfg.get("channels", 1),
        chunk_size=audio_cfg.get("chunk_size", 1024),
        device_index=audio_cfg.get("device"),
    )
    print("Recording 3 seconds...")
    capture.start()
    time.sleep(3)
    audio = capture.stop()
    out_path = "/tmp/verbal_code_test.wav"
    AudioCapture.save_wav(out_path, audio, sample_rate=sample_rate)
    print(f"Saved {len(audio) / sample_rate:.2f}s of audio to {out_path}")


def _run_test_transcribe(config: dict) -> None:
    from verbal_code.audio import AudioCapture
    from verbal_code.transcriber import create_transcriber

    audio_cfg = config.get("audio", {})
    sample_rate: int = audio_cfg.get("sample_rate", 16000)
    capture = AudioCapture(
        sample_rate=sample_rate,
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
    print(f"\nTranscription: {transcriber.transcribe_batch(audio)}")


def _run_test_inject(config: dict) -> None:
    from verbal_code.injector import create_injector

    injector = create_injector(config)
    print("Click into a text field... injecting in 3 seconds")
    time.sleep(3)
    injector.inject("Hello from Verbal Code! This is a test.")
    print("Done!")


def _build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verbal-code",
        description="Voice-to-text input for Linux",
    )
    parser.add_argument("-c", "--config", help="Path to config.yaml")
    parser.add_argument(
        "--list-devices", action="store_true", help="List audio devices and exit"
    )
    parser.add_argument(
        "--test-audio",
        action="store_true",
        help="Record 3 seconds of audio and save to WAV",
    )
    parser.add_argument(
        "--test-transcribe",
        action="store_true",
        help="Record 5 seconds, transcribe, and print result",
    )
    parser.add_argument(
        "--test-inject",
        action="store_true",
        help="Inject test text into focused window after 3s delay",
    )
    parser.add_argument(
        "--version", action="version", version=f"Verbal Code {__version__}"
    )
    return parser


def main() -> None:
    """Entry point: parse arguments, dispatch diagnostic modes, or run the app."""
    args = _build_argument_parser().parse_args()
    config = load_config(args.config)
    setup_logging(config)

    if args.list_devices:
        _run_list_devices()
        sys.exit(0)
    if args.test_audio:
        _run_test_audio(config)
        sys.exit(0)
    if args.test_transcribe:
        _run_test_transcribe(config)
        sys.exit(0)
    if args.test_inject:
        _run_test_inject(config)
        sys.exit(0)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)
    validate_config(config)

    try:
        app = VerbalCode(config)
        app.start()
    except Exception as exc:
        logger.error("Failed to start: %s", exc)
        sys.exit(1)

    while not _shutdown:
        try:
            time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit):
            break

    app.stop()
