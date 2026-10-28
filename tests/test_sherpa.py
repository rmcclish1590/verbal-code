"""sherpa-onnx streaming engine (MCC-121): transcriber contract with a fake
recognizer, plus model download/verification with local tarballs."""

import hashlib
import io
import os
import sys
import tarfile
import types

import numpy as np
import pytest

from verbal_code import sherpa_models
from verbal_code.sherpa_models import (
    ensure_sherpa_model_downloaded,
    resolve_transducer_files,
)
from verbal_code.transcriber import SherpaOnnxTranscriber

_KROKO = "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06"


class _FakeStream:
    def __init__(self):
        self.samples = 0
        self.finished = False
        self.text = ""

    def accept_waveform(self, sample_rate, samples):
        assert samples.dtype == np.float32
        assert not self.finished, "audio fed to a finished stream"
        self.samples += len(samples)

    def input_finished(self):
        self.finished = True


class _FakeRecognizer:
    """Hears one word per accepted chunk; an endpoint every ``endpoint_every``
    chunks since the last reset."""

    def __init__(self, endpoint_every=3):
        self.endpoint_every = endpoint_every
        self.streams: list[_FakeStream] = []
        self.resets = 0
        self._chunks_since_reset = 0
        self._word = 0

    def create_stream(self):
        stream = _FakeStream()
        self.streams.append(stream)
        return stream

    def is_ready(self, stream):
        return False

    def decode_stream(self, stream):
        raise AssertionError("is_ready() is False; nothing to decode")

    def is_endpoint(self, stream):
        self._chunks_since_reset += 1
        self._word += 1
        stream.text = (stream.text + f" w{self._word}").strip()
        return self._chunks_since_reset >= self.endpoint_every

    def get_result(self, stream):
        if stream.finished and not stream.text:
            return f" batch {stream.samples} "
        return f" {stream.text} "

    def reset(self, stream):
        self.resets += 1
        self._chunks_since_reset = 0
        stream.text = ""


@pytest.fixture
def model_dir(tmp_path):
    d = tmp_path / _KROKO
    d.mkdir()
    for name in ("encoder.onnx", "decoder.onnx", "joiner.onnx", "tokens.txt"):
        (d / name).write_text("x")
    return d


@pytest.fixture
def fake_sherpa(monkeypatch):
    module = types.SimpleNamespace(calls=[], recognizer=_FakeRecognizer())

    class OnlineRecognizer:
        @staticmethod
        def from_transducer(**kwargs):
            module.calls.append(kwargs)
            return module.recognizer

    module.OnlineRecognizer = OnlineRecognizer
    monkeypatch.setitem(sys.modules, "sherpa_onnx", module)
    return module


def _loaded(model_dir, **kwargs) -> SherpaOnnxTranscriber:
    t = SherpaOnnxTranscriber(
        cpu_threads=4, cache_dir=str(model_dir.parent), **kwargs
    )
    t.load_model()
    return t


_CHUNK = np.zeros(1024, dtype=np.float32)


class TestSherpaTranscriber:
    def test_declares_live_streaming_support(self):
        assert SherpaOnnxTranscriber.supports_live_streaming is True

    def test_load_model_builds_endpointing_transducer(self, fake_sherpa, model_dir):
        _loaded(model_dir)
        kwargs = fake_sherpa.calls[0]
        assert kwargs["encoder"] == str(model_dir / "encoder.onnx")
        assert kwargs["tokens"] == str(model_dir / "tokens.txt")
        assert kwargs["num_threads"] == 4
        assert kwargs["enable_endpoint_detection"] is True
        assert kwargs["provider"] == "cpu"

    def test_yields_only_on_endpoint_without_repeating_text(
        self, fake_sherpa, model_dir
    ):
        t = _loaded(model_dir)
        yielded = [list(t.transcribe_stream(_CHUNK)) for _ in range(6)]

        assert yielded == [[], [], ["w1 w2 w3"], [], [], ["w4 w5 w6"]]
        assert fake_sherpa.recognizer.resets == 2

    def test_stream_finalize_flushes_and_opens_fresh_stream(
        self, fake_sherpa, model_dir
    ):
        t = _loaded(model_dir)
        list(t.transcribe_stream(_CHUNK))  # w1, no endpoint yet
        live = t._stream

        assert t.stream_finalize() == "w1"
        assert live.finished
        assert live.samples > len(_CHUNK)  # tail padding was appended
        assert t._stream is not live and not t._stream.finished

    def test_stream_finalize_before_load_is_empty(self):
        assert SherpaOnnxTranscriber(cpu_threads=1).stream_finalize() == ""

    def test_reset_starts_each_recording_on_a_fresh_stream(
        self, fake_sherpa, model_dir
    ):
        t = _loaded(model_dir)
        list(t.transcribe_stream(_CHUNK))
        old = t._stream
        t.reset()
        assert t._stream is not old and t._stream.samples == 0

    def test_transcribe_batch_uses_a_one_shot_stream(self, fake_sherpa, model_dir):
        t = _loaded(model_dir)
        live = t._stream
        text = t.transcribe_batch(np.zeros(16000, dtype=np.float32))

        assert text.startswith("batch ")
        assert t._stream is live and live.samples == 0  # live stream untouched

    def test_unload_releases_recognizer(self, fake_sherpa, model_dir):
        t = _loaded(model_dir)
        t.unload_model()
        assert t._recognizer is None and t._stream is None


class TestResolveTransducerFiles:
    def test_prefers_int8_weights(self, tmp_path):
        for name in (
            "encoder.onnx", "encoder.int8.onnx", "decoder.int8.onnx",
            "joiner.int8.onnx", "tokens.txt",
        ):
            (tmp_path / name).write_text("x")
        encoder, decoder, joiner, tokens = resolve_transducer_files(str(tmp_path))
        assert os.path.basename(encoder) == "encoder.int8.onnx"
        assert os.path.basename(decoder) == "decoder.int8.onnx"
        assert os.path.basename(joiner) == "joiner.int8.onnx"
        assert os.path.basename(tokens) == "tokens.txt"

    def test_accepts_epoch_style_names(self, tmp_path):
        for part in ("encoder", "decoder", "joiner"):
            (tmp_path / f"{part}-epoch-99-avg-1.onnx").write_text("x")
        (tmp_path / "tokens.txt").write_text("x")
        encoder, *_ = resolve_transducer_files(str(tmp_path))
        assert os.path.basename(encoder) == "encoder-epoch-99-avg-1.onnx"

    def test_missing_files_are_named(self, tmp_path):
        (tmp_path / "encoder.onnx").write_text("x")
        with pytest.raises(FileNotFoundError, match="joiner.*tokens.txt"):
            resolve_transducer_files(str(tmp_path))


def _tarball(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, data in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _serve(monkeypatch, payload: bytes) -> list[str]:
    requested: list[str] = []

    def urlopen(url):
        requested.append(url)
        return io.BytesIO(payload)

    monkeypatch.setattr(sherpa_models.urllib.request, "urlopen", urlopen)
    return requested


class TestEnsureModelDownloaded:
    def test_cached_model_is_used_without_download(self, tmp_path, monkeypatch):
        (tmp_path / _KROKO).mkdir()
        requested = _serve(monkeypatch, b"")
        assert ensure_sherpa_model_downloaded(_KROKO, str(tmp_path)) == str(
            tmp_path / _KROKO
        )
        assert requested == []

    def test_unknown_uncached_model_is_refused(self, tmp_path, monkeypatch):
        requested = _serve(monkeypatch, b"")
        with pytest.raises(ValueError, match="Unknown sherpa-onnx model"):
            ensure_sherpa_model_downloaded("some-other-model", str(tmp_path))
        assert requested == []

    def test_verified_archive_is_extracted(self, tmp_path, monkeypatch):
        payload = _tarball({f"{_KROKO}/tokens.txt": b"tokens"})
        monkeypatch.setitem(
            sherpa_models.SHERPA_MODELS, _KROKO, hashlib.sha256(payload).hexdigest()
        )
        requested = _serve(monkeypatch, payload)

        model_dir = ensure_sherpa_model_downloaded(_KROKO, str(tmp_path))

        assert requested == [
            "https://github.com/k2-fsa/sherpa-onnx/releases/download/"
            f"asr-models/{_KROKO}.tar.bz2"
        ]
        assert (tmp_path / _KROKO / "tokens.txt").read_bytes() == b"tokens"
        assert model_dir == str(tmp_path / _KROKO)
        assert os.listdir(tmp_path) == [_KROKO]  # no temp files left behind

    def test_checksum_mismatch_installs_nothing(self, tmp_path, monkeypatch):
        payload = _tarball({f"{_KROKO}/tokens.txt": b"tampered"})
        monkeypatch.setitem(sherpa_models.SHERPA_MODELS, _KROKO, "0" * 64)
        _serve(monkeypatch, payload)

        with pytest.raises(RuntimeError, match="Checksum mismatch"):
            ensure_sherpa_model_downloaded(_KROKO, str(tmp_path))
        assert os.listdir(tmp_path) == []

    def test_path_traversal_member_is_rejected(self, tmp_path, monkeypatch):
        cache = tmp_path / "cache"
        payload = _tarball({f"{_KROKO}/../../escaped.txt": b"evil"})
        monkeypatch.setitem(
            sherpa_models.SHERPA_MODELS, _KROKO, hashlib.sha256(payload).hexdigest()
        )
        _serve(monkeypatch, payload)

        with pytest.raises(tarfile.FilterError):
            ensure_sherpa_model_downloaded(_KROKO, str(cache))
        # <cache>/.extract-*/<model>/../../escaped.txt would land in <cache>.
        assert os.listdir(cache) == []
