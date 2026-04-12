import logging
import os
import subprocess
import threading
from enum import Enum

logger = logging.getLogger("verbal_code")

_ICON_DIR = os.path.expanduser("~/.cache/verbal-code/icons")

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
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    ERROR = "error"


_STATE_ICONS = {
    TrayState.IDLE: ("mic-idle", "#888888", ""),
    TrayState.LISTENING: ("mic-listening", "#e53935", ""),
    TrayState.PROCESSING: ("mic-processing", "#fbc02d", ""),
    TrayState.ERROR: ("mic-error", "#888888", _ERROR_X),
}


def _write_icons():
    os.makedirs(_ICON_DIR, exist_ok=True)
    for state, (name, color, extra) in _STATE_ICONS.items():
        path = os.path.join(_ICON_DIR, f"{name}.svg")
        if not os.path.exists(path):
            svg = _SVG_TEMPLATE.format(color=color, extra=extra)
            with open(path, "w") as f:
                f.write(svg)


class SystemTray:
    def __init__(self, on_quit=None, notifications: bool = True):
        self._on_quit = on_quit
        self._notifications = notifications
        self._indicator = None
        self._status_item = None
        self._available = False
        self._gtk = None
        self._glib = None

    def start(self) -> None:
        try:
            import gi
            gi.require_version("Gtk", "3.0")
            gi.require_version("AppIndicator3", "0.1")
            from gi.repository import AppIndicator3, GLib, Gtk
            self._gtk = Gtk
            self._glib = GLib
        except (ImportError, ValueError) as e:
            logger.warning("System tray unavailable (%s), continuing without it", e)
            return

        _write_icons()

        self._indicator = AppIndicator3.Indicator.new(
            "verbal-code",
            "mic-idle",
            AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
        )
        self._indicator.set_icon_theme_path(_ICON_DIR)
        self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        menu = Gtk.Menu()

        self._status_item = Gtk.MenuItem(label="Verbal Code — Idle")
        self._status_item.set_sensitive(False)
        menu.append(self._status_item)

        menu.append(Gtk.SeparatorMenuItem())

        quit_item = Gtk.MenuItem(label="Quit Verbal Code")
        quit_item.connect("activate", self._on_quit_clicked)
        menu.append(quit_item)

        menu.show_all()
        self._indicator.set_menu(menu)

        self._available = True
        threading.Thread(target=Gtk.main, daemon=True).start()
        logger.info("System tray started")

    def stop(self) -> None:
        if self._available and self._gtk:
            self._glib.idle_add(self._gtk.main_quit)
            logger.info("System tray stopped")

    def set_state(self, state: TrayState) -> None:
        if not self._available:
            return
        icon_name = _STATE_ICONS[state][0]
        label_map = {
            TrayState.IDLE: "Verbal Code — Idle",
            TrayState.LISTENING: "Verbal Code — Listening...",
            TrayState.PROCESSING: "Verbal Code — Processing...",
            TrayState.ERROR: "Verbal Code — Error",
        }

        def _update():
            self._indicator.set_icon_full(icon_name, state.value)
            if self._status_item:
                self._status_item.set_label(label_map.get(state, "Verbal Code"))

        self._glib.idle_add(_update)

    def notify(self, title: str, msg: str) -> None:
        if not self._notifications:
            return
        try:
            subprocess.run(
                ["notify-send", "-a", "Verbal Code", title, msg],
                capture_output=True, timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            logger.debug("notify-send not available")

    def _on_quit_clicked(self, _widget):
        if self._on_quit:
            self._on_quit()
