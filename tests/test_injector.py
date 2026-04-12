from unittest.mock import patch

from verbal_code.injector import (
    ClipboardInjector,
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
