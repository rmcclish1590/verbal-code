import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from collections.abc import Callable

logger = logging.getLogger("verbal_code")

_SUBPROCESS_TIMEOUT = 10


class InjectorBase(ABC):
    """Abstract base for all text-injection strategies."""

    @abstractmethod
    def inject(self, text: str) -> None:
        """Type ``text`` into the currently focused window."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if the required system tools are present."""
        ...


class XdotoolInjector(InjectorBase):
    """Injects text by simulating keyboard events via xdotool."""

    def __init__(self, typing_delay_ms: int = 0):
        self.typing_delay_ms = typing_delay_ms

    def inject(self, text: str) -> None:
        """Type ``text`` using ``xdotool type``."""
        cmd = ["xdotool", "type", "--clearmodifiers"]
        if self.typing_delay_ms > 0:
            cmd += ["--delay", str(self.typing_delay_ms)]
        cmd += ["--", text]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.error("xdotool failed: %s", result.stderr.strip())
        except subprocess.TimeoutExpired:
            logger.error("xdotool timed out after %ds", _SUBPROCESS_TIMEOUT)

    def is_available(self) -> bool:
        """Return True when xdotool is on PATH."""
        return shutil.which("xdotool") is not None


class ClipboardInjector(InjectorBase):
    """Injects text by writing to the clipboard then pasting with Ctrl+V.

    The previous clipboard contents are saved and restored so the user's
    clipboard is not permanently overwritten.
    """

    def inject(self, text: str) -> None:
        """Paste ``text`` via xclip + xdotool Ctrl+V."""
        saved_clipboard = self._read_clipboard()
        if not self._write_and_paste(text):
            return
        self._restore_clipboard(saved_clipboard)

    def _read_clipboard(self) -> str:
        try:
            return subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            ).stdout
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return ""

    def _write_and_paste(self, text: str) -> bool:
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            return True
        except subprocess.TimeoutExpired:
            logger.error("Clipboard injection timed out")
            return False
        except FileNotFoundError as exc:
            logger.error("Missing tool for clipboard injection: %s", exc)
            return False

    def _restore_clipboard(self, saved: str) -> None:
        try:
            subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=saved,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            logger.warning("Failed to restore clipboard")

    def is_available(self) -> bool:
        """Return True when both xclip and xdotool are on PATH."""
        return shutil.which("xclip") is not None and shutil.which("xdotool") is not None


class YdotoolInjector(InjectorBase):
    """Injects text via ydotool (works under Wayland without X11)."""

    def inject(self, text: str) -> None:
        """Type ``text`` using ``ydotool type``."""
        try:
            result = subprocess.run(
                ["ydotool", "type", "--", text],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
            if result.returncode != 0:
                logger.error("ydotool failed: %s", result.stderr.strip())
        except subprocess.TimeoutExpired:
            logger.error("ydotool timed out after %ds", _SUBPROCESS_TIMEOUT)

    def is_available(self) -> bool:
        """Return True when ydotool is on PATH."""
        return shutil.which("ydotool") is not None


class TextProcessor:
    """Applies lightweight post-processing to raw transcription output.

    Capitalises the first word of each dictation session and ensures each
    segment ends with a trailing space so consecutive injections do not run
    together.
    """

    def __init__(self) -> None:
        self._is_start: bool = True

    def process(self, text: str) -> str:
        """Return ``text`` with session-start capitalisation and trailing space."""
        if not text:
            return text
        if self._is_start:
            text = text[0].upper() + text[1:]
            self._is_start = False
        if not text.endswith(" "):
            text += " "
        return text

    def reset(self) -> None:
        """Reset state so the next segment is treated as a new session start."""
        self._is_start = True


def _build_candidate_list(
    preferred: str,
    delay: int,
) -> list[InjectorBase]:
    """Return an ordered list of injectors with the preferred method first."""
    xdotool = XdotoolInjector(delay)
    clipboard = ClipboardInjector()
    ydotool = YdotoolInjector()

    priority_map: dict[str, list[InjectorBase]] = {
        "xdotool": [xdotool, clipboard, ydotool],
        "clipboard": [clipboard, xdotool, ydotool],
        "ydotool": [ydotool, xdotool, clipboard],
    }
    return priority_map.get(preferred, [xdotool, clipboard, ydotool])


def create_injector(config: dict) -> InjectorBase:
    """Resolve and return the best available injector for the current system.

    Reads ``injection.method`` and ``injection.delay_ms`` from ``config``.
    Falls back through the full candidate list if the preferred tool is absent.
    """
    inj_cfg = config.get("injection", {})
    preferred: str = inj_cfg.get("method", "auto")
    delay: int = inj_cfg.get("delay_ms", 0)

    for injector in _build_candidate_list(preferred, delay):
        if injector.is_available():
            logger.info("Using injector: %s", type(injector).__name__)
            return injector

    logger.warning("No injector available, falling back to xdotool (may fail)")
    return XdotoolInjector(delay)
