"""scripts/benchmark_cpu.py helpers (MCC-126) — no real models."""

import importlib.util
import os
import wave

import numpy as np
import pytest

_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "benchmark_cpu.py")
_spec = importlib.util.spec_from_file_location("benchmark_cpu", _SCRIPT)
bench = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bench)


class TestWordErrorRate:
    def test_exact_match_ignores_case_and_punctuation(self):
        assert bench.word_error_rate("ask not what", "Ask not, what.") == 0.0

    def test_counts_substitutions_insertions_deletions(self):
        ref = "the quick brown fox"
        assert bench.word_error_rate(ref, "the quick red fox") == 0.25
        assert bench.word_error_rate(ref, "the quick brown fox jumps") == 0.25
        assert bench.word_error_rate(ref, "quick brown fox") == 0.25

    def test_keeps_apostrophes(self):
        assert bench.word_error_rate("it's here", "its here") == 0.5

    def test_empty_reference(self):
        assert bench.word_error_rate("", "") == 0.0
        assert bench.word_error_rate("", "noise") == 1.0


def _write_wav(path, samples: np.ndarray, rate: int, channels: int) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.astype("<i2").tobytes())


class TestLoadWav:
    def test_16k_mono_round_trips(self, tmp_path):
        pcm = (np.sin(np.linspace(0, 100, 16000)) * 16000).astype(np.int16)
        _write_wav(tmp_path / "a.wav", pcm, 16000, 1)
        audio = bench.load_wav(str(tmp_path / "a.wav"))
        assert audio.dtype == np.float32 and len(audio) == 16000
        assert np.allclose(audio, pcm / 32768.0, atol=1e-6)

    def test_stereo_48k_becomes_mono_16k(self, tmp_path):
        frames = 48000  # 1 second
        left = np.full(frames, 8192, dtype=np.int16)
        right = np.zeros(frames, dtype=np.int16)
        interleaved = np.column_stack([left, right]).ravel()
        _write_wav(tmp_path / "s.wav", interleaved, 48000, 2)
        audio = bench.load_wav(str(tmp_path / "s.wav"))
        assert len(audio) == 16000
        assert np.allclose(audio, 0.125, atol=1e-6)  # (0.25 + 0) / 2


class _FakeBatch:
    supports_live_streaming = False

    def __init__(self):
        self.batch_calls = 0

    def load_model(self):
        pass

    def transcribe_batch(self, audio):
        self.batch_calls += 1
        return "The quick brown fox."


class _FakeLive:
    supports_live_streaming = True

    def __init__(self):
        self.chunks = 0
        self.finalizes = 0
        self._pass_chunks = 0

    def load_model(self):
        pass

    def reset(self):
        self._pass_chunks = 0

    def transcribe_stream(self, chunk):
        self.chunks += 1
        self._pass_chunks += 1
        if self._pass_chunks == 3:  # an endpoint mid-pass
            yield "the quick"

    def stream_finalize(self):
        self.finalizes += 1
        return "brown fox"


def _clip(seconds=1.0, reference="the quick brown fox"):
    return bench.Clip("c", np.zeros(int(16000 * seconds), np.float32), reference)


@pytest.fixture
def fake_engine(monkeypatch):
    import verbal_code.transcriber as transcriber_module

    made = []

    def factory(engine_cls):
        def create(config):
            made.append(engine_cls())
            return made[-1]

        monkeypatch.setattr(transcriber_module, "create_transcriber", create)
        return made

    return factory


class TestBenchmarkModel:
    def test_batch_engine_times_transcribe_batch(self, fake_engine):
        made = fake_engine(_FakeBatch)
        result = bench.benchmark_model("parakeet", "m", [_clip()], 2, None)

        assert result.error is None and not result.live
        assert made[0].batch_calls == 3  # warm-up + 2 timed runs
        (clip,) = result.clips
        assert clip.wer == 0.0
        assert clip.latency_ms >= 0 and clip.rtf >= 0
        assert result.peak_rss_mb > 0

    def test_live_engine_streams_chunks_and_times_finalize(self, fake_engine):
        made = fake_engine(_FakeLive)
        result = bench.benchmark_model("sherpa", "m", [_clip(seconds=0.5)], 2, None)

        assert result.live and result.error is None
        chunks_per_pass = -(-8000 // bench.CHUNK_SAMPLES)  # ceil
        assert made[0].finalizes == 3  # warm-up + 2 timed passes
        assert made[0].chunks == 3 * chunks_per_pass
        assert result.clips[0].text == "the quick brown fox"

    def test_failure_is_reported_not_raised(self, fake_engine):
        class _Broken(_FakeBatch):
            def load_model(self):
                raise RuntimeError("model download failed\nlong traceback")

        fake_engine(_Broken)
        result = bench.benchmark_model("whisper", "m", [_clip()], 1, None)
        assert result.error == "RuntimeError: model download failed"
        assert result.clips == []


class TestPlanAndReport:
    def test_missing_engines_are_skipped_with_a_reason(self, monkeypatch):
        import verbal_code.transcriber as transcriber_module

        monkeypatch.setattr(
            transcriber_module, "installed_engines", lambda: ["parakeet"]
        )
        plan, skipped = bench._model_plan("parakeet,vosk,bogus", None)

        assert plan == [
            ("parakeet", m) for m in transcriber_module.AVAILABLE_MODELS["parakeet"]
        ]
        reasons = {(r.engine, r.error) for r in skipped}
        assert ("vosk", "not installed") in reasons
        assert ("bogus", "unknown engine") in reasons

    def test_table_shows_results_and_skips(self):
        ok = bench.ModelResult("parakeet", "v2", load_s=1.5, peak_rss_mb=900)
        ok.clips.append(bench.ClipResult("five.wav", 120.4, 0.024, "Hi.", 0.0))
        skipped = bench.ModelResult("vosk", "small", error="not installed")

        table = bench.format_table([ok, skipped])

        assert "parakeet" in table and "120" in table and "0.0%" in table
        assert "SKIPPED: not installed" in table
