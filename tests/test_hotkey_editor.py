"""Capture-logic tests for the hotkey editor (no GTK required).

The editor instance is created without running __init__; only the state the
key handlers touch is set up, and fake gdk/label/button objects stand in for
GTK. This exercises the modifier-only capture flow from MCC-26.
"""

from verbal_code.hotkey_editor import HotkeyEditorWindow


class _FakeGdk:
    @staticmethod
    def keyval_name(keyval):
        return keyval  # tests pass the GDK key name directly


class _FakeLabel:
    def __init__(self):
        self.text = ""

    def set_text(self, text):
        self.text = text


class _FakeButton:
    def set_label(self, label):
        pass

    def set_sensitive(self, sensitive):
        pass


class _FakeEvent:
    def __init__(self, keyval_name):
        self.keyval = keyval_name


def _make_editor() -> HotkeyEditorWindow:
    editor = object.__new__(HotkeyEditorWindow)
    editor._gdk = _FakeGdk()
    editor._recording = True
    editor._captured_modifiers = []
    editor._captured_key = None
    editor._new_modifiers = None
    editor._new_key = None
    editor._new_label = _FakeLabel()
    editor._record_btn = _FakeButton()
    editor._save_btn = _FakeButton()
    editor._on_recording_stop = lambda: None
    return editor


def _press(editor, name):
    editor._on_key_press(None, _FakeEvent(name))


def _release(editor, name):
    editor._on_key_release(None, _FakeEvent(name))


class TestModifierOnlyCapture:
    def test_three_modifiers_finalize_on_release(self):
        editor = _make_editor()
        _press(editor, "Alt_L")
        _press(editor, "Control_L")
        _press(editor, "Super_L")
        assert editor._recording  # still waiting: could be a 4-key combo
        _release(editor, "Super_L")
        assert not editor._recording
        assert editor._new_modifiers == ["alt", "ctrl"]
        assert editor._new_key == "super"

    def test_last_pressed_modifier_becomes_trigger(self):
        editor = _make_editor()
        _press(editor, "Super_L")
        _press(editor, "Control_L")
        _release(editor, "Control_L")
        assert editor._new_modifiers == ["super"]
        assert editor._new_key == "ctrl"

    def test_single_modifier_release_abandons_capture(self):
        editor = _make_editor()
        _press(editor, "Alt_L")
        _release(editor, "Alt_L")
        assert editor._recording
        assert editor._captured_modifiers == []
        assert editor._new_key is None

    def test_non_modifier_key_still_finalizes_immediately(self):
        editor = _make_editor()
        _press(editor, "Super_L")
        _press(editor, "Alt_L")
        _press(editor, "space")
        assert not editor._recording
        assert editor._new_modifiers == ["super", "alt"]
        assert editor._new_key == "space"

    def test_release_after_normal_finalize_is_ignored(self):
        editor = _make_editor()
        _press(editor, "Super_L")
        _press(editor, "Alt_L")
        _press(editor, "space")
        _release(editor, "Alt_L")  # releasing the chord afterwards
        assert editor._new_modifiers == ["super", "alt"]
        assert editor._new_key == "space"

    def test_repeated_modifier_press_not_duplicated(self):
        editor = _make_editor()
        _press(editor, "Alt_L")
        _press(editor, "Alt_L")  # key-repeat while held
        _press(editor, "Control_L")
        _release(editor, "Alt_L")
        assert editor._new_modifiers == ["alt"]
        assert editor._new_key == "ctrl"
