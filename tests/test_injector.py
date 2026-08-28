import subprocess
from unittest.mock import patch

import pytest

from verbal_code.injector import (
    ClipboardInjector,
    HybridInjector,
    InjectionError,
    XdotoolInjector,
    YdotoolInjector,
    _build_candidate_list,
    create_injector,
)


class TestBuildCandidateList:
    def test_default_order_xdotool_first(self):
        candidates = _build_candidate_list("auto", 0)
        assert isinstance(candidates[0], XdotoolInjector)
        assert isinstance(candidates[1], ClipboardInjector)
        assert isinstance(candidates[2], YdotoolInjector)

    def test_clipboard_preferred(self):
        candidates = _build_candidate_list("clipboard", 0)
        assert isinstance(candidates[0], ClipboardInjector)

    def test_ydotool_preferred(self):
        candidates = _build_candidate_list("ydotool", 0)
        assert isinstance(candidates[0], YdotoolInjector)

    def test_xdotool_preferred(self):
        candidates = _build_candidate_list("xdotool", 50)
        assert isinstance(candidates[0], XdotoolInjector)
        assert candidates[0].typing_delay_ms == 50

    def test_unknown_method_falls_back_to_default(self):
        candidates = _build_candidate_list("unknown_tool", 0)
        assert isinstance(candidates[0], XdotoolInjector)


class TestCreateInjector:
    @patch("verbal_code.injector.shutil.which")
    def test_selects_xdotool_when_available(self, mock_which):
        mock_which.side_effect = (
            lambda cmd: "/usr/bin/xdotool" if cmd == "xdotool" else None
        )
        injector = create_injector({"injection": {"method": "auto"}})
        assert isinstance(injector, XdotoolInjector)

    @patch("verbal_code.injector.shutil.which")
    def test_falls_back_when_nothing_available(self, mock_which):
        mock_which.return_value = None
        injector = create_injector({})
        assert isinstance(injector, XdotoolInjector)

    @patch("verbal_code.injector.shutil.which")
    def test_respects_delay_ms(self, mock_which):
        mock_which.return_value = "/usr/bin/xdotool"
        injector = create_injector(
            {"injection": {"method": "xdotool", "delay_ms": 100}}
        )
        assert isinstance(injector, XdotoolInjector)
        assert injector.typing_delay_ms == 100


class TestWaylandAutoOrder:
    @patch("verbal_code.injector.shutil.which")
    def test_auto_prefers_ydotool_on_wayland(self, mock_which, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        mock_which.return_value = "/usr/bin/anything"  # everything available
        injector = create_injector({"injection": {"method": "auto"}})
        assert isinstance(injector, YdotoolInjector)

    @patch("verbal_code.injector.shutil.which")
    def test_auto_prefers_xdotool_on_x11(self, mock_which, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        mock_which.return_value = "/usr/bin/anything"
        injector = create_injector({"injection": {"method": "auto"}})
        # auto on X11 wraps xdotool typing with clipboard paste for long text
        assert isinstance(injector, HybridInjector)
        assert isinstance(injector._typing, XdotoolInjector)

    @patch("verbal_code.injector.shutil.which")
    def test_explicit_method_overrides_session(self, mock_which, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "wayland")
        mock_which.return_value = "/usr/bin/anything"
        injector = create_injector({"injection": {"method": "xdotool"}})
        assert isinstance(injector, XdotoolInjector)


class _SpyInjector:
    def __init__(self, available=True, fail=False):
        self.available = available
        self.fail = fail
        self.injected: list[str] = []

    def inject(self, text):
        if self.fail:
            raise InjectionError("spy failure")
        self.injected.append(text)

    def is_available(self):
        return self.available


def _completed(returncode=0, stderr="", stdout=""):
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout=stdout, stderr=stderr
    )


class TestInjectionFailuresRaise:
    """MCC-39: a failed injection must raise, never silently succeed."""

    @patch("verbal_code.injector.subprocess.run")
    def test_xdotool_nonzero_exit_raises(self, mock_run):
        mock_run.return_value = _completed(returncode=1, stderr="no display")
        with pytest.raises(InjectionError, match="no display"):
            XdotoolInjector().inject("hello")

    @patch("verbal_code.injector.subprocess.run")
    def test_xdotool_timeout_raises(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="xdotool", timeout=10)
        with pytest.raises(InjectionError, match="timed out"):
            XdotoolInjector().inject("hello")

    @patch("verbal_code.injector.subprocess.run")
    def test_ydotool_nonzero_exit_raises(self, mock_run):
        mock_run.return_value = _completed(returncode=1, stderr="no uinput")
        with pytest.raises(InjectionError, match="no uinput"):
            YdotoolInjector().inject("hello")

    @patch("verbal_code.injector.subprocess.run")
    def test_ydotool_missing_binary_raises(self, mock_run):
        mock_run.side_effect = FileNotFoundError("ydotool")
        with pytest.raises(InjectionError, match="not installed"):
            YdotoolInjector().inject("hello")

    @patch("verbal_code.injector.subprocess.run")
    def test_clipboard_write_failure_raises(self, mock_run):
        mock_run.side_effect = [
            _completed(stdout="UTF8_STRING"),  # TARGETS query
            _completed(stdout="previous"),  # read of existing clipboard
            _completed(returncode=1),  # xclip write fails
        ]
        with pytest.raises(InjectionError, match="xclip write failed"):
            ClipboardInjector().inject("hello")

    @patch("verbal_code.injector.time.sleep")
    @patch("verbal_code.injector.subprocess.run")
    def test_clipboard_paste_failure_skips_restore_and_raises(
        self, mock_run, _sleep
    ):
        mock_run.side_effect = [
            _completed(stdout="UTF8_STRING"),  # TARGETS query
            _completed(stdout="previous"),  # read of existing clipboard
            _completed(),  # xclip write succeeds
            _completed(returncode=1, stderr="keystroke lost"),  # paste fails
        ]
        with pytest.raises(InjectionError, match="paste keystroke failed"):
            ClipboardInjector().inject("hello")
        # No further call: the clipboard is NOT restored, so the dictated
        # text stays recoverable via manual paste.
        assert mock_run.call_count == 4

    @patch("verbal_code.injector.time.sleep")
    @patch("verbal_code.injector.subprocess.run")
    def test_clipboard_success_restores_clipboard(self, mock_run, _sleep):
        mock_run.side_effect = [
            _completed(stdout="UTF8_STRING"),  # TARGETS query
            _completed(stdout="previous"),  # read of existing clipboard
            _completed(),  # xclip write
            _completed(),  # paste keystroke
            _completed(stdout="hello"),  # race check: still our text
            _completed(),  # restore write
        ]
        ClipboardInjector().inject("hello")
        assert mock_run.call_count == 6

    def test_hybrid_falls_back_to_typing_when_paste_raises(self):
        typing = _SpyInjector()
        clipboard = _SpyInjector(fail=True)
        long_text = "x" * 500
        HybridInjector(typing, clipboard, threshold=100).inject(long_text)
        assert typing.injected == [long_text]


class TestClipboardSafety:
    """MCC-43: never clobber the clipboard with an empty or stale restore."""

    @patch("verbal_code.injector.time.sleep")
    @patch("verbal_code.injector.subprocess.run")
    def test_nontext_clipboard_is_not_restored(self, mock_run, _sleep):
        mock_run.side_effect = [
            _completed(stdout="image/png\nTARGETS"),  # non-text content
            _completed(),  # xclip write
            _completed(),  # paste keystroke
        ]
        ClipboardInjector().inject("hello")
        # No read, no restore: an image cannot be round-tripped, so the
        # dictated text stays on the clipboard instead of an empty string.
        assert mock_run.call_count == 3

    @patch("verbal_code.injector.time.sleep")
    @patch("verbal_code.injector.subprocess.run")
    def test_unreadable_clipboard_skips_restore(self, mock_run, _sleep):
        mock_run.side_effect = [
            subprocess.TimeoutExpired(cmd="xclip", timeout=10),  # TARGETS
            _completed(),  # xclip write
            _completed(),  # paste keystroke
        ]
        ClipboardInjector().inject("hello")
        assert mock_run.call_count == 3

    @patch("verbal_code.injector.time.sleep")
    @patch("verbal_code.injector.subprocess.run")
    def test_empty_clipboard_skips_restore(self, mock_run, _sleep):
        mock_run.side_effect = [
            _completed(returncode=1),  # TARGETS: no clipboard owner
            _completed(),  # xclip write
            _completed(),  # paste keystroke
        ]
        ClipboardInjector().inject("hello")
        assert mock_run.call_count == 3

    @patch("verbal_code.injector.time.sleep")
    @patch("verbal_code.injector.subprocess.run")
    def test_user_copy_during_settle_window_wins(self, mock_run, _sleep):
        mock_run.side_effect = [
            _completed(stdout="UTF8_STRING"),  # TARGETS query
            _completed(stdout="previous"),  # read of existing clipboard
            _completed(),  # xclip write
            _completed(),  # paste keystroke
            _completed(stdout="user copied this"),  # race check: changed
        ]
        ClipboardInjector().inject("hello")
        # The user's copy wins: no restore write happens.
        assert mock_run.call_count == 5


class TestHybridInjector:
    def test_short_text_is_typed(self):
        typing, clipboard = _SpyInjector(), _SpyInjector()
        HybridInjector(typing, clipboard, threshold=100).inject("short")
        assert typing.injected == ["short"]
        assert clipboard.injected == []

    def test_long_text_is_pasted(self):
        typing, clipboard = _SpyInjector(), _SpyInjector()
        long_text = "x" * 100
        HybridInjector(typing, clipboard, threshold=100).inject(long_text)
        assert clipboard.injected == [long_text]
        assert typing.injected == []

    def test_falls_back_to_typing_when_clipboard_unavailable(self):
        typing, clipboard = _SpyInjector(), _SpyInjector(available=False)
        long_text = "x" * 500
        HybridInjector(typing, clipboard, threshold=100).inject(long_text)
        assert typing.injected == [long_text]

    @patch("verbal_code.injector.shutil.which")
    def test_auto_on_x11_returns_hybrid(self, mock_which, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        mock_which.return_value = "/usr/bin/anything"
        injector = create_injector({"injection": {"method": "auto"}})
        assert isinstance(injector, HybridInjector)
        assert injector.threshold == 100

    @patch("verbal_code.injector.shutil.which")
    def test_zero_threshold_disables_hybrid(self, mock_which, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
        mock_which.return_value = "/usr/bin/anything"
        injector = create_injector(
            {"injection": {"method": "auto", "clipboard_threshold": 0}}
        )
        assert isinstance(injector, XdotoolInjector)

    @patch("verbal_code.injector.shutil.which")
    def test_explicit_method_never_wrapped(self, mock_which, monkeypatch):
        monkeypatch.setenv("XDG_SESSION_TYPE", "x11")
        mock_which.return_value = "/usr/bin/anything"
        injector = create_injector({"injection": {"method": "xdotool"}})
        assert isinstance(injector, XdotoolInjector)
