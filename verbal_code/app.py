import argparse
import logging
import os
import signal
import sys
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


def main():
    parser = argparse.ArgumentParser(
        prog="verbal-code",
        description="Voice-to-text input for Linux",
    )
    parser.add_argument("-c", "--config", help="Path to config.yaml")
    parser.add_argument("--list-devices", action="store_true", help="List audio devices and exit")
    parser.add_argument("--test-audio", action="store_true", help="Record 3 seconds of audio and save to WAV")
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

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    logger.info("Starting Verbal Code v%s", __version__)
    print(f"Verbal Code v{__version__} ready")

    while not _shutdown:
        try:
            time.sleep(0.5)
        except (KeyboardInterrupt, SystemExit):
            break

    logger.info("Shutting down")
