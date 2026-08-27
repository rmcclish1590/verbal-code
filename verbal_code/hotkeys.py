import logging
import os
import threading
from collections.abc import Callable

from pynput.keyboard import Key, KeyCode, Listener

logger = logging.getLogger("verbal_code")


def is_wayland_session() -> bool:
    """True when running under a Wayland session (where X11 grabs can't work)."""
    return (
        os.environ.get("XDG_SESSION_TYPE", "").lower() == "wayland"
        or bool(os.environ.get("WAYLAND_DISPLAY"))
    )


def create_hotkey_listener(
    modifiers: list[str],
    key: str,
    on_activate: Callable[[], None],
    on_deactivate: Callable[[], None],
):
    """Return the hotkey listener implementation for the current session.

    X11 uses the pynput listener.  Wayland compositors do not expose global
    keyboard events to X11 clients, so there the evdev listener (which reads
    /dev/input directly) is used instead — falling back to pynput with a
    warning when the evdev package is missing.
    """
    if is_wayland_session():
        try:
            from verbal_code.hotkeys_evdev import EvdevHotkeyListener

            import evdev  # noqa: F401 — fail here, not in the reader thread
        except ImportError:
            logger.error(
                "Wayland session detected but the 'evdev' package is not "
                "installed (pip install evdev); global hotkeys will most "
                "likely not work. Falling back to the X11 listener."
            )
        else:
            return EvdevHotkeyListener(modifiers, key, on_activate, on_deactivate)
    return HotkeyListener(modifiers, key, on_activate, on_deactivate)

_MODIFIER_MAP: dict[str, set[Key]] = {
    "ctrl": {Key.ctrl_l, Key.ctrl_r},
    "alt": {Key.alt_l, Key.alt_r},
    "shift": {Key.shift_l, Key.shift_r},
    "super": {Key.cmd_l, Key.cmd_r},
    "meta": {Key.cmd_l, Key.cmd_r},
}

_SPECIAL_KEY_MAP: dict[str, Key] = {
    "space": Key.space,
    "tab": Key.tab,
    "enter": Key.enter,
    "backspace": Key.backspace,
    "esc": Key.esc,
    "escape": Key.esc,
}

_PynputKey = Key | KeyCode | None


def _normalize_key(key: _PynputKey) -> Key | str | None:
    """Reduce a raw pynput key event to a canonical Key or lowercase string.

    With Ctrl held, pynput reports letter keys as control characters
    (e.g. ``'\\x04'`` for ``d``), so a non-printable char falls through to the
    virtual key code.  Returns None for key codes that cannot be represented
    (e.g. out-of-range virtual key values).
    """
    if isinstance(key, Key):
        return key
    if isinstance(key, KeyCode) and key.char and key.char.isprintable():
        return key.char.lower()
    if isinstance(key, KeyCode) and key.vk is not None:
        try:
            return chr(key.vk).lower()
        except (ValueError, OverflowError):
            return None
    return None


class HotkeyListener:
    """Listens for a configurable modifier+key combo and fires callbacks.

    Activates when all required modifiers and the trigger key are held down
    simultaneously.  Deactivates as soon as any part of the combo is released.
    Callbacks run on daemon threads so they do not block the listener loop.
    """

    def __init__(
        self,
        modifiers: list[str],
        key: str,
        on_activate: Callable[[], None],
        on_deactivate: Callable[[], None],
    ):
        self._required_modifiers = modifiers
        key_lower = key.lower()
        # Modifier-only combos (e.g. ctrl+alt+super) use a modifier as the
        # trigger; it is matched by modifier name rather than normalized key.
        self._trigger_is_modifier = key_lower in _MODIFIER_MAP
        self._trigger_key: Key | str = _SPECIAL_KEY_MAP.get(key_lower, key_lower)
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate

        self._pressed_modifiers: set[str] = set()
        self._trigger_held = False
        self._active = False
        self._lock = threading.Lock()
        self._listener: Listener | None = None

    @property
    def is_active(self) -> bool:
        """True while the hotkey combo is fully held down."""
        return self._active

    def _modifier_name(self, key: _PynputKey) -> str | None:
        if isinstance(key, Key):
            for name, variants in _MODIFIER_MAP.items():
                if key in variants:
                    return name
        return None

    def _check_combo(self) -> bool:
        return self._trigger_held and all(
            m in self._pressed_modifiers for m in self._required_modifiers
        )

    def _is_trigger(self, key: _PynputKey) -> bool:
        if self._trigger_is_modifier:
            return self._modifier_name(key) == self._trigger_key
        return _normalize_key(key) == self._trigger_key

    def _on_press(self, key: _PynputKey) -> None:
        with self._lock:
            mod = self._modifier_name(key)
            if mod:
                self._pressed_modifiers.add(mod)

            if self._is_trigger(key):
                self._trigger_held = True

            if not self._active and self._check_combo():
                self._active = True
                threading.Thread(target=self._on_activate, daemon=True).start()

    def _on_release(self, key: _PynputKey) -> None:
        with self._lock:
            was_active = self._active

            mod = self._modifier_name(key)
            if mod:
                self._pressed_modifiers.discard(mod)

            if self._is_trigger(key):
                self._trigger_held = False

            if was_active and not self._check_combo():
                self._active = False
                threading.Thread(target=self._on_deactivate, daemon=True).start()

    def start(self) -> None:
        """Attach the pynput listener and begin monitoring keyboard events."""
        self._listener = Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        mods = "+".join(self._required_modifiers)
        trigger = self._trigger_key
        key_name = trigger if isinstance(trigger, str) else trigger.name
        logger.info("Hotkey listener started: %s+%s", mods, key_name)

    def stop(self) -> None:
        """Stop monitoring keyboard events and clean up the listener."""
        if self._listener:
            self._listener.stop()
            self._listener = None
            logger.info("Hotkey listener stopped")
