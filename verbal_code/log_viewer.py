"""GTK3 window for viewing the dictation latency log (MCC-58).

Modeled on the "Dictionary..." tray window (`dictionary_editor.py`): a
lazily constructed GTK window opened from the tray menu. Surfaces only the
`dictation_latency_ms=` lines logged by MCC-30, not the full application
log, since that's the data users need for tuning/regression checks. A
static snapshot with a manual Refresh button is enough for v1 — no live
tailing.
"""

import logging
from typing import Any

logger = logging.getLogger("verbal_code")

_LATENCY_MARKER = "dictation_latency_ms="
_MAX_LINES = 1000


def _extract_latency_lines(lines: list[str]) -> list[str]:
    """Return only the lines that record a dictation latency measurement."""
    return [line for line in lines if _LATENCY_MARKER in line]


def _read_latency_log(path: str | None, max_lines: int = _MAX_LINES) -> list[str]:
    """Read up to the last ``max_lines`` latency entries from the log at ``path``.

    Returns an empty list if no log file is configured or it can't be read;
    callers show a friendly placeholder rather than an error for that case.
    """
    if not path:
        return []
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError:
        return []
    latency_lines = _extract_latency_lines(lines)
    return [line.rstrip("\n") for line in latency_lines[-max_lines:]]


class LogViewerWindow:
    """GTK3 read-only window showing the hotkey-release-to-injection latency log."""

    def __init__(self, gtk: Any, log_path: str | None):
        self._gtk = gtk
        self._log_path = log_path

        self._window = gtk.Window(title="Verbal Code — Latency Log")
        self._window.set_default_size(640, 420)
        self._window.set_position(gtk.WindowPosition.CENTER)

        vbox = gtk.Box(orientation=gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(12)
        vbox.set_margin_end(12)
        self._window.add(vbox)

        self._text_view = gtk.TextView()
        self._text_view.set_editable(False)
        self._text_view.set_cursor_visible(False)
        self._text_view.set_monospace(True)
        self._buffer = self._text_view.get_buffer()

        scroller = gtk.ScrolledWindow()
        scroller.set_policy(gtk.PolicyType.AUTOMATIC, gtk.PolicyType.AUTOMATIC)
        scroller.set_vexpand(True)
        scroller.add(self._text_view)
        vbox.pack_start(scroller, True, True, 0)

        button_box = gtk.ButtonBox(orientation=gtk.Orientation.HORIZONTAL)
        button_box.set_layout(gtk.ButtonBoxStyle.END)
        button_box.set_spacing(8)

        refresh_btn = gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", lambda _w: self._refresh())
        button_box.pack_start(refresh_btn, False, False, 0)

        close_btn = gtk.Button(label="Close")
        close_btn.connect("clicked", lambda _w: self._window.destroy())
        button_box.pack_start(close_btn, False, False, 0)

        vbox.pack_start(button_box, False, False, 0)

        self._refresh()

    def show(self) -> None:
        self._window.show_all()

    def _refresh(self) -> None:
        lines = _read_latency_log(self._log_path)
        if not lines:
            text = (
                "No latency entries logged yet."
                if self._log_path
                else "File logging isn't configured (set logging.file in config.yaml)."
            )
        else:
            text = "\n".join(lines)
        self._buffer.set_text(text)
        end_iter = self._buffer.get_end_iter()
        self._text_view.scroll_to_iter(end_iter, 0.0, False, 0.0, 0.0)
