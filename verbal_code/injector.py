import logging
import re
import shutil
import subprocess
import time
from abc import ABC, abstractmethod

logger = logging.getLogger("verbal_code")

_SUBPROCESS_TIMEOUT = 10

# Slow applications process the synthesized Ctrl+V asynchronously; restoring the
# clipboard too early makes them paste the restored (old) contents instead.
_PASTE_SETTLE_SECONDS = 0.3


class InjectionError(RuntimeError):
    """Raised when an injection attempt fails to deliver the text.

    Injectors must raise (not just log) on failure so the app can surface
    the error to the user instead of reporting a successful dictation while
    the text was silently lost.
    """


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
        except subprocess.TimeoutExpired as exc:
            raise InjectionError(
                f"xdotool timed out after {_SUBPROCESS_TIMEOUT}s"
            ) from exc
        except FileNotFoundError as exc:
            raise InjectionError("xdotool is not installed") from exc
        if result.returncode != 0:
            raise InjectionError(f"xdotool failed: {result.stderr.strip()}")

    def is_available(self) -> bool:
        """Return True when xdotool is on PATH."""
        return shutil.which("xdotool") is not None



# Clipboard TARGETS that indicate plain-text content xclip can round-trip.
_TEXT_CLIPBOARD_TARGETS = {
    "UTF8_STRING",
    "STRING",
    "TEXT",
    "COMPOUND_TEXT",
    "text/plain",
    "text/plain;charset=utf-8",
}


class ClipboardInjector(InjectorBase):
    """Injects text by writing to the clipboard then pasting with Ctrl+V.

    Previous plain-text clipboard contents are saved and restored so the
    user's clipboard is not permanently overwritten.  Non-text content
    (images, file copies) cannot be round-tripped through xclip, so no
    restore is attempted for it — the dictated text stays on the clipboard
    instead of being replaced by an empty string.
    """

    def inject(self, text: str) -> None:
        """Paste ``text`` via xclip + xdotool Ctrl+V."""
        saved_clipboard = self._save_clipboard()
        self._write_clipboard(text)
        try:
            self._press_paste()
        except InjectionError:
            # The dictation is already on the clipboard; leave it there so
            # the user can recover it with a manual paste.
            logger.warning("Paste failed; dictated text left on the clipboard")
            raise
        time.sleep(_PASTE_SETTLE_SECONDS)
        if saved_clipboard is not None:
            self._restore_clipboard(saved_clipboard, injected=text)

    def _save_clipboard(self) -> str | None:
        """Return the clipboard text to restore later, or None to skip restore.

        None means the clipboard is empty, unreadable, or holds non-text
        content — in every such case actively writing a "restored" value
        would destroy more than it saves.
        """
        targets = self._clipboard_targets()
        if targets is None:
            return None
        if not targets & _TEXT_CLIPBOARD_TARGETS:
            logger.debug(
                "Clipboard holds non-text content that cannot be restored "
                "after pasting; the dictated text will remain on the clipboard"
            )
            return None
        return self._read_clipboard()

    def _clipboard_targets(self) -> set[str] | None:
        """Return the clipboard's advertised TARGETS, or None if unreadable."""
        try:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o", "-t", "TARGETS"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if result.returncode != 0:  # empty clipboard, or no owner
            return None
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def _read_clipboard(self) -> str | None:
        """Return the clipboard text, or None when it cannot be read.

        A failed read must be distinguished from an empty clipboard: callers
        skip the restore on None rather than overwrite the clipboard with an
        empty string.
        """
        try:
            result = subprocess.run(
                ["xclip", "-selection", "clipboard", "-o"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def _write_clipboard(self, text: str) -> None:
        try:
            # stdout/stderr go to DEVNULL rather than pipes: xclip forks a
            # daemon that inherits them, and reading a pipe to EOF would block
            # until the daemon exits (i.e. until the clipboard is replaced).
            write_result = subprocess.run(
                ["xclip", "-selection", "clipboard"],
                input=text,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise InjectionError("xclip write timed out") from exc
        except FileNotFoundError as exc:
            raise InjectionError("xclip is not installed") from exc
        if write_result.returncode != 0:
            raise InjectionError(
                f"xclip write failed with exit code {write_result.returncode}"
            )

    def _press_paste(self) -> None:
        try:
            result = subprocess.run(
                ["xdotool", "key", "--clearmodifiers", "ctrl+v"],
                capture_output=True,
                text=True,
                timeout=_SUBPROCESS_TIMEOUT,
            )
        except subprocess.TimeoutExpired as exc:
            raise InjectionError("paste keystroke timed out") from exc
        except FileNotFoundError as exc:
            raise InjectionError("xdotool is not installed") from exc
        if result.returncode != 0:
            raise InjectionError(
                f"paste keystroke failed: {result.stderr.strip()}"
            )

    def _restore_clipboard(self, saved: str, injected: str) -> None:
        """Write ``saved`` back, unless the user changed the clipboard meanwhile.

        Anything copied during the paste-settle window must win over the
        restore; the clipboard is only restored while it still holds the
        text this injector put there.
        """
        current = self._read_clipboard()
        if current is not None and current != injected:
            logger.debug(
                "Clipboard changed during the paste settle window; "
                "leaving it untouched"
            )
            return
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
        except subprocess.TimeoutExpired as exc:
            raise InjectionError(
                f"ydotool timed out after {_SUBPROCESS_TIMEOUT}s"
            ) from exc
        except FileNotFoundError as exc:
            raise InjectionError("ydotool is not installed") from exc
        if result.returncode != 0:
            raise InjectionError(f"ydotool failed: {result.stderr.strip()}")

    def is_available(self) -> bool:
        """Return True when ydotool is on PATH."""
        return shutil.which("ydotool") is not None


class HybridInjector(InjectorBase):
    """Types short fragments, pastes long ones via the clipboard.

    Keystroke simulation feels natural for short dictations but scales
    linearly with text length (and multiplies with ``delay_ms``); a clipboard
    paste lands a long dictation instantly.  ``threshold`` is the character
    count at which pasting takes over.
    """

    def __init__(
        self,
        typing_injector: InjectorBase,
        clipboard_injector: InjectorBase,
        threshold: int,
    ):
        self._typing = typing_injector
        self._clipboard = clipboard_injector
        self.threshold = threshold

    def inject(self, text: str) -> None:
        """Route ``text`` to typing or clipboard paste based on its length."""
        if len(text) >= self.threshold and self._clipboard.is_available():
            logger.debug(
                "Text is %d chars (>= %d): using clipboard paste",
                len(text),
                self.threshold,
            )
            try:
                self._clipboard.inject(text)
                return
            except InjectionError as exc:
                logger.warning(
                    "Clipboard paste failed (%s); falling back to typing", exc
                )
        self._typing.inject(text)

    def is_available(self) -> bool:
        """Available when either underlying strategy is."""
        return self._typing.is_available() or self._clipboard.is_available()


# Spoken command phrases → replacement text, tried in order (longer phrases
# first so "new paragraph" wins over "new line" prefix handling). The \s*
# before each phrase swallows the space the STT engine put in front of it, so
# punctuation attaches to the preceding word.
_PUNCTUATION_COMMANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\s*\bnew paragraph\b", re.IGNORECASE), "\n\n"),
    (re.compile(r"\s*\bnew ?line\b", re.IGNORECASE), "\n"),
    (re.compile(r"\s*\bfull stop\b", re.IGNORECASE), "."),
    (re.compile(r"\s*\bperiod\b", re.IGNORECASE), "."),
    (re.compile(r"\s*\bcomma\b", re.IGNORECASE), ","),
    (re.compile(r"\s*\bquestion mark\b", re.IGNORECASE), "?"),
    (re.compile(r"\s*\bexclamation (?:mark|point)\b", re.IGNORECASE), "!"),
    (re.compile(r"\s*\bsemicolon\b", re.IGNORECASE), ";"),
    (re.compile(r"\s*\bcolon\b", re.IGNORECASE), ":"),
    (re.compile(r"\s*\bellipsis\b", re.IGNORECASE), "..."),
]

# Punctuation the STT engine may already have attached to a command word,
# e.g. Whisper emitting "period." — dropped after substitution. Exactly two
# repeats collapse; longer runs (an ellipsis) are left alone.
_DUPLICATE_PUNCTUATION = re.compile(r"(?<![.,!?;:])([.,!?;:])\1(?!\1)")
_PUNCT_BEFORE_NEWLINE = re.compile(r"[ \t]+(\n)")
_SPACE_AFTER_NEWLINE = re.compile(r"(\n+)[ \t]+")
_SENTENCE_START = re.compile(r"([.!?]\s+|\n\s*)([a-z])")


def _apply_punctuation_commands(text: str) -> str:
    for pattern, replacement in _PUNCTUATION_COMMANDS:
        text = pattern.sub(replacement, text)
    text = _DUPLICATE_PUNCTUATION.sub(r"\1", text)
    text = _PUNCT_BEFORE_NEWLINE.sub(r"\1", text)
    text = _SPACE_AFTER_NEWLINE.sub(r"\1", text)
    return text


class TextProcessor:
    """Applies lightweight post-processing to raw transcription output.

    Translates spoken punctuation/formatting commands ("period", "comma",
    "new line", ...), capitalises sentence starts, and ensures each segment
    ends with a separator so consecutive injections do not run together.
    """

    def __init__(self, punctuation_commands: bool = True) -> None:
        self._capitalize_next: bool = True
        self._commands_enabled = punctuation_commands

    def process(self, text: str) -> str:
        """Return ``text`` with commands applied, capitalisation, and a trailing
        separator."""
        if not text:
            return text
        if self._commands_enabled:
            text = _apply_punctuation_commands(text)
        if not text.strip():
            return text

        if self._capitalize_next:
            text = self._capitalize_first_letter(text)
        text = _SENTENCE_START.sub(
            lambda m: m.group(1) + m.group(2).upper(), text
        )

        # Carry sentence state across segments: after "…stop." the next
        # dictation should start capitalised.
        self._capitalize_next = text.rstrip(" ")[-1] in ".!?\n"

        if not text[-1].isspace():
            text += " "
        return text

    @staticmethod
    def _capitalize_first_letter(text: str) -> str:
        for i, char in enumerate(text):
            if char.isalpha():
                return text[:i] + char.upper() + text[i + 1 :]
            if not char.isspace():
                break
        return text

    def reset(self) -> None:
        """Reset state so the next segment is treated as a new session start."""
        self._capitalize_next = True


def _build_candidate_list(
    preferred: str,
    delay: int,
) -> list[InjectorBase]:
    """Return an ordered list of injectors with the preferred method first.

    With ``method: auto``, X11 prefers xdotool while Wayland prefers ydotool —
    xdotool/xclip only reach XWayland windows there, so they are kept solely
    as a last resort.
    """
    from verbal_code.hotkeys import is_wayland_session

    xdotool = XdotoolInjector(delay)
    clipboard = ClipboardInjector()
    ydotool = YdotoolInjector()

    if is_wayland_session():
        auto = [ydotool, xdotool, clipboard]
    else:
        auto = [xdotool, clipboard, ydotool]

    priority_map: dict[str, list[InjectorBase]] = {
        "xdotool": [xdotool, clipboard, ydotool],
        "clipboard": [clipboard, xdotool, ydotool],
        "ydotool": [ydotool, xdotool, clipboard],
    }
    return priority_map.get(preferred, auto)


DEFAULT_CLIPBOARD_THRESHOLD = 100


def create_injector(config: dict) -> InjectorBase:
    """Resolve and return the best available injector for the current system.

    Reads ``injection.method``, ``injection.delay_ms``, and
    ``injection.clipboard_threshold`` from ``config``.  Falls back through the
    full candidate list if the preferred tool is absent.  With ``method:
    auto`` on X11, typing injection is wrapped so dictations of
    ``clipboard_threshold`` characters or more are pasted via the clipboard
    instead of typed (0 disables the switch).
    """
    inj_cfg = config.get("injection", {})
    preferred: str = inj_cfg.get("method", "auto")
    delay: int = inj_cfg.get("delay_ms", 0)
    threshold: int = inj_cfg.get("clipboard_threshold", DEFAULT_CLIPBOARD_THRESHOLD)

    resolved: InjectorBase | None = None
    for injector in _build_candidate_list(preferred, delay):
        if injector.is_available():
            resolved = injector
            break

    if resolved is None:
        logger.warning("No injector available, falling back to xdotool (may fail)")
        return XdotoolInjector(delay)

    if (
        preferred == "auto"
        and threshold > 0
        and isinstance(resolved, XdotoolInjector)
    ):
        clipboard = ClipboardInjector()
        if clipboard.is_available():
            logger.info(
                "Using injector: XdotoolInjector with clipboard paste for "
                "%d+ character texts",
                threshold,
            )
            return HybridInjector(resolved, clipboard, threshold)

    logger.info("Using injector: %s", type(resolved).__name__)
    return resolved
