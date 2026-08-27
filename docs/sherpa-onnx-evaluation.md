# Evaluation: sherpa-onnx as the streaming STT backend

_MCC-21, evaluated 2026-08-27._

## Question

Would [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) (k2-fsa's ONNX
runtime for Kaldi-family models) be a better streaming backend than Vosk for
live injection?

## What sherpa-onnx offers

- **Streaming Zipformer transducer models** producing true incremental
  partial results with built-in endpointing — the recognizer reports
  utterance boundaries itself, the same contract our live-injection path
  (`supports_live_streaming` + `stream_finalize()`) was designed around.
- **onnxruntime only** — no torch, aligned with the project's dependency
  posture after MCC-18. `pip install sherpa-onnx` ships prebuilt wheels.
- **Active maintenance** — model releases continuing through 2026 (e.g.
  int8 streaming Zipformer builds dated 2026); Vosk's small English model
  has not been updated since 2020.
- **Better accuracy than vosk-small** at comparable CPU cost: streaming
  Zipformer en (~20M params, int8-quantized ~40–80 MB) benchmarks well below
  vosk-small-en-us-0.15's WER on common English test sets while decoding
  faster than real time on modest CPUs.
- A first-party [real-time microphone example](https://k2-fsa.github.io/sherpa/onnx/python/real-time-speech-recongition-from-a-microphone.html)
  matching our capture model (16 kHz float32 chunks).

## Fit with the current architecture

The `TranscriberBase` contract added for MCC-11 maps directly:

| Our contract | sherpa-onnx equivalent |
|---|---|
| `transcribe_stream(chunk)` yields final text | `OnlineRecognizer` + `stream.accept_waveform()`; emit text when `is_endpoint()` fires |
| `stream_finalize()` | `input_finished()` + final `get_result()` |
| `transcribe_batch(audio)` | feed the whole array, then finalize (or use an offline Zipformer model) |
| `supports_live_streaming = True` | endpointed results are final — same guarantee Vosk gives, at better accuracy |

A `SherpaOnnxTranscriber` is an estimated 100–150 lines following the
`VoskTranscriber` shape, plus an entry in `AVAILABLE_MODELS`/`_ENGINE_PACKAGES`
so the tray's model switcher picks it up automatically.

## Costs and risks

- **Model distribution**: unlike Vosk, the Python package does not
  auto-download models; we would ship a small downloader (models are tarballs
  on GitHub releases / HuggingFace) and cache under
  `~/.cache/verbal-code/models`, as done for Vosk.
- **Three-file models** (encoder/decoder/joiner) mean slightly more config
  surface than a single model name; hide it behind a catalog of named
  presets.
- **API churn**: sherpa-onnx iterates quickly; pin `sherpa-onnx>=1.10,<2`.
- The English streaming models are larger than vosk-small (~40–80 MB int8 vs
  ~40 MB) — negligible in practice.

## Recommendation

**Adopt** as an optional fourth engine (`stt.engine: "sherpa"`) in a future
slice, keeping Vosk as the minimal-footprint fallback. It upgrades the
live-injection path (MCC-11) from vosk-small accuracy to near-Whisper-base
accuracy while keeping true streaming finality, and its offline models are a
credible alternative for the batch path too. Effort estimate: one slice
(transcriber class, model downloader, catalog entries, docs, tests with a
fake recognizer).

Not adopted now because live injection just landed on Vosk and deserves
real-world usage feedback first; nothing in the current design blocks the
addition.

## Sources

- [sherpa-onnx documentation](https://k2-fsa.github.io/sherpa/onnx/index.html)
- [Streaming Zipformer transducer models](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/zipformer-transducer-models.html)
- [Real-time microphone recognition example](https://k2-fsa.github.io/sherpa/onnx/python/real-time-speech-recongition-from-a-microphone.html)
- [Online transducer model list](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-transducer/index.html)
