from pynput.keyboard import Key, KeyCode

from verbal_code.hotkeys import _normalize_key, _SPECIAL_KEY_MAP


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


class TestSpecialKeyMap:
    def test_space_maps_to_key_space(self):
        assert _SPECIAL_KEY_MAP["space"] is Key.space

    def test_tab_maps_to_key_tab(self):
        assert _SPECIAL_KEY_MAP["tab"] is Key.tab

    def test_escape_and_esc_both_map(self):
        assert _SPECIAL_KEY_MAP["esc"] is Key.esc
        assert _SPECIAL_KEY_MAP["escape"] is Key.esc
