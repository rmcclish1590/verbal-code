import logging
import threading
from collections.abc import Callable

from pynput.keyboard import Key, KeyCode, Listener

logger = logging.getLogger("verbal_code")

_MODIFIER_MAP: dict[str, set[Key]] = {
    "ctrl": {Key.ctrl_l, Key.ctrl_r},
    "alt": {Key.alt_l, Key.alt_r},
    "shift": {Key.shift_l, Key.shift_r},
    "super": {Key.cmd_l, Key.cmd_r},
    "meta": {Key.cmd_l, Key.cmd_r},
}


def _normalize_key(key) -> Key | str | None:
    if isinstance(key, Key):
        return key
    if isinstance(key, KeyCode) and key.char:
        return key.char.lower()
    if isinstance(key, KeyCode) and key.vk is not None:
        try:
            return chr(key.vk).lower()
        except (ValueError, OverflowError):
            return None
    return None


class HotkeyListener:
    def __init__(
        self,
        modifiers: list[str],
        key: str,
        on_activate: Callable[[], None],
        on_deactivate: Callable[[], None],
    ):
        self._required_modifiers = modifiers
        self._trigger_key = key.lower()
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate

        self._pressed_modifiers: set[str] = set()
        self._trigger_held = False
        self._active = False
        self._lock = threading.Lock()
        self._listener: Listener | None = None

    @property
    def is_active(self) -> bool:
        return self._active

    def _modifier_name(self, key) -> str | None:
        if isinstance(key, Key):
            for name, variants in _MODIFIER_MAP.items():
                if key in variants:
                    return name
        return None

    def _check_combo(self) -> bool:
        return (
            self._trigger_held
            and all(m in self._pressed_modifiers for m in self._required_modifiers)
        )

    def _on_press(self, key):
        with self._lock:
            mod = self._modifier_name(key)
            if mod:
                self._pressed_modifiers.add(mod)

            normalized = _normalize_key(key)
            if normalized == self._trigger_key:
                self._trigger_held = True

            if not self._active and self._check_combo():
                self._active = True
                threading.Thread(target=self._on_activate, daemon=True).start()

    def _on_release(self, key):
        with self._lock:
            was_active = self._active

            mod = self._modifier_name(key)
            if mod:
                self._pressed_modifiers.discard(mod)

            normalized = _normalize_key(key)
            if normalized == self._trigger_key:
                self._trigger_held = False

            if was_active and not self._check_combo():
                self._active = False
                threading.Thread(target=self._on_deactivate, daemon=True).start()

    def start(self) -> None:
        self._listener = Listener(
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self._listener.daemon = True
        self._listener.start()
        mods = "+".join(self._required_modifiers)
        logger.info("Hotkey listener started: %s+%s", mods, self._trigger_key)

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
            logger.info("Hotkey listener stopped")
