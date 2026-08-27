import threading

from pynput.keyboard import Key, KeyCode

from verbal_code.hotkeys import _SPECIAL_KEY_MAP, HotkeyListener, _normalize_key


class TestNormalizeKey:
    def test_key_enum_returns_itself(self):
        assert _normalize_key(Key.space) is Key.space

    def test_keycode_with_char(self):
        assert _normalize_key(KeyCode.from_char("A")) == "a"

    def test_keycode_lowercase(self):
        assert _normalize_key(KeyCode.from_char("d")) == "d"

    def test_none_returns_none(self):
        assert _normalize_key(None) is None

    def test_modifier_key_returns_itself(self):
        assert _normalize_key(Key.ctrl_l) is Key.ctrl_l

    def test_control_char_falls_back_to_vk(self):
        # With Ctrl held, pynput reports 'd' as '\x04'; vk must win.
        assert _normalize_key(KeyCode(char="\x04", vk=100)) == "d"


class TestSpecialKeyMap:
    def test_space_maps_to_key_space(self):
        assert _SPECIAL_KEY_MAP["space"] is Key.space

    def test_tab_maps_to_key_tab(self):
        assert _SPECIAL_KEY_MAP["tab"] is Key.tab

    def test_escape_and_esc_both_map(self):
        assert _SPECIAL_KEY_MAP["esc"] is Key.esc
        assert _SPECIAL_KEY_MAP["escape"] is Key.esc


class _Callback:
    """Records invocations; hotkey callbacks run on daemon threads."""

    def __init__(self):
        self.event = threading.Event()

    def __call__(self):
        self.event.set()

    def fired(self) -> bool:
        return self.event.wait(timeout=2.0)


def _make_listener(modifiers, key):
    activate, deactivate = _Callback(), _Callback()
    listener = HotkeyListener(
        modifiers=modifiers,
        key=key,
        on_activate=activate,
        on_deactivate=deactivate,
    )
    return listener, activate, deactivate


class TestModifierOnlyCombo:
    def test_activates_on_all_modifiers_held(self):
        listener, activate, _ = _make_listener(["alt", "ctrl"], "super")
        listener._on_press(Key.alt_l)
        listener._on_press(Key.ctrl_l)
        assert not listener.is_active
        listener._on_press(Key.cmd_l)
        assert activate.fired()
        assert listener.is_active

    def test_deactivates_on_any_release(self):
        listener, activate, deactivate = _make_listener(["alt", "ctrl"], "super")
        listener._on_press(Key.alt_l)
        listener._on_press(Key.ctrl_l)
        listener._on_press(Key.cmd_l)
        assert activate.fired()
        listener._on_release(Key.ctrl_l)
        assert deactivate.fired()
        assert not listener.is_active

    def test_trigger_modifier_release_deactivates(self):
        listener, activate, deactivate = _make_listener(["alt", "ctrl"], "super")
        listener._on_press(Key.ctrl_l)
        listener._on_press(Key.alt_l)
        listener._on_press(Key.cmd_r)  # right-hand variant works too
        assert activate.fired()
        listener._on_release(Key.cmd_r)
        assert deactivate.fired()

    def test_normal_key_trigger_still_works(self):
        listener, activate, _ = _make_listener(["super", "alt"], "space")
        listener._on_press(Key.cmd_l)
        listener._on_press(Key.alt_l)
        listener._on_press(Key.space)
        assert activate.fired()
