#!/usr/bin/env python3
"""On-device STT benchmark: latency, real-time factor, memory, and accuracy.

Runs every installed engine/model from the tray's model catalog over one or
more WAV clips and prints a comparison table.  Each engine/model runs in its
own subprocess, so peak RSS is per model and an engine that is missing, fails
to load, or crashes is reported and skipped instead of aborting the run.

Batch engines (parakeet, whisper, moonshine) are timed on ``transcribe_batch``
— the work done after hotkey release.  Live engines (sherpa, vosk) are fed
the clip in capture-sized chunks like a real dictation; ``latency`` is then
the ``stream_finalize`` flush at release and ``RTF`` covers all streaming
compute.

Examples::

    # Record a 5s and a 15s clip from the mic, then benchmark everything:
    python scripts/benchmark_cpu.py --record

    # Existing clips; a reference transcript gives a WER column:
    python scripts/benchmark_cpu.py --wav five.wav --wav fifteen.wav \\
        --reference "first clip text" --reference "second clip text"

    # Just two engines:
    python scripts/benchmark_cpu.py --wav five.wav --engines parakeet,whisper

A ``<clip>.txt`` file next to a WAV is used as its reference automatically.
Models download on first use, so the first run of a model is slow.
"""

import argparse
import logging
import multiprocessing as mp
import os
import re
import resource
import statistics
import sys
import time
import traceback
import wave
from dataclasses import dataclass, field

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

SAMPLE_RATE = 16000
CHUNK_SAMPLES = 1024  # AudioCapture's default chunk size
RECORD_SECONDS = (5, 15)


@dataclass
class Clip:
    name: str
    audio: np.ndarray
    reference: str | None = None

    @property
    def seconds(self) -> float:
        return len(self.audio) / SAMPLE_RATE


@dataclass
class ClipResult:
    clip: str
    latency_ms: float
    rtf: float
    text: str
    wer: float | None


@dataclass
class ModelResult:
    engine: str
    model: str
    live: bool = False
    load_s: float | None = None
    peak_rss_mb: float | None = None
    clips: list[ClipResult] = field(default_factory=list)
    error: str | None = None


# --- Audio ----------------------------------------------------------------


def load_wav(path: str) -> np.ndarray:
    """Read a PCM WAV as mono float32 at 16 kHz.

    Multi-channel audio is averaged to mono; other rates are linearly
    resampled, which is plenty for benchmarking (not for production audio).
    """
    with wave.open(path, "rb") as wf:
        width = wf.getsampwidth()
        channels = wf.getnchannels()
        rate = wf.getframerate()
        frames = wf.readframes(wf.getnframes())
    if width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2**31
    elif width == 1:
        audio = (np.frombuffer(frames, dtype=np.uint8).astype(np.float32) - 128) / 128
    else:
        raise ValueError(f"{path}: unsupported {8 * width}-bit WAV")
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(audio):
        n = int(round(len(audio) * SAMPLE_RATE / rate))
        audio = np.interp(
            np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio
        )
    return audio.astype(np.float32)


def record_clips(seconds_list=RECORD_SECONDS) -> list[Clip]:
    """Record one clip per duration from the default microphone."""
    from verbal_code.audio import AudioCapture

    clips = []
    for seconds in seconds_list:
        input(f"Press Enter, then speak for {seconds}s... ")
        capture = AudioCapture(sample_rate=SAMPLE_RATE)
        capture.start()
        time.sleep(seconds)
        clips.append(Clip(f"rec-{seconds}s", capture.stop()))
    return clips


# --- Accuracy -------------------------------------------------------------


def _words(text: str) -> list[str]:
    """Lowercase words with punctuation dropped, so engines that punctuate
    and capitalise aren't penalised against plain references."""
    return re.sub(r"[^\w\s']", " ", text.lower()).split()


def word_error_rate(reference: str, hypothesis: str) -> float:
    """(substitutions + deletions + insertions) / reference word count."""
    ref, hyp = _words(reference), _words(hypothesis)
    if not ref:
        return 0.0 if not hyp else 1.0
    previous = list(range(len(hyp) + 1))
    for i, ref_word in enumerate(ref, 1):
        current = [i] + [0] * len(hyp)
        for j, hyp_word in enumerate(hyp, 1):
            current[j] = min(
                previous[j] + 1,
                current[j - 1] + 1,
                previous[j - 1] + (ref_word != hyp_word),
            )
        previous = current
    return previous[-1] / len(ref)


# --- Benchmark (runs inside a child process) -------------------------------


def _peak_rss_mb() -> float:
    # ru_maxrss is in KiB on Linux.
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024


def _time_batch(transcriber, clip: Clip, runs: int) -> tuple[float, float, str]:
    transcriber.transcribe_batch(clip.audio)  # untimed warm-up pass
    times, text = [], ""
    for _ in range(runs):
        t0 = time.perf_counter()
        text = transcriber.transcribe_batch(clip.audio)
        times.append(time.perf_counter() - t0)
    latency = statistics.median(times)
    return latency * 1000, latency / clip.seconds, text


def _time_live(transcriber, clip: Clip, runs: int) -> tuple[float, float, str]:
    finalize_times, compute_times, text = [], [], ""
    for _ in range(runs + 1):  # first pass is an untimed warm-up
        transcriber.reset()
        parts: list[str] = []
        t0 = time.perf_counter()
        for start in range(0, len(clip.audio), CHUNK_SAMPLES):
            parts.extend(
                transcriber.transcribe_stream(clip.audio[start : start + CHUNK_SAMPLES])
            )
        t1 = time.perf_counter()
        parts.append(transcriber.stream_finalize())
        t2 = time.perf_counter()
        compute_times.append(t2 - t0)
        finalize_times.append(t2 - t1)
        text = " ".join(p for p in parts if p)
    finalize = statistics.median(finalize_times[1:])
    rtf = statistics.median(compute_times[1:]) / clip.seconds
    return finalize * 1000, rtf, text


def benchmark_model(
    engine: str, model: str, clips: list[Clip], runs: int, cpu_threads: int | None
) -> ModelResult:
    from verbal_code.transcriber import apply_selection, create_transcriber

    result = ModelResult(engine, model)
    try:
        config: dict = {"audio": {"sample_rate": SAMPLE_RATE}, "stt": {}}
        if cpu_threads:
            config["stt"]["cpu_threads"] = cpu_threads
        apply_selection(config, engine, model)
        transcriber = create_transcriber(config)
        result.live = transcriber.supports_live_streaming

        t0 = time.perf_counter()
        transcriber.load_model()
        result.load_s = time.perf_counter() - t0

        timer = _time_live if result.live else _time_batch
        for clip in clips:
            latency_ms, rtf, text = timer(transcriber, clip, runs)
            wer = word_error_rate(clip.reference, text) if clip.reference else None
            result.clips.append(ClipResult(clip.name, latency_ms, rtf, text, wer))
    except Exception as exc:  # noqa: BLE001 — report and move on
        result.error = f"{type(exc).__name__}: {exc}".splitlines()[0][:120]
        logging.debug("%s", traceback.format_exc())
    result.peak_rss_mb = _peak_rss_mb()
    return result


def _child(queue, *args) -> None:
    logging.getLogger("verbal_code").setLevel(logging.WARNING)
    queue.put(benchmark_model(*args))


def run_isolated(
    engine: str, model: str, clips: list[Clip], runs: int, cpu_threads: int | None
) -> ModelResult:
    """Benchmark one model in a fresh process (true per-model peak RSS;
    a crash in native code can't take the whole run down)."""
    ctx = mp.get_context("spawn")
    queue = ctx.Queue()
    proc = ctx.Process(
        target=_child, args=(queue, engine, model, clips, runs, cpu_threads)
    )
    proc.start()
    try:
        result = queue.get()
    except Exception as exc:  # noqa: BLE001
        result = ModelResult(engine, model, error=f"no result: {exc}")
    proc.join()
    if proc.exitcode not in (0, None) and result.error is None and not result.clips:
        result.error = f"process exited with code {proc.exitcode}"
    return result


# --- Report ---------------------------------------------------------------


def format_table(results: list[ModelResult]) -> str:
    header = (
        "engine", "model", "mode", "load s", "clip", "latency ms", "RTF",
        "peak MB", "WER", "text",
    )
    rows: list[tuple[str, ...]] = []
    for r in results:
        mode = "live" if r.live else "batch"
        if r.error:
            rows.append((r.engine, r.model, "-", "-", "-", "-", "-", "-", "-",
                         f"SKIPPED: {r.error}"))
            continue
        for i, c in enumerate(r.clips):
            text = c.text if len(c.text) <= 48 else c.text[:45] + "..."
            rows.append((
                r.engine if i == 0 else "",
                r.model if i == 0 else "",
                mode if i == 0 else "",
                f"{r.load_s:.1f}" if i == 0 and r.load_s is not None else "",
                c.clip,
                f"{c.latency_ms:.0f}",
                f"{c.rtf:.3f}",
                f"{r.peak_rss_mb:.0f}" if i == 0 and r.peak_rss_mb else "",
                f"{c.wer:.1%}" if c.wer is not None else "-",
                text,
            ))
    widths = [max(len(str(row[i])) for row in (header, *rows)) for i in range(10)]
    line = "  ".join
    out = [line(h.ljust(w) for h, w in zip(header, widths, strict=True))]
    out.append(line("-" * w for w in widths))
    out += [line(c.ljust(w) for c, w in zip(row, widths, strict=True)) for row in rows]
    return "\n".join(out)


# --- CLI ------------------------------------------------------------------


def _model_plan(engines_arg: str | None, models_arg: str | None):
    from verbal_code.transcriber import AVAILABLE_MODELS, installed_engines

    wanted = engines_arg.split(",") if engines_arg else list(AVAILABLE_MODELS)
    only_models = set(models_arg.split(",")) if models_arg else None
    installed = set(installed_engines())
    plan, skipped = [], []
    for engine in wanted:
        if engine not in AVAILABLE_MODELS:
            skipped.append(ModelResult(engine, "-", error="unknown engine"))
            continue
        for model in AVAILABLE_MODELS[engine]:
            if only_models and model not in only_models:
                continue
            if engine not in installed:
                skipped.append(ModelResult(engine, model, error="not installed"))
            else:
                plan.append((engine, model))
    return plan, skipped


def _load_clips(args) -> list[Clip]:
    clips = record_clips() if args.record else []
    for path in args.wav or []:
        sidecar = os.path.splitext(path)[0] + ".txt"
        reference = None
        if os.path.isfile(sidecar):
            with open(sidecar) as f:
                reference = f.read().strip()
        clips.append(Clip(os.path.basename(path), load_wav(path), reference))
    # Explicit --reference values win, matched to clips in order.
    for clip, reference in zip(clips, args.reference or [], strict=False):
        clip.reference = reference
    return clips


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--wav", action="append", help="WAV clip (repeatable)")
    parser.add_argument(
        "--record", action="store_true", help="record a 5s and a 15s clip"
    )
    parser.add_argument(
        "--reference", action="append", help="reference text per clip, in order"
    )
    parser.add_argument("--engines", help="comma-separated engines (default: all)")
    parser.add_argument("--models", help="comma-separated models to restrict to")
    parser.add_argument("--runs", type=int, default=3, help="timed runs per clip")
    parser.add_argument("--cpu-threads", type=int, help="override stt.cpu_threads")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)

    if not args.wav and not args.record:
        parser.error("give at least one --wav, or --record")
    clips = _load_clips(args)
    plan, results = _model_plan(args.engines, args.models)

    print(f"{os.cpu_count()} logical CPUs; clips: " + ", ".join(
        f"{c.name} ({c.seconds:.1f}s)" for c in clips
    ))
    for engine, model in plan:
        print(f"  benchmarking {engine} / {model} ...", flush=True)
        results.append(run_isolated(engine, model, clips, args.runs, args.cpu_threads))

    order = {e: i for i, (e, _) in enumerate(plan)}
    results.sort(key=lambda r: (r.error is not None, order.get(r.engine, 99)))
    print()
    print(format_table(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
