"""Tests for the Wayland/evdev hotkey path — no evdev package required."""

from verbal_code.hotkeys import create_hotkey_listener, is_wayland_session
from verbal_code.hotkeys_evdev import ComboState, evdev_key_name


class TestEvdevKeyName:
    def test_modifiers(self):
        assert evdev_key_name("KEY_LEFTCTRL") == "ctrl"
        assert evdev_key_name("KEY_RIGHTCTRL") == "ctrl"
        assert evdev_key_name("KEY_LEFTMETA") == "super"
        assert evdev_key_name("KEY_RIGHTALT") == "alt"

    def test_letters_and_digits(self):
        assert evdev_key_name("KEY_D") == "d"
        assert evdev_key_name("KEY_5") == "5"

    def test_special_keys(self):
        assert evdev_key_name("KEY_SPACE") == "space"
        assert evdev_key_name("KEY_ENTER") == "enter"
        assert evdev_key_name("KEY_ESC") == "esc"

    def test_alias_list_uses_first(self):
        assert evdev_key_name(["KEY_ENTER", "KEY_KPENTER"]) == "enter"

    def test_unknown_codes_return_none(self):
        assert evdev_key_name("KEY_F13") is None
        assert evdev_key_name("BTN_LEFT") is None
        assert evdev_key_name("") is None


class TestComboState:
    def test_activates_when_full_combo_held(self):
        combo = ComboState(["super", "alt"], "space")
        assert not combo.press("super")
        assert not combo.press("alt")
        assert combo.press("space")
        assert combo.active

    def test_deactivates_on_any_release(self):
        combo = ComboState(["super", "alt"], "space")
        combo.press("super")
        combo.press("alt")
        combo.press("space")
        assert combo.release("alt")
        assert not combo.active

    def test_modifier_only_combo(self):
        combo = ComboState(["alt", "ctrl"], "super")
        combo.press("alt")
        combo.press("ctrl")
        assert combo.press("super")
        assert combo.release("super")

    def test_none_keys_ignored(self):
        combo = ComboState(["super"], "space")
        assert not combo.press(None)
        combo.press("super")
        combo.press("space")
        assert not combo.release(None)
        assert combo.active

    def test_no_double_activation_while_held(self):
        combo = ComboState(["super"], "space")
        combo.press("super")
        assert combo.press("space")
        assert not combo.press("space")  # key repeat


class TestListenerFactory:
    def _noop(self):
        pass

    def test_x11_uses_pynput_listener(self, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        assert not is_wayland_session()
        listener = create_hotkey_listener(["super"], "space", self._noop, self._noop)
        assert type(listener).__name__ == "HotkeyListener"

    def test_wayland_uses_evdev_listener(self, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        assert is_wayland_session()
        try:
            import evdev  # noqa: F401

            expected = "EvdevHotkeyListener"
        except ImportError:
            expected = "HotkeyListener"  # graceful fallback without evdev
        listener = create_hotkey_listener(["super"], "space", self._noop, self._noop)
        assert type(listener).__name__ == expected

    def test_wayland_display_alone_counts(self, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "")
        monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
        assert is_wayland_session()
