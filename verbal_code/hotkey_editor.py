import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("verbal_code")

_GDK_MODIFIER_NAMES: dict[str, str] = {
    "Control_L": "ctrl",
    "Control_R": "ctrl",
    "Alt_L": "alt",
    "Alt_R": "alt",
    "Super_L": "super",
    "Super_R": "super",
    "Shift_L": "shift",
    "Shift_R": "shift",
    "Meta_L": "meta",
    "Meta_R": "meta",
    "ISO_Level3_Shift": "alt",
}

_SPECIAL_GDK_KEYS: dict[str, str] = {
    "space": "space",
    "Tab": "tab",
    "Return": "enter",
    "BackSpace": "backspace",
    "Escape": "esc",
}


def _format_combo(modifiers: list[str], key: str) -> str:
    parts = [m.capitalize() for m in modifiers]
    parts.append(key.capitalize())
    return "+".join(parts)


def save_hotkey_config(
    config_path: str, modifiers: list[str], key: str
) -> None:
    """Update the hotkey section of the config, preserving everything else."""
    from verbal_code.config_store import update_config

    def _set_hotkey(cfg: dict) -> None:
        cfg.setdefault("hotkey", {})
        cfg["hotkey"]["modifiers"] = modifiers
        cfg["hotkey"]["key"] = key

    update_config(config_path, _set_hotkey)
    logger.info("Hotkey config saved to %s", config_path)


class HotkeyEditorWindow:
    """GTK3 window for interactively capturing a new hotkey combo."""

    def __init__(
        self,
        gtk: Any,
        gdk: Any,
        current_modifiers: list[str],
        current_key: str,
        config_path: str,
        on_save: Callable[[list[str], str], None],
        on_recording_start: Callable[[], None],
        on_recording_stop: Callable[[], None],
    ):
        self._gtk = gtk
        self._gdk = gdk
        self._config_path = config_path
        self._on_save = on_save
        self._on_recording_start = on_recording_start
        self._on_recording_stop = on_recording_stop

        self._recording = False
        # Press order matters: a modifier-only combo uses the last-pressed
        # modifier as the trigger key.
        self._captured_modifiers: list[str] = []
        self._captured_key: str | None = None
        self._new_modifiers: list[str] | None = None
        self._new_key: str | None = None

        self._window = gtk.Window(title="Verbal Code \u2014 Hotkeys")
        self._window.set_default_size(400, 180)
        self._window.set_position(gtk.WindowPosition.CENTER)
        self._window.set_keep_above(True)
        self._window.set_resizable(False)
        self._window.connect("destroy", self._on_window_destroy)
        self._window.connect("key-press-event", self._on_key_press)
        self._window.connect("key-release-event", self._on_key_release)

        vbox = gtk.Box(orientation=gtk.Orientation.VERTICAL, spacing=12)
        vbox.set_margin_top(20)
        vbox.set_margin_bottom(20)
        vbox.set_margin_start(20)
        vbox.set_margin_end(20)

        current_label = gtk.Label(
            label=f"Current hotkey: {_format_combo(current_modifiers, current_key)}"
        )
        vbox.pack_start(current_label, False, False, 0)

        self._new_label = gtk.Label(label="New hotkey: [not set]")
        vbox.pack_start(self._new_label, False, False, 0)

        button_box = gtk.ButtonBox(orientation=gtk.Orientation.HORIZONTAL)
        button_box.set_layout(gtk.ButtonBoxStyle.CENTER)
        button_box.set_spacing(10)

        self._record_btn = gtk.Button(label="Record")
        self._record_btn.connect("clicked", self._on_record_clicked)
        button_box.pack_start(self._record_btn, False, False, 0)

        self._save_btn = gtk.Button(label="Save")
        self._save_btn.set_sensitive(False)
        self._save_btn.connect("clicked", self._on_save_clicked)
        button_box.pack_start(self._save_btn, False, False, 0)

        cancel_btn = gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", self._on_cancel_clicked)
        button_box.pack_start(cancel_btn, False, False, 0)

        vbox.pack_start(button_box, False, False, 0)
        self._window.add(vbox)

    def show(self) -> None:
        self._window.show_all()

    def _on_record_clicked(self, _widget: Any) -> None:
        self._recording = True
        self._captured_modifiers = []
        self._captured_key = None
        self._new_label.set_text("Press your desired key combo...")
        self._record_btn.set_label("Recording...")
        self._record_btn.set_sensitive(False)
        self._save_btn.set_sensitive(False)
        self._on_recording_start()

    def _on_key_press(self, _widget: Any, event: Any) -> bool:
        if not self._recording:
            return False

        keyval_name = self._gdk.keyval_name(event.keyval)
        if keyval_name is None:
            return True

        mod_name = _GDK_MODIFIER_NAMES.get(keyval_name)
        if mod_name:
            if mod_name not in self._captured_modifiers:
                self._captured_modifiers.append(mod_name)
            partial = "+".join(m.capitalize() for m in self._captured_modifiers)
            self._new_label.set_text(f"New hotkey: {partial}+...")
            return True

        # Non-modifier key — finalize capture
        self._captured_key = _SPECIAL_GDK_KEYS.get(
            keyval_name, keyval_name.lower()
        )
        self._finalize_capture()
        return True

    def _on_key_release(self, _widget: Any, event: Any) -> bool:
        """Finalize a modifier-only combo when its keys are released.

        A combo of two or more modifiers (e.g. Alt+Ctrl+Super) has no
        non-modifier trigger; releasing any of its keys completes the capture,
        with the last-pressed modifier acting as the trigger key.  Releasing a
        lone modifier abandons it so a fresh combo can be recorded.
        """
        if not self._recording or self._captured_key is not None:
            return False

        keyval_name = self._gdk.keyval_name(event.keyval)
        if keyval_name is None or keyval_name not in _GDK_MODIFIER_NAMES:
            return True

        if len(self._captured_modifiers) >= 2:
            self._captured_key = self._captured_modifiers[-1]
            self._captured_modifiers = self._captured_modifiers[:-1]
            self._finalize_capture()
            return True

        released = _GDK_MODIFIER_NAMES[keyval_name]
        if released in self._captured_modifiers:
            self._captured_modifiers.remove(released)
        self._new_label.set_text("Press your desired key combo...")
        return True

    def _finalize_capture(self) -> None:
        self._recording = False
        self._new_modifiers = list(self._captured_modifiers)
        self._new_key = self._captured_key
        self._new_label.set_text(
            f"New hotkey: {_format_combo(self._new_modifiers, self._new_key)}"
        )
        self._record_btn.set_label("Record")
        self._record_btn.set_sensitive(True)
        self._save_btn.set_sensitive(True)
        self._on_recording_stop()

    def _on_save_clicked(self, _widget: Any) -> None:
        if self._new_key is None or self._new_modifiers is None:
            return
        try:
            save_hotkey_config(
                self._config_path, self._new_modifiers, self._new_key
            )
            self._on_save(self._new_modifiers, self._new_key)
        except Exception as exc:
            logger.error("Failed to save hotkey config: %s", exc)
            self._new_label.set_text(f"Error saving: {exc}")
            return
        self._window.destroy()

    def _on_cancel_clicked(self, _widget: Any) -> None:
        self._window.destroy()

    def _on_window_destroy(self, _widget: Any) -> None:
        if self._recording:
            self._recording = False
            self._on_recording_stop()
