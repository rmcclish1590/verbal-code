import logging
import os
import subprocess
import threading
from collections.abc import Callable
from enum import Enum
from typing import Any

logger = logging.getLogger("verbal_code")

_ICON_DIR = os.path.expanduser("~/.cache/verbal-code/icons")
_NOTIFY_TIMEOUT_SECONDS = 5

_SVG_TEMPLATE = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24">
  <rect x="9" y="2" width="6" height="12" rx="3" fill="{color}"/>
  <path d="M5 11a7 7 0 0 0 14 0" stroke="{color}" stroke-width="2" fill="none"/>
  <line x1="12" y1="18" x2="12" y2="22" stroke="{color}" stroke-width="2"/>
  <line x1="8" y1="22" x2="16" y2="22" stroke="{color}" stroke-width="2"/>{extra}
</svg>"""

_ERROR_X = """
  <line x1="16" y1="2" x2="22" y2="8" stroke="#e53935" stroke-width="2.5"/>
  <line x1="22" y1="2" x2="16" y2="8" stroke="#e53935" stroke-width="2.5"/>"""


class TrayState(Enum):
    """Visual states reflected in the system tray icon and menu label."""

    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    ERROR = "error"


_STATE_ICONS: dict[TrayState, tuple[str, str, str]] = {
    TrayState.IDLE: ("mic-idle", "#888888", ""),
    TrayState.LISTENING: ("mic-listening", "#e53935", ""),
    TrayState.PROCESSING: ("mic-processing", "#fbc02d", ""),
    TrayState.ERROR: ("mic-error", "#888888", _ERROR_X),
}

_STATE_LABELS: dict[TrayState, str] = {
    TrayState.IDLE: "Verbal Code \u2014 Idle",
    TrayState.LISTENING: "Verbal Code \u2014 Listening...",
    TrayState.PROCESSING: "Verbal Code \u2014 Processing...",
    TrayState.ERROR: "Verbal Code \u2014 Error",
}


def _write_icons() -> None:
    """Render per-state SVG icon files into the icon cache directory."""
    os.makedirs(_ICON_DIR, exist_ok=True)
    for _state, (name, color, extra) in _STATE_ICONS.items():
        path = os.path.join(_ICON_DIR, f"{name}.svg")
        if not os.path.exists(path):
            svg = _SVG_TEMPLATE.format(color=color, extra=extra)
            with open(path, "w") as f:
                f.write(svg)


class SystemTray:
    """Manages the AppIndicator3 system tray icon and desktop notifications.

    GTK is imported lazily so the application can start without it if the
    desktop environment does not support app indicators.
    """

    def __init__(
        self,
        on_quit: Callable[[], None] | None = None,
        on_hotkeys: Callable[[], None] | None = None,
        notifications: bool = True,
    ):
        self._on_quit = on_quit
        self._on_hotkeys = on_hotkeys
        self._notifications = notifications
        self._indicator: Any = None
        self._status_item: Any = None
        self._available = False
        self._gtk: Any = None
        self._gdk: Any = None
        self._glib: Any = None

    def start(self) -> None:
        """Initialise the GTK main loop and register the tray indicator."""
        try:
            import gi

            gi.require_version("Gtk", "3.0")
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3, Gdk, GLib, Gtk

            self._gtk = Gtk
            self._gdk = Gdk
            self._glib = GLib
        except (ImportError, ValueError) as exc:
            logger.warning(
                "System tray unavailable (%s), continuing without it", exc
            )
            return

        _write_icons()

        self._indicator = AppIndicator3.Indicator.new(
            "verbal-code",
            "mic-idle",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_icon_theme_path(_ICON_DIR)
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        menu = self._gtk.Menu()

        self._status_item = self._gtk.MenuItem(label="Verbal Code \u2014 Idle")
        self._status_item.set_sensitive(False)
        menu.append(self._status_item)

        menu.append(self._gtk.SeparatorMenuItem())

        hotkeys_item = self._gtk.MenuItem(label="Hotkeys...")
        hotkeys_item.connect("activate", self._on_hotkeys_clicked)
        menu.append(hotkeys_item)

        menu.append(self._gtk.SeparatorMenuItem())

        quit_item = self._gtk.MenuItem(label="Quit Verbal Code")
        quit_item.connect("activate", self._on_quit_clicked)
        menu.append(quit_item)

        menu.show_all()
        self._indicator.set_menu(menu)

        self._available = True
        threading.Thread(target=self._gtk.main, daemon=True).start()
        logger.info("System tray started")

    def stop(self) -> None:
        """Request GTK to quit on the next idle cycle."""
        if self._available and self._gtk:
            self._glib.idle_add(self._gtk.main_quit)
            logger.info("System tray stopped")

    def set_state(self, state: TrayState) -> None:
        """Update the tray icon and menu label to reflect ``state``."""
        if not self._available:
            return
        icon_name = _STATE_ICONS[state][0]
        label = _STATE_LABELS.get(state, "Verbal Code")

        def _update() -> None:
            self._indicator.set_icon_full(icon_name, state.value)
            if self._status_item:
                self._status_item.set_label(label)

        self._glib.idle_add(_update)

    def notify(self, title: str, msg: str) -> None:
        """Send a desktop notification via notify-send if available."""
        if not self._notifications:
            return
        safe_title = str(title)[:128]
        safe_msg = str(msg)[:256]
        try:
            subprocess.run(
                ["notify-send", "-a", "Verbal Code", "--", safe_title, safe_msg],
                capture_output=True,
                timeout=_NOTIFY_TIMEOUT_SECONDS,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("notify-send not available")

    def _on_hotkeys_clicked(self, _widget: Any) -> None:
        if self._on_hotkeys:
            self._on_hotkeys()

    def _on_quit_clicked(self, _widget: Any) -> None:
        if self._on_quit:
            self._on_quit()
