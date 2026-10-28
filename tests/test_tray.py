"""Tray Model menu with every engine (MCC-16 regression, MCC-125).

GTK is replaced by minimal fakes so the menu-building and check-mark logic
runs without a display.
"""

from verbal_code.transcriber import AVAILABLE_MODELS
from verbal_code.tray import SystemTray


class _FakeMenuItem:
    def __init__(self, label=""):
        self.label = label
        self.submenu = None
        self.handlers = []

    def connect(self, signal, handler, *args):
        self.handlers.append((signal, handler, args))

    def set_label(self, label):
        self.label = label

    def set_submenu(self, submenu):
        self.submenu = submenu

    def activate(self):
        for _signal, handler, args in self.handlers:
            handler(self, *args)


class _FakeMenu:
    def __init__(self):
        self.items = []

    def append(self, item):
        self.items.append(item)


class _FakeGtk:
    MenuItem = _FakeMenuItem
    Menu = _FakeMenu


class _ImmediateGLib:
    @staticmethod
    def idle_add(func, *args):
        func(*args)


_MODEL_MENU = [(engine, models) for engine, models in AVAILABLE_MODELS.items()]


def _tray(current, selected):
    tray = SystemTray(
        on_model_selected=lambda engine, model: selected.append((engine, model)),
        model_menu=_MODEL_MENU,
        current_model=current,
    )
    tray._gtk = _FakeGtk
    tray._glib = _ImmediateGLib
    tray._available = True
    return tray


def _labels(root):
    return [item.label for item in root.submenu.items]


class TestModelMenu:
    def test_lists_every_engine_model_with_one_check_mark(self):
        tray = _tray(("parakeet", "nemo-parakeet-tdt-0.6b-v2"), [])
        root = tray._build_model_submenu()

        expected = [
            (engine, model) for engine, models in _MODEL_MENU for model in models
        ]
        assert root.label == "Model"
        for (engine, model), label in zip(expected, _labels(root), strict=True):
            assert label.strip().endswith(f"{engine}: {model}")
        checked = [label for label in _labels(root) if label.startswith("✓")]
        assert checked == ["✓ parakeet: nemo-parakeet-tdt-0.6b-v2"]

    def test_set_model_moves_the_check_mark(self):
        tray = _tray(("parakeet", "nemo-parakeet-tdt-0.6b-v2"), [])
        root = tray._build_model_submenu()
        sherpa = AVAILABLE_MODELS["sherpa"][1]

        tray.set_model("sherpa", sherpa)

        checked = [label for label in _labels(root) if label.startswith("✓")]
        assert checked == [f"✓ sherpa: {sherpa}"]

    def test_clicks_dispatch_except_on_the_current_model(self):
        selected: list[tuple[str, str]] = []
        tray = _tray(("whisper", "distil-small.en"), selected)
        tray._build_model_submenu()
        items = tray._model_items

        items[("whisper", "distil-small.en")].activate()  # already active
        items[("vosk", "vosk-model-small-en-us-0.15")].activate()
        items[("parakeet", "nemo-parakeet-tdt-0.6b-v3")].activate()

        assert selected == [
            ("vosk", "vosk-model-small-en-us-0.15"),
            ("parakeet", "nemo-parakeet-tdt-0.6b-v3"),
        ]
