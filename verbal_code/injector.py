import logging
import shutil
import subprocess
from abc import ABC, abstractmethod

logger = logging.getLogger("verbal_code")

_SUBPROCESS_TIMEOUT = 10


class InjectorBase(ABC):
    @abstractmethod
    def inject(self, text: str) -> None: ...

    @abstractmethod
    def is_available(self) -> bool: ...


class XdotoolInjector(InjectorBase):
    def __init__(self, typing_delay_ms: int = 0):
        self.typing_delay_ms = typing_delay_ms

    def inject(self, text: str) -> None:
        cmd = ["xdotool", "type", "--clearmodifiers"]
        if self.typing_delay_ms > 0:
            cmd += ["--delay", str(self.typing_delay_ms)]
        cmd += ["--", text]
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.error("xdotool failed: %s", result.stderr.strip())
        except subprocess.TimeoutExpired:
            logger.error("xdotool timed out after %ds", _SUBPROCESS_TIMEOUT)

    def is_available(self) -> bool:
        return shutil.which("xdotool") is not None


class ClipboardInjector(InjectorBase):
    def inject(self, text: str) -> None:
        try:
            saved = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            ).stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            saved = ""

        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired:
            logger.error("Clipboard injection timed out")
            return
        except FileNotFoundError as e:
            logger.error("Missing tool for clipboard injection: %s", e)
            return

        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=saved, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Failed to restore clipboard")

    def is_available(self) -> bool:
        return shutil.which("xclip") is not None and shutil.which("xdotool") is not None


class YdotoolInjector(InjectorBase):
    def inject(self, text: str) -> None:
        try:
            result = subprocess.run(
                ["ydotool", "type", "--", text],
                capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.error("ydotool failed: %s", result.stderr.strip())
        except subprocess.TimeoutExpired:
            logger.error("ydotool timed out after %ds", _SUBPROCESS_TIMEOUT)

    def is_available(self) -> bool:
        return shutil.which("ydotool") is not None


class TextProcessor:
    def __init__(self):
        self._is_start = True

    def process(self, text: str) -> str:
        if not text:
            return text
        if self._is_start:
            text = text[0].upper() + text[1:]
            self._is_start = False
        if not text.endswith(" "):
            text += " "
        return text

    def reset(self) -> None:
        self._is_start = True


def create_injector(config: dict) -> InjectorBase:
    inj_cfg = config.get("injection", {})
    preferred = inj_cfg.get("method", "auto")
    delay = inj_cfg.get("delay_ms", 0)

    candidates: list[InjectorBase]
    if preferred == "xdotool":
        candidates = [XdotoolInjector(delay), ClipboardInjector(), YdotoolInjector()]
    elif preferred == "clipboard":
        candidates = [ClipboardInjector(), XdotoolInjector(delay), YdotoolInjector()]
    elif preferred == "ydotool":
        candidates = [YdotoolInjector(), XdotoolInjector(delay), ClipboardInjector()]
    else:
        candidates = [XdotoolInjector(delay), ClipboardInjector(), YdotoolInjector()]

    for injector in candidates:
        if injector.is_available():
            logger.info("Using injector: %s", type(injector).__name__)
            return injector

    logger.warning("No injector available, falling back to xdotool (may fail)")
    return XdotoolInjector(delay)
