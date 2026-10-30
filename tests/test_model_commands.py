"""--list-models / --set-model / --download-model: the CLI install.sh uses to
pick and pre-download the speech model (MCC-130)."""

import sys

import pytest

from verbal_code import app
from verbal_code.app import main
from verbal_code.transcriber import AVAILABLE_MODELS


class _FakeTranscriber:
    def __init__(self, downloaded=False, error=None):
        self.downloaded = downloaded
        self.error = error
        self.downloads = 0

    def is_model_downloaded(self):
        return self.downloaded

    def download_model(self):
        self.downloads += 1
        if self.error is not None:
            raise self.error


@pytest.fixture
def fake_transcriber(monkeypatch):
    transcriber = _FakeTranscriber()
    monkeypatch.setattr(
        "verbal_code.transcriber.create_transcriber", lambda config: transcriber
    )
    return transcriber


class TestListModels:
    def test_lists_installed_engines_models(self, capsys, monkeypatch):
        monkeypatch.setattr(
            "verbal_code.transcriber.installed_engines", lambda: ["parakeet"]
        )
        app._run_list_models()
        lines = capsys.readouterr().out.splitlines()
        assert lines == [f"parakeet {m}" for m in AVAILABLE_MODELS["parakeet"]]


class TestSetModel:
    def test_saves_selection_and_keeps_comments(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text('stt:\n  engine: "whisper"  # keep me\n')
        config: dict = {"stt": {"engine": "whisper"}}

        app._run_set_model(
            config, str(path), "parakeet", "nemo-parakeet-tdt_ctc-110m"
        )

        text = path.read_text()
        assert "# keep me" in text
        assert "nemo-parakeet-tdt_ctc-110m" in text
        saved = app.load_config(str(path))
        assert saved["stt"]["engine"] == "parakeet"
        # The in-memory config follows, so --download-model fetches the new one.
        assert config["stt"]["parakeet"]["model"] == "nemo-parakeet-tdt_ctc-110m"

    def test_unknown_model_exits_without_writing(self, tmp_path, capsys):
        path = tmp_path / "config.yaml"
        path.write_text("stt: {}\n")
        with pytest.raises(SystemExit) as exc:
            app._run_set_model({}, str(path), "parakeet", "no-such-model")
        assert exc.value.code == 2
        assert path.read_text() == "stt: {}\n"
        assert "nemo-parakeet-tdt-0.6b-v2" in capsys.readouterr().err

    def test_missing_config_file_exits(self):
        with pytest.raises(SystemExit) as exc:
            app._run_set_model({}, None, "parakeet", "nemo-parakeet-tdt-0.6b-v2")
        assert exc.value.code == 1


class TestDownloadModel:
    def test_downloads_a_missing_model(self, fake_transcriber, capsys):
        app._run_download_model({"stt": {"engine": "parakeet"}})
        assert fake_transcriber.downloads == 1
        assert "is ready" in capsys.readouterr().out

    def test_skips_a_cached_model(self, fake_transcriber, capsys):
        fake_transcriber.downloaded = True
        app._run_download_model({"stt": {"engine": "parakeet"}})
        assert fake_transcriber.downloads == 0
        assert "already downloaded" in capsys.readouterr().out

    def test_failure_exits_1_with_advice(self, fake_transcriber, capsys):
        fake_transcriber.error = OSError("connection reset")
        with pytest.raises(SystemExit) as exc:
            app._run_download_model({"stt": {"engine": "parakeet"}})
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "connection reset" in err
        assert "verbal-code --download-model" in err

    def test_interrupt_exits_130(self, fake_transcriber, capsys):
        fake_transcriber.error = KeyboardInterrupt()
        with pytest.raises(SystemExit) as exc:
            app._run_download_model({"stt": {"engine": "parakeet"}})
        assert exc.value.code == 130
        assert "interrupted" in capsys.readouterr().err


class TestMainDispatch:
    @pytest.fixture(autouse=True)
    def _isolate(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("HOME", str(tmp_path))
        monkeypatch.setattr(app, "setup_logging", lambda config: None)

    def test_set_model_then_download_in_one_call(self, tmp_path, monkeypatch):
        path = tmp_path / "config.yaml"
        path.write_text("stt:\n  engine: parakeet\n")
        downloaded = []
        monkeypatch.setattr(app, "_run_download_model", downloaded.append)
        monkeypatch.setattr(
            "sys.argv",
            [
                "verbal-code", "-c", str(path), "--set-model",
                "parakeet", "nemo-parakeet-tdt-0.6b-v3", "--download-model",
            ],
        )
        with pytest.raises(SystemExit) as exc:
            main()
        assert exc.value.code == 0
        assert downloaded[0]["stt"]["parakeet"]["model"] == (
            "nemo-parakeet-tdt-0.6b-v3"
        )

    def test_download_runs_after_validation(self, monkeypatch):
        monkeypatch.setattr("sys.argv", ["verbal-code", "--download-model"])
        monkeypatch.setattr(app, "validate_config", lambda config: sys.exit(1))
        monkeypatch.setattr(
            app,
            "_run_download_model",
            lambda config: pytest.fail("downloaded before validate_config"),
        )
        with pytest.raises(SystemExit):
            main()
