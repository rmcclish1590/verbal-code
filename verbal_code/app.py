import argparse
import logging
import os
import signal
import sys
import tempfile
import threading
import time

import yaml

from verbal_code import __version__

logger = logging.getLogger("verbal_code")

# Brief pause before injection gives the focused window time to settle after the
# hotkey release so modifiers are not misinterpreted as part of the typed text.
_PRE_INJECT_DELAY_SECONDS = 0.05

_KNOWN_CONFIG_SECTIONS = {"hotkey", "stt", "audio", "injection", "vad", "tray", "logging"}

# Single source of truth for the default hotkey, matching config.yaml and README.
DEFAULT_HOTKEY_MODIFIERS = ["super", "alt"]
DEFAULT_HOTKEY_KEY = "space"

_shutdown = False


def _handle_signal(signum: int, frame: object) -> None:
    global _shutdown
    _shutdown = True


def _config_candidates(path: str | None = None) -> list[str]:
    """Return the ordered list of config file paths to search."""
    candidates: list[str] = []
    if path:
        candidates.append(path)
    candidates.append(os.path.expanduser("~/.config/verbal-code/config.yaml"))
    candidates.append(os.path.join(os.getcwd(), "config.yaml"))
    return candidates


def resolve_config_path(path: str | None = None) -> str | None:
    """Return the path to the first config file found, or ``None``."""
    for candidate in _config_candidates(path):
        if os.path.isfile(candidate):
            return candidate
    return None


def load_config(path: str | None = None) -> dict:
    """Load config from an explicit path, the XDG location, or the CWD.

    Search order:
    1. ``path`` (if provided)
    2. ``~/.config/verbal-code/config.yaml``
    3. ``./config.yaml``
    """
    for candidate in _config_candidates(path):
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

    engine = config.get("stt", {}).get("engine", "whisper")
    _assert_stt_engine_available(engine)
    _assert_numeric_values(config)
    _assert_sample_rate_supported(engine, config)


# (section path, key, expected type, min, max) — bounds are inclusive. Values
# outside these ranges either crash the subsystems or exhaust resources
# (e.g. a huge chunk_size or beam_size).
_NUMERIC_CONFIG_BOUNDS: list[tuple[tuple[str, ...], str, type | tuple, float, float]] = [
    (("audio",), "sample_rate", int, 8000, 192000),
    (("audio",), "channels", int, 1, 8),
    (("audio",), "chunk_size", int, 64, 65536),
    (("stt", "whisper"), "beam_size", int, 1, 20),
    (("stt", "whisper"), "batch_size", int, 1, 64),
    (("injection",), "delay_ms", int, 0, 1000),
    (("vad",), "trim_threshold_db", (int, float), -120, 0),
]


def _assert_numeric_values(config: dict) -> None:
    """Exit with a clear message when a numeric config value is unusable."""
    for path, key, expected, low, high in _NUMERIC_CONFIG_BOUNDS:
        section: object = config
        for part in path:
            section = section.get(part, {}) if isinstance(section, dict) else {}
        if not isinstance(section, dict) or key not in section:
            continue

        value = section[key]
        dotted = ".".join((*path, key))
        kind = "an integer" if expected is int else "a number"
        if isinstance(value, bool) or not isinstance(value, expected):
            logger.error("%s must be %s, got %r", dotted, kind, value)
            sys.exit(1)
        if not low <= value <= high:
            logger.error(
                "%s is %s, outside the supported range %s to %s",
                dotted, value, low, high,
            )
            sys.exit(1)


def _assert_sample_rate_supported(engine: str, config: dict) -> None:
    """Exit if the configured capture rate cannot work with the STT engine.

    faster-whisper interprets raw numpy input as 16 kHz and does not resample,
    so any other capture rate produces silently garbled transcriptions.
    """
    sample_rate = config.get("audio", {}).get("sample_rate", 16000)
    if engine == "whisper" and sample_rate != 16000:
        logger.error(
            "audio.sample_rate is %d, but the whisper engine requires 16000. "
            "Set audio.sample_rate: 16000 (or switch to the vosk engine).",
            sample_rate,
        )
        sys.exit(1)


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
    elif engine == "moonshine":
        try:
            import moonshine_onnx  # noqa: F401
        except ImportError:
            logger.error(
                "moonshine is not installed. Install it with:\n"
                "  pip install useful-moonshine-onnx\n"
                "Or run ./install.sh to set up everything."
            )
            sys.exit(1)


_LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"


def _resolve_log_file(path: object) -> str | None:
    """Return a usable log file path, or None if the value is unsafe.

    The path is user-controlled config; expanding ``~`` and refusing
    symlinks/directories keeps a crafted value from redirecting log writes
    onto an arbitrary file, and a missing parent directory becomes a warning
    instead of a FileHandler traceback.
    """
    resolved = os.path.expanduser(str(path))
    if os.path.islink(resolved):
        logger.warning("logging.file %r is a symlink; file logging disabled", path)
        return None
    if os.path.isdir(resolved):
        logger.warning("logging.file %r is a directory; file logging disabled", path)
        return None
    parent = os.path.dirname(resolved) or "."
    if not os.path.isdir(parent):
        logger.warning(
            "logging.file directory %r does not exist; file logging disabled", parent
        )
        return None
    return resolved


def setup_logging(config: dict) -> None:
    """Configure the root logger from the ``logging`` section of ``config``.

    Console logging is configured first so problems with ``logging.file``
    can be reported; an unusable file path degrades to console-only logging
    rather than aborting startup.
    """
    log_cfg = config.get("logging", {})
    level = log_cfg.get("level", "INFO").upper()

    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format=_LOG_FORMAT,
        handlers=[logging.StreamHandler(sys.stderr)],
        force=True,
    )

    log_file = log_cfg.get("file")
    if not log_file:
        return
    resolved = _resolve_log_file(log_file)
    if resolved is None:
        return
    try:
        handler = logging.FileHandler(resolved)
    except OSError as exc:
        logger.warning("Cannot open logging.file %r: %s", log_file, exc)
        return
    handler.setFormatter(logging.Formatter(_LOG_FORMAT))
    logging.getLogger().addHandler(handler)


class VerbalCode:
    """Top-level application object that wires together all subsystems.

    Owns the audio capture, transcriber, text injector, hotkey listener, and
    system tray.  A dictation session records audio while the hotkey is held
    and transcribes it in a single batched pass on release.
    """

    MIN_AUDIO_SECONDS = 0.3

    def __init__(self, config: dict, config_path: str | None = None):
        # Deferred imports keep startup fast and avoid circular dependencies
        # at module load time — all subsystems import from each other indirectly.
        from verbal_code.audio import AudioCapture
        from verbal_code.hotkeys import HotkeyListener
        from verbal_code.injector import TextProcessor, create_injector
        from verbal_code.transcriber import create_transcriber
        from verbal_code.tray import SystemTray, TrayState

        self._TrayState = TrayState
        self.config = config
        self._config_path = config_path or os.path.expanduser(
            "~/.config/verbal-code/config.yaml"
        )

        audio_cfg = config.get("audio", {})
        hotkey_cfg = config.get("hotkey", {})
        stt_cfg = config.get("stt", {})
        tray_cfg = config.get("tray", {})
        vad_cfg = config.get("vad", {})

        # Energy-based trim of leading/trailing silence before batch
        # transcription. Whisper's built-in vad_filter would cope without it,
        # but Vosk and Moonshine receive the raw capture otherwise.
        self._trim_silence_enabled: bool = vad_cfg.get("trim_silence", True)
        self._trim_threshold_db: float = vad_cfg.get("trim_threshold_db", -40.0)

        # With the vosk engine, streaming injects each utterance live as it
        # finalises. Off by default: batch transcription on hotkey release
        # covers normal dictation without the per-interval inference cost
        # while recording.
        self._streaming_enabled: bool = stt_cfg.get("streaming_enabled", False)

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
            modifiers=hotkey_cfg.get("modifiers", DEFAULT_HOTKEY_MODIFIERS),
            key=hotkey_cfg.get("key", DEFAULT_HOTKEY_KEY),
            on_activate=self._on_dictation_start,
            on_deactivate=self._on_dictation_stop,
        )
        self._tray_enabled: bool = tray_cfg.get("enabled", True)
        self.tray = SystemTray(
            on_quit=self._on_tray_quit,
            on_hotkeys=self._on_hotkeys_requested,
            notifications=tray_cfg.get("notifications", True),
        )
        self._dictation_lock = threading.Lock()
        self._recording = False
        self._record_start: float = 0.0

        self._stream_stop = threading.Event()
        self._stream_thread: threading.Thread | None = None
        # Live injection needs stream text the engine will never revise;
        # engines with revisable partials (Whisper) keep streaming log-only
        # and rely on batch transcription at release.
        self._live_injection: bool = (
            self._streaming_enabled and self.transcriber.supports_live_streaming
        )
        if self._streaming_enabled and not self._live_injection:
            logger.info(
                "stt.streaming_enabled is on, but the configured engine only "
                "produces revisable partial results; text is still injected "
                "in one batch on hotkey release (use the vosk engine for "
                "live injection)."
            )

    def start(self) -> None:
        """Load the model, start subsystems, and print the ready banner."""
        logger.info("Loading transcription model...")
        self.transcriber.load_model()
        if self._tray_enabled:
            self.tray.start()
        self.hotkey.start()
        logger.info("Starting Verbal Code v%s", __version__)
        hotkey_cfg = self.config.get("hotkey", {})
        mods = "+".join(hotkey_cfg.get("modifiers", DEFAULT_HOTKEY_MODIFIERS))
        key = hotkey_cfg.get("key", DEFAULT_HOTKEY_KEY)
        print(f"Verbal Code v{__version__} ready \u2014 hold {mods}+{key} to dictate")

    def stop(self) -> None:
        """Gracefully shut down all subsystems."""
        self.hotkey.stop()
        self._join_stream_thread()
        if self._recording:
            self.capture.stop()
        if self._tray_enabled:
            self.tray.stop()
        logger.info("Shutting down")

    def _on_tray_quit(self) -> None:
        global _shutdown
        _shutdown = True

    def _on_hotkeys_requested(self) -> None:
        from verbal_code.hotkey_editor import HotkeyEditorWindow

        hotkey_cfg = self.config.get("hotkey", {})
        editor = HotkeyEditorWindow(
            gtk=self.tray._gtk,
            gdk=self.tray._gdk,
            current_modifiers=hotkey_cfg.get("modifiers", DEFAULT_HOTKEY_MODIFIERS),
            current_key=hotkey_cfg.get("key", DEFAULT_HOTKEY_KEY),
            config_path=self._config_path,
            on_save=self._on_hotkey_saved,
            on_recording_start=self.hotkey.stop,
            on_recording_stop=self.hotkey.start,
        )
        editor.show()

    def _on_hotkey_saved(self, modifiers: list[str], key: str) -> None:
        from verbal_code.hotkeys import HotkeyListener

        self.hotkey.stop()
        self.config.setdefault("hotkey", {})["modifiers"] = modifiers
        self.config["hotkey"]["key"] = key
        self.hotkey = HotkeyListener(
            modifiers=modifiers,
            key=key,
            on_activate=self._on_dictation_start,
            on_deactivate=self._on_dictation_stop,
        )
        self.hotkey.start()
        mods_str = "+".join(modifiers)
        logger.info("Hotkey updated to %s+%s", mods_str, key)
        self.tray.notify("Verbal Code", f"Hotkey changed to {mods_str}+{key}")

    def _on_dictation_start(self) -> None:
        with self._dictation_lock:
            if self._recording:
                return
            self._recording = True
            self._record_start = time.monotonic()
            self.text_processor.reset()
            self.transcriber.reset()
            self.capture.start()
            if self._streaming_enabled:
                self._stream_stop.clear()
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
            self._emit_stream_text(chunk)
        # Chunks captured before the stop request may still be queued; feed
        # them through so the end of the dictation isn't lost.
        for chunk in self.capture.get_all_chunks():
            self._emit_stream_text(chunk)

    def _emit_stream_text(self, chunk: object) -> None:
        for text in self.transcriber.transcribe_stream(chunk):  # type: ignore[arg-type]
            if not text:
                continue
            logger.debug("[stream] %s", text)
            if self._live_injection:
                self._inject_stream_text(text)

    def _inject_stream_text(self, text: str) -> None:
        """Inject one finalised stream utterance into the focused window."""
        try:
            self.injector.inject(self.text_processor.process(text))
        except Exception as exc:
            logger.error("Live injection failed: %s", exc)

    def _on_dictation_stop(self) -> None:
        audio, duration = self._stop_recording()
        if audio is None:
            return

        self._join_stream_thread()

        if self._live_injection:
            self._finish_live_dictation()
            return

        if duration < self.MIN_AUDIO_SECONDS:
            logger.info("Audio too short (%.2fs), skipping transcription", duration)
            self.tray.set_state(self._TrayState.IDLE)
            return

        audio = self._trim_batch_audio(audio, duration)
        if audio is None:
            return

        text = self._run_transcription(audio)
        if text is None:
            return

        self._inject_text(text)

    def _join_stream_thread(self) -> None:
        """Stop the per-session streaming thread and wait for it to drain."""
        if self._stream_thread is None:
            return
        self._stream_stop.set()
        self._stream_thread.join(timeout=5.0)
        if self._stream_thread.is_alive():
            logger.warning("Streaming thread did not stop within timeout")
        self._stream_thread = None

    def _finish_live_dictation(self) -> None:
        """Flush and inject the stream tail; everything else already landed live."""
        try:
            tail = self.transcriber.stream_finalize()
        except Exception as exc:
            logger.error("Stream finalize failed: %s", exc)
            self.tray.set_state(self._TrayState.ERROR)
            return
        if tail.strip():
            self._inject_text(self.text_processor.process(tail))
        else:
            self.tray.set_state(self._TrayState.IDLE)

    def _stop_recording(self) -> tuple[object, float]:
        """Stop the audio stream and return (audio, duration).

        Returns (None, 0.0) if no recording was active so callers can guard
        early without duplicating the lock check.
        """
        with self._dictation_lock:
            if not self._recording:
                return None, 0.0
            self._recording = False
            audio = self.capture.stop()
            sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)
            duration = len(audio) / sample_rate
            self.tray.set_state(self._TrayState.PROCESSING)
            logger.info("Dictation stopped (%.2fs of audio)", duration)

        return audio, duration

    def _trim_batch_audio(self, audio: object, duration: float) -> object | None:
        """Trim leading/trailing silence before batch transcription.

        Returns None (and resets the tray) when the recording contains no
        audible speech at all, so callers can skip transcription entirely.
        """
        if not self._trim_silence_enabled:
            return audio

        from verbal_code.audio import trim_silence

        sample_rate = self.config.get("audio", {}).get("sample_rate", 16000)
        trimmed = trim_silence(
            audio,  # type: ignore[arg-type]
            sample_rate,
            threshold_db=self._trim_threshold_db,
        )
        if len(trimmed) == 0:
            logger.info("No speech detected (recording below silence threshold)")
            self.tray.set_state(self._TrayState.IDLE)
            return None

        trimmed_duration = len(trimmed) / sample_rate
        if trimmed_duration < duration:
            logger.info(
                "Trimmed silence: %.2fs -> %.2fs", duration, trimmed_duration
            )
        return trimmed

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
    # mkstemp creates a fresh file we own — a fixed /tmp name could be a
    # symlink planted by another user, redirecting the write.
    fd, out_path = tempfile.mkstemp(prefix="verbal_code_test_", suffix=".wav")
    os.close(fd)
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

    # Validate before the remaining diagnostic modes so a missing STT package
    # produces the friendly install hint instead of a raw traceback.
    validate_config(config)

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

    config_path = resolve_config_path(args.config)

    try:
        app = VerbalCode(config, config_path=config_path)
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
