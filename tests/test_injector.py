from unittest.mock import patch

from verbal_code.injector import (
    ClipboardInjector,
    HybridInjector,
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
        mock_which.side_effect = lambda cmd: "/usr/bin/xdotool" if cmd == "xdotool" else None
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
        injector = create_injector({"injection": {"method": "xdotool", "delay_ms": 100}})
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
    def __init__(self, available=True):
        self.available = available
        self.injected: list[str] = []

    def inject(self, text):
        self.injected.append(text)

    def is_available(self):
        return self.available


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
