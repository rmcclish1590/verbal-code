"""Wayland-compatible global hotkey listener built on evdev.

pynput's X11 backend cannot see keyboard events under Wayland, so this
listener reads them straight from the kernel input devices instead.  That
requires read access to ``/dev/input/event*`` — on Debian/Mint this means the
user must be in the ``input`` group.

The combo-matching state machine (:class:`ComboState`) is pure Python with
string key names, so it is shared logic-wise with the pynput listener's
semantics (activate when all modifiers plus the trigger are held, deactivate
when any part is released, modifier-only combos allowed) and unit-testable
without evdev installed.  Only the device-reading thread imports evdev.
"""

import logging
import threading

logger = logging.getLogger("verbal_code")

INPUT_GROUP_HINT = (
    "Cannot read /dev/input devices. Add your user to the 'input' group:\n"
    "  sudo usermod -aG input $USER\n"
    "then log out and back in."
)

# evdev key-code names → canonical modifier names (matching hotkeys.py).
_EVDEV_MODIFIER_NAMES: dict[str, str] = {
    "KEY_LEFTCTRL": "ctrl",
    "KEY_RIGHTCTRL": "ctrl",
    "KEY_LEFTALT": "alt",
    "KEY_RIGHTALT": "alt",
    "KEY_LEFTSHIFT": "shift",
    "KEY_RIGHTSHIFT": "shift",
    "KEY_LEFTMETA": "super",
    "KEY_RIGHTMETA": "super",
}

# evdev key-code names → canonical trigger-key names used in the config.
_EVDEV_SPECIAL_KEYS: dict[str, str] = {
    "KEY_SPACE": "space",
    "KEY_TAB": "tab",
    "KEY_ENTER": "enter",
    "KEY_BACKSPACE": "backspace",
    "KEY_ESC": "esc",
}

_EV_KEY_DOWN = 1
_EV_KEY_UP = 0


def evdev_key_name(code_name: str | list[str]) -> str | None:
    """Reduce an evdev key-code name to a canonical hotkey name.

    ``evdev.ecodes.keys[code]`` yields either a string like ``"KEY_D"`` or a
    list of aliases; unknown/non-key codes return None.
    """
    if isinstance(code_name, list):
        code_name = code_name[0]
    if not isinstance(code_name, str) or not code_name.startswith("KEY_"):
        return None
    if code_name in _EVDEV_MODIFIER_NAMES:
        return _EVDEV_MODIFIER_NAMES[code_name]
    if code_name in _EVDEV_SPECIAL_KEYS:
        return _EVDEV_SPECIAL_KEYS[code_name]
    suffix = code_name[len("KEY_") :]
    if len(suffix) == 1:  # letters and digits
        return suffix.lower()
    return None


_MODIFIER_NAMES = frozenset(_EVDEV_MODIFIER_NAMES.values())


class ComboState:
    """Tracks held keys and reports combo activation transitions.

    Keys are canonical lowercase names ("ctrl", "alt", "super", "shift",
    letters, "space", ...). The trigger key may itself be a modifier name,
    enabling modifier-only combos such as alt+ctrl+super.
    """

    def __init__(self, modifiers: list[str], key: str):
        self._required = [m.lower() for m in modifiers]
        self._trigger = key.lower()
        self._held: set[str] = set()
        self.active = False

    def press(self, name: str | None) -> bool:
        """Record a key press; return True when the combo just activated."""
        if name is None:
            return False
        self._held.add(name)
        if not self.active and self._complete():
            self.active = True
            return True
        return False

    def release(self, name: str | None) -> bool:
        """Record a key release; return True when the combo just deactivated."""
        if name is None:
            return False
        self._held.discard(name)
        if self.active and not self._complete():
            self.active = False
            return True
        return False

    def _complete(self) -> bool:
        return self._trigger in self._held and all(
            m in self._held for m in self._required
        )


class EvdevHotkeyListener:
    """Drop-in alternative to :class:`~verbal_code.hotkeys.HotkeyListener`.

    Reads key events from every keyboard-capable ``/dev/input`` device in a
    daemon thread.  Same callback contract: ``on_activate`` fires when the
    full combo is held, ``on_deactivate`` when any part is released.
    """

    def __init__(
        self,
        modifiers: list[str],
        key: str,
        on_activate,
        on_deactivate,
    ):
        self._combo = ComboState(modifiers, key)
        self._on_activate = on_activate
        self._on_deactivate = on_deactivate
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._label = "+".join([*modifiers, key])

    @property
    def is_active(self) -> bool:
        """True while the hotkey combo is fully held down."""
        return self._combo.active

    def _keyboards(self):
        """Return evdev devices that look like keyboards."""
        import evdev
        from evdev import ecodes

        devices = []
        for path in evdev.list_devices():
            try:
                device = evdev.InputDevice(path)
            except OSError:
                continue
            keys = device.capabilities().get(ecodes.EV_KEY, [])
            # A real keyboard has letter keys; mice/buttons don't.
            if ecodes.KEY_A in keys and ecodes.KEY_Z in keys:
                devices.append(device)
            else:
                device.close()
        return devices

    def _handle_event(self, event) -> None:
        from evdev import ecodes

        if event.type != ecodes.EV_KEY or event.value not in (
            _EV_KEY_DOWN,
            _EV_KEY_UP,
        ):
            return
        name = evdev_key_name(ecodes.keys.get(event.code, ""))
        if event.value == _EV_KEY_DOWN:
            if self._combo.press(name):
                threading.Thread(target=self._on_activate, daemon=True).start()
        else:
            if self._combo.release(name):
                threading.Thread(target=self._on_deactivate, daemon=True).start()

    def _loop(self) -> None:
        import select

        try:
            devices = self._keyboards()
        except PermissionError:
            logger.error(INPUT_GROUP_HINT)
            return
        if not devices:
            logger.error(
                "No readable keyboard devices found under /dev/input. %s",
                INPUT_GROUP_HINT,
            )
            return

        fd_map = {device.fd: device for device in devices}
        try:
            while not self._stop.is_set():
                ready, _, _ = select.select(fd_map, [], [], 0.2)
                for fd in ready:
                    try:
                        for event in fd_map[fd].read():
                            self._handle_event(event)
                    except OSError:
                        # Device unplugged; drop it and carry on.
                        fd_map.pop(fd, None)
                        if not fd_map:
                            logger.error("All keyboard devices disappeared")
                            return
        finally:
            for device in fd_map.values():
                device.close()

    def start(self) -> None:
        """Start the device-reading thread."""
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("Hotkey listener started (evdev): %s", self._label)

    def stop(self) -> None:
        """Stop the device-reading thread."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
            logger.info("Hotkey listener stopped (evdev)")
