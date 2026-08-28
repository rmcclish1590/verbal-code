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

_KNOWN_CONFIG_SECTIONS = {
    "hotkey",
    "stt",
    "audio",
    "injection",
    "vad",
    "tray",
    "logging",
}

# Single source of truth for the default hotkey, matching config.yaml and README.
DEFAULT_HOTKEY_MODIFIERS = ["super", "alt"]
DEFAULT_HOTKEY_KEY = "space"

_KNOWN_MODIFIERS = {"ctrl", "alt", "shift", "super", "meta"}

# Engines create_transcriber() can actually build; anything else would
# silently fall through to the whisper branch there.
_KNOWN_STT_ENGINES = ("whisper", "vosk", "moonshine")


def resolve_hotkey_config(config: dict) -> tuple[list[str], str]:
    """Return the saved (modifiers, key), or the defaults if unusable.

    A hand-edited or out-of-date config must never leave the app without a
    working hotkey, so anything malformed — modifiers that aren't a list of
    known modifier names, a key that isn't a non-empty string — falls back to
    the default combo with a warning instead of breaking startup.
    """
    hotkey_cfg = config.get("hotkey", {})
    modifiers = hotkey_cfg.get("modifiers", DEFAULT_HOTKEY_MODIFIERS)
    key = hotkey_cfg.get("key", DEFAULT_HOTKEY_KEY)

    valid_modifiers = (
        isinstance(modifiers, list)
        and len(modifiers) > 0
        and all(
            isinstance(m, str) and m.lower() in _KNOWN_MODIFIERS for m in modifiers
        )
    )
    valid_key = isinstance(key, str) and bool(key.strip())
    if not (valid_modifiers and valid_key):
        logger.warning(
            "Saved hotkey config is invalid (modifiers=%r, key=%r); "
            "falling back to the default %s+%s",
            modifiers,
            key,
            "+".join(DEFAULT_HOTKEY_MODIFIERS),
            DEFAULT_HOTKEY_KEY,
        )
        return list(DEFAULT_HOTKEY_MODIFIERS), DEFAULT_HOTKEY_KEY

    return [m.lower() for m in modifiers], key.strip().lower()

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
    if engine not in _KNOWN_STT_ENGINES:
        logger.error(
            "stt.engine must be one of %s, got %r",
            ", ".join(f"'{e}'" for e in _KNOWN_STT_ENGINES),
            engine,
        )
        sys.exit(1)
    _assert_stt_engine_available(engine)
    _assert_numeric_values(config)
    _assert_sample_rate_supported(engine, config)

    mode = config.get("hotkey", {}).get("mode", "hold")
    if mode not in ("hold", "toggle"):
        logger.error("hotkey.mode must be 'hold' or 'toggle', got %r", mode)
        sys.exit(1)


# (section path, key, expected type, min, max) — bounds are inclusive. Values
# outside these ranges either crash the subsystems or exhaust resources
# (e.g. a huge chunk_size or beam_size).
_BoundSpec = tuple[tuple[str, ...], str, "type | tuple", float, float]
_NUMERIC_CONFIG_BOUNDS: list[_BoundSpec] = [
    (("audio",), "sample_rate", int, 8000, 192000),
    (("audio",), "channels", int, 1, 8),
    (("audio",), "chunk_size", int, 64, 65536),
    (("audio",), "max_seconds", (int, float), 0, 86400),
    (("stt", "whisper"), "beam_size", int, 1, 20),
    (("stt", "whisper"), "batch_size", int, 1, 64),
    (("injection",), "delay_ms", int, 0, 1000),
    (("injection",), "clipboard_threshold", int, 0, 100000),
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
    # The log file may capture transcript text when transcript logging is
    # enabled, so keep it readable by the owner only.
    try:
        os.chmod(resolved, 0o600)
    except OSError as exc:
        logger.warning("Could not restrict permissions on %r: %s", resolved, exc)
    logging.getLogger().addHandler(handler)


class VerbalCode:
    """Top-level application object that wires together all subsystems.

    Owns the audio capture, transcriber, text injector, hotkey listener, and
    system tray.  A dictation session records audio while the hotkey is held
    and transcribes it in a single batched pass on release.
    """

    MIN_AUDIO_SECONDS = 0.3
    # Recording accumulates float32 audio in memory (~3.8 MB/min); an
    # unattended toggle-mode session would otherwise grow without bound.
    DEFAULT_MAX_RECORD_SECONDS = 300.0

    def __init__(self, config: dict, config_path: str | None = None):
        # Deferred imports keep startup fast and avoid circular dependencies
        # at module load time — all subsystems import from each other indirectly.
        from verbal_code.audio import AudioCapture
        from verbal_code.hotkeys import create_hotkey_listener
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
        self._hotkey_mode: str = hotkey_cfg.get("mode", "hold")
        # Saved (or default) combo, validated once; every consumer — listener,
        # ready banner, hotkey editor — uses these so they can't disagree.
        self._hotkey_modifiers, self._hotkey_key = resolve_hotkey_config(config)
        stt_cfg = config.get("stt", {})
        tray_cfg = config.get("tray", {})
        vad_cfg = config.get("vad", {})

        # Dictated text can contain anything the user speaks (passwords,
        # personal details), so transcript content stays out of the logs
        # unless explicitly opted in; only metadata is logged by default.
        self._log_transcripts: bool = bool(
            config.get("logging", {}).get("log_transcripts", False)
        )

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
        self.text_processor = TextProcessor(
            punctuation_commands=config.get("injection", {}).get(
                "punctuation_commands", True
            )
        )
        self.hotkey = create_hotkey_listener(
            modifiers=self._hotkey_modifiers,
            key=self._hotkey_key,
            on_activate=self._on_hotkey_pressed,
            on_deactivate=self._on_hotkey_released,
        )
        self._tray_enabled: bool = tray_cfg.get("enabled", True)
        from verbal_code.transcriber import (
            AVAILABLE_MODELS,
            current_selection,
            installed_engines,
        )

        model_menu = [
            (engine, AVAILABLE_MODELS[engine])
            for engine in installed_engines()
            if engine in AVAILABLE_MODELS
        ]
        self.tray = SystemTray(
            on_quit=self._on_tray_quit,
            on_hotkeys=self._on_hotkeys_requested,
            notifications=tray_cfg.get("notifications", True),
            on_model_selected=self._on_model_requested,
            model_menu=model_menu,
            current_model=current_selection(config),
        )
        self._model_switch_lock = threading.Lock()
        self._dictation_lock = threading.Lock()
        self._recording = False
        self._record_start: float = 0.0
        # Watchdog that stops a dictation left recording past
        # audio.max_seconds (0 disables the cap).
        self._max_record_seconds: float = audio_cfg.get(
            "max_seconds", self.DEFAULT_MAX_RECORD_SECONDS
        )
        self._max_record_timer: threading.Timer | None = None

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
                "produces revisable partial results, so streaming is skipped "
                "entirely; text is transcribed and injected in one batch on "
                "hotkey release (use the vosk engine for live injection)."
            )

    def start(self) -> None:
        """Load the model, start subsystems, and print the ready banner."""
        logger.info("Loading transcription model...")
        self.transcriber.load_model()
        if self._tray_enabled:
            self.tray.start()
        self.hotkey.start()
        logger.info("Starting Verbal Code v%s", __version__)
        mods = "+".join(self._hotkey_modifiers)
        key = self._hotkey_key
        if self._hotkey_mode == "toggle":
            action = f"press {mods}+{key} to start/stop dictation"
        else:
            action = f"hold {mods}+{key} to dictate"
        print(f"Verbal Code v{__version__} ready \u2014 {action}")

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

        editor = HotkeyEditorWindow(
            gtk=self.tray._gtk,
            gdk=self.tray._gdk,
            current_modifiers=self._hotkey_modifiers,
            current_key=self._hotkey_key,
            config_path=self._config_path,
            on_save=self._on_hotkey_saved,
            on_recording_start=self.hotkey.stop,
            on_recording_stop=self.hotkey.start,
        )
        editor.show()

    def _on_hotkey_saved(self, modifiers: list[str], key: str) -> None:
        from verbal_code.hotkeys import create_hotkey_listener

        self.hotkey.stop()
        self.config.setdefault("hotkey", {})["modifiers"] = modifiers
        self.config["hotkey"]["key"] = key
        self._hotkey_modifiers, self._hotkey_key = modifiers, key
        self.hotkey = create_hotkey_listener(
            modifiers=modifiers,
            key=key,
            on_activate=self._on_hotkey_pressed,
            on_deactivate=self._on_hotkey_released,
        )
        self.hotkey.start()
        mods_str = "+".join(modifiers)
        logger.info("Hotkey updated to %s+%s", mods_str, key)
        self.tray.notify("Verbal Code", f"Hotkey changed to {mods_str}+{key}")

    def _on_model_requested(self, engine: str, model: str) -> None:
        """Tray callback: switch models off the GTK thread."""
        threading.Thread(
            target=self._switch_model, args=(engine, model), daemon=True
        ).start()

    def _switch_model(self, engine: str, model: str) -> None:
        """Load the requested engine/model, swap it in, and persist the choice."""
        import copy

        from verbal_code.transcriber import apply_selection, create_transcriber

        if self._recording:
            self.tray.notify(
                "Verbal Code", "Finish the current dictation before switching models"
            )
            return
        if not self._model_switch_lock.acquire(blocking=False):
            return
        try:
            self.tray.set_state(self._TrayState.PROCESSING)
            self.tray.notify("Verbal Code", f"Loading {engine} ({model})...")
            # Build the new transcriber from a config copy so self.config only
            # changes if the swap actually commits below.
            new_config = copy.deepcopy(self.config)
            apply_selection(new_config, engine, model)
            transcriber = create_transcriber(new_config)
            transcriber.load_model()
            # Commit under the dictation lock: a dictation started while the
            # model was loading must finish on the transcriber it began with,
            # never have the engine swapped out mid-session (MCC-44).
            with self._dictation_lock:
                if self._recording:
                    logger.info(
                        "Dictation started during model load; switch to "
                        "%s (%s) cancelled",
                        engine,
                        model,
                    )
                    self.tray.set_state(self._TrayState.LISTENING)
                    self.tray.notify(
                        "Verbal Code",
                        "Dictation in progress — model switch cancelled, "
                        "try again",
                    )
                    return
                apply_selection(self.config, engine, model)
                self.transcriber = transcriber
                self._live_injection = (
                    self._streaming_enabled and transcriber.supports_live_streaming
                )
            self._save_stt_selection(engine, model)
            self.tray.set_model(engine, model)
            self.tray.set_state(self._TrayState.IDLE)
            self.tray.notify("Verbal Code", f"Now using {engine} ({model})")
            logger.info("Switched STT to %s (%s)", engine, model)
        except Exception as exc:
            logger.error("Model switch to %s (%s) failed: %s", engine, model, exc)
            self.tray.set_state(self._TrayState.ERROR)
            self.tray.notify("Verbal Code", "Model switch failed — check logs")
        finally:
            self._model_switch_lock.release()

    def _save_stt_selection(self, engine: str, model: str) -> None:
        """Persist the engine/model choice to the config file."""
        from verbal_code.config_store import update_config
        from verbal_code.transcriber import apply_selection

        try:
            update_config(
                self._config_path,
                lambda cfg: apply_selection(cfg, engine, model),
            )
            logger.info("STT selection saved to %s", self._config_path)
        except Exception as exc:
            logger.warning("Could not persist model choice: %s", exc)

    def _on_hotkey_pressed(self) -> None:
        """Dispatch a hotkey press according to hotkey.mode.

        Hold mode starts recording (release stops it); toggle mode starts on
        one press and stops on the next, so long dictations don't require
        holding the chord.
        """
        if self._hotkey_mode == "toggle" and self._recording:
            self._on_dictation_stop()
        else:
            self._on_dictation_start()

    def _on_hotkey_released(self) -> None:
        if self._hotkey_mode == "hold":
            self._on_dictation_stop()

    def _on_dictation_start(self) -> None:
        with self._dictation_lock:
            if self._recording:
                return
            self._recording = True
            self._record_start = time.monotonic()
            self.text_processor.reset()
            self.transcriber.reset()
            self.capture.start()
            # Streaming only runs when its text can be injected live. For
            # engines with revisable partials (Whisper) it would re-transcribe
            # the whole session every interval — O(n²) CPU — to produce
            # nothing but debug logs, so the batch pass on release covers
            # them instead (MCC-42).
            if self._live_injection:
                self._stream_stop.clear()
                self._stream_thread = threading.Thread(
                    target=self._streaming_loop, daemon=True
                )
                self._stream_thread.start()
            if self._max_record_seconds > 0:
                self._max_record_timer = threading.Timer(
                    self._max_record_seconds, self._on_max_duration_reached
                )
                self._max_record_timer.daemon = True
                self._max_record_timer.start()
            self.tray.set_state(self._TrayState.LISTENING)
            logger.info("Dictation started")

    def _on_max_duration_reached(self) -> None:
        """Watchdog: stop a dictation that has hit ``audio.max_seconds``.

        Guards against a forgotten toggle-mode session growing the in-memory
        capture buffer without bound; the audio recorded so far is still
        transcribed and injected normally.
        """
        if not self._recording:
            return
        logger.warning(
            "Recording reached audio.max_seconds (%.0fs); stopping dictation",
            self._max_record_seconds,
        )
        self.tray.notify(
            "Verbal Code", "Maximum recording length reached — transcribing"
        )
        self._on_dictation_stop()

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
            if self._log_transcripts:
                logger.debug("[stream] %s", text)
            else:
                logger.debug("[stream] %d chars", len(text))
            if self._live_injection:
                self._inject_stream_text(text)

    def _inject_stream_text(self, text: str) -> None:
        """Inject one finalised stream utterance into the focused window."""
        try:
            self.injector.inject(self.text_processor.process(text))
        except Exception as exc:
            logger.error("Live injection failed: %s", exc)

    def _on_dictation_stop(self) -> None:
        # Timer for the release→text-on-screen latency metric; this handler
        # runs the moment the hotkey is released.
        released_at = time.monotonic()

        audio, duration = self._stop_recording()
        if audio is None:
            return

        self._join_stream_thread()

        if self._live_injection:
            if self._finish_live_dictation():
                self._log_dictation_latency(released_at)
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

        if self._inject_text(text):
            self._log_dictation_latency(released_at)

    def _log_dictation_latency(self, released_at: float) -> None:
        """Log the hotkey-release→injection-complete latency for this cycle."""
        elapsed_ms = int((time.monotonic() - released_at) * 1000)
        logger.info("dictation_latency_ms=%d", elapsed_ms)

    def _join_stream_thread(self) -> None:
        """Stop the per-session streaming thread and wait for it to drain."""
        if self._stream_thread is None:
            return
        self._stream_stop.set()
        self._stream_thread.join(timeout=5.0)
        if self._stream_thread.is_alive():
            logger.warning("Streaming thread did not stop within timeout")
        self._stream_thread = None

    def _finish_live_dictation(self) -> bool:
        """Flush and inject the stream tail; everything else already landed live.

        Returns True when the cycle completed (with or without a tail to
        inject), False on failure — the caller uses this for the latency log.
        """
        try:
            tail = self.transcriber.stream_finalize()
        except Exception as exc:
            logger.error("Stream finalize failed: %s", exc)
            self.tray.set_state(self._TrayState.ERROR)
            return False
        if tail.strip():
            return self._inject_text(self.text_processor.process(tail))
        self.tray.set_state(self._TrayState.IDLE)
        return True

    def _stop_recording(self) -> tuple[object, float]:
        """Stop the audio stream and return (audio, duration).

        Returns (None, 0.0) if no recording was active so callers can guard
        early without duplicating the lock check.
        """
        with self._dictation_lock:
            if not self._recording:
                return None, 0.0
            self._recording = False
            if self._max_record_timer is not None:
                self._max_record_timer.cancel()
                self._max_record_timer = None
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
            self.tray.notify(
                "Verbal Code", "Transcription failed \u2014 check logs for details"
            )
            return None

        if not raw.strip():
            logger.info("No speech detected")
            self.tray.set_state(self._TrayState.IDLE)
            return None

        text = self.text_processor.process(raw)
        if self._log_transcripts:
            logger.info("Transcribed: %s", text)
        else:
            logger.info("Transcribed %d chars", len(text))
        return text

    def _inject_text(self, text: str) -> bool:
        """Inject ``text`` into the focused window after a brief settle delay.

        Returns True when the injection completed, False on failure.
        """
        time.sleep(_PRE_INJECT_DELAY_SECONDS)
        try:
            self.injector.inject(text)
            logger.info("Text injected")
            self.tray.set_state(self._TrayState.IDLE)
            return True
        except Exception as exc:
            logger.error("Injection failed: %s", exc)
            self.tray.set_state(self._TrayState.ERROR)
            self.tray.notify(
                "Verbal Code", "Injection failed \u2014 check logs for details"
            )
            return False


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
