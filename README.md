# Verbal Code

Real-time speech-to-text dictation for Linux. Hold a hotkey, speak, and your words appear in whatever window is focused — terminal, browser, Slack, email, anywhere.

## How It Works

```
Hold Super+Alt+Space → Speak → Release → Text appears in focused window
```

Verbal Code runs as a lightweight daemon with a system tray icon. When you hold the hotkey:

1. **Red mic icon** — recording your voice
2. **Yellow icon** — processing final transcription
3. **Gray icon** — idle, ready for next dictation

The final text is injected directly into the focused input field using `xdotool`, so it works in any application that accepts keyboard input.

## Quick Start

```bash
git clone <this-repo> verbal-code
cd verbal-code
chmod +x install.sh
./install.sh
```

The installer handles everything: system packages, Python venv, the parakeet, sherpa and whisper engines plus any optional extras (moonshine, vosk), and config file creation. Re-run it after pulling to update an existing install.

Then run:

```bash
verbal-code
```

To uninstall:

```bash
./uninstall.sh            # keeps your custom dictionary for a later reinstall
./uninstall.sh --purge    # removes the dictionary too
```

The uninstaller removes the app, venv, config and downloaded models, but
leaves your dictionary (`~/.config/verbal-code/dictionary.json`, or your
`dictionary.path`) in place; reinstalling picks it up automatically.

## Configuration

Config lives at `~/.config/verbal-code/config.yaml`. Key settings:

### Hotkey

```yaml
hotkey:
  modifiers: ["super", "alt"]
  key: "space"
```

Any combination of `ctrl`, `alt`, `shift`, `super` plus a trigger key. Special keys like `space`, `tab`, `enter` are supported. Modifier-only combos work too — set `key` to a modifier name (e.g. `modifiers: ["alt", "ctrl"]`, `key: "super"` for Alt+Ctrl+Super); in the hotkey dialog, hold the modifiers and release to capture such a combo.

`mode` selects how the hotkey behaves: `"hold"` (default) is push-to-talk — recording lasts while the chord is held; `"toggle"` starts recording on one press and stops on the next, so long dictations don't require holding the chord.

### STT Engine

```yaml
stt:
  engine: "parakeet"   # or "sherpa", "whisper", "moonshine", "vosk"
  streaming_enabled: false  # live injection while recording (see below)
  cpu_threads: 6       # optional; default = one per physical CPU core
  whisper:
    model: "distil-small.en" # see table below
    device: "auto"           # auto|cpu|cuda
    compute_type: "int8"
    language: "en"
    beam_size: 2          # 2 = fast; 5 = slightly more accurate, ~2x slower on CPU
    batch_size: 8            # parallel-decode batch for the batched pipeline
    initial_prompt: ""       # vocabulary hint, e.g. names/jargon to spell
  parakeet:
    model: "nemo-parakeet-tdt-0.6b-v2"  # or "nemo-parakeet-tdt-0.6b-v3" (multilingual)
    quantization: "int8"     # "" = full-precision model
  sherpa:
    model: "sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06"
    # or "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25"
  moonshine:
    model: "moonshine/base"  # or "moonshine/tiny"
  vosk:
    model_name: "vosk-model-small-en-us-0.15"
```

`streaming_enabled` runs incremental transcription while you hold the hotkey.
With the **sherpa** or **vosk** engine, each utterance is injected live into the
focused window as it finalises (a pause ends an utterance) — words appear while
you speak, and releasing the hotkey just flushes the last utterance. Parakeet,
Whisper, and Moonshine have no final-text streaming, so with those engines the
setting has no effect and the text arrives in one batch on release. Off by
default: streaming costs continuous inference during recording.

**Whisper models** (accuracy vs speed):

- **whisper** — batched single-pass on release; widest model choice. Used when
  `stt.engine` is unset.
- **parakeet** (template default) — NVIDIA Parakeet TDT (INT8, onnxruntime): faster and more
  accurate than Whisper's distil models on CPU, with punctuation and
  capitalisation. Batch on release; recordings over 25s are split at pauses.
  Downloads from Hugging Face on first use (~660 MB).
- **sherpa** — sherpa-onnx streaming transducers for live dictation with
  `streaming_enabled: true`: punctuated, capitalised text appears after each
  pause. Models are downloaded from the sherpa-onnx GitHub releases and
  verified against a pinned SHA-256 before use.
- **moonshine** — fast English-only ASR on onnxruntime (no torch). Lowest
  latency on weak CPUs; great for short dictation. `base` ≈ Whisper-base
  accuracy, `tiny` is faster. Optional: pick it in the installer.
- **vosk** — lightweight streaming recognizer; lowest resource use, lower
  accuracy. Optional: pick it in the installer.

With whisper, transcription runs as a single batched pass on release via faster-whisper's
`BatchedInferencePipeline`, which segments the audio with Silero VAD and decodes
segments in parallel — several times faster than a sequential pass on multi-segment
audio. `condition_on_previous_text` is disabled to avoid repetition/hallucination
loops on short dictations.

**Recommended presets.** The template config ships the push-to-talk preset:

```yaml
# Push-to-talk: text arrives in one batch on hotkey release.
stt:
  engine: "parakeet"
  streaming_enabled: false
  parakeet:
    model: "nemo-parakeet-tdt-0.6b-v2"
```

```yaml
# Live streaming: each utterance is typed as soon as you pause.
stt:
  engine: "sherpa"
  streaming_enabled: true
  sherpa:
    model: "sherpa-onnx-nemotron-speech-streaming-en-0.6b-560ms-int8-2026-04-25"
```

`stt.cpu_threads` (1–256) sets the inference threads for parakeet, sherpa, and
whisper; leave it unset to use one thread per physical CPU core.

**Whisper models** (accuracy vs speed). For English the `.en` / `distil` variants
are more accurate than the multilingual models at the same size:

| Model             | Size   | Speed   | Accuracy | Best for                     |
|-------------------|--------|---------|----------|------------------------------|
| tiny.en           | ~75MB  | Fastest | Fair     | Quick notes, weak CPUs       |
| base.en           | ~140MB | Fast    | Good     | General use                  |
| distil-small.en   | ~330MB | Medium  | Better   | Default — balanced on CPU    |
| small.en          | ~460MB | Medium  | Better+  | Emails, messages             |
| distil-medium.en  | ~790MB | Slower  | Better+  | More accuracy on CPU         |
| distil-large-v3.5 | ~1.5GB | Slow    | Great    | Best Whisper accuracy on CPU |
| large-v3-turbo    | ~1.6GB | Slow    | Great    | GPU recommended              |

Whisper runs one CTranslate2 thread per physical CPU core (6 on a Ryzen 5
5600G) instead of CTranslate2's default of 4.

### Audio

```yaml
audio:
  sample_rate: 16000   # must stay 16000 for the whisper engine
  channels: 1
  chunk_size: 1024
  device: null         # null = default mic, or device index
```

The whisper engine requires 16 kHz input (faster-whisper does not resample raw
audio); the app refuses to start with another rate. Vosk accepts other rates.

### Text Injection

```yaml
injection:
  method: "auto"           # auto|xdotool|clipboard|ydotool
  delay_ms: 0              # delay between keystrokes, in ms PER CHARACTER
  clipboard_threshold: 100 # auto only: paste texts this long instead of typing
```

`delay_ms` is the pause between each simulated keystroke, not a one-time delay —
at 50 a 200-character dictation takes 10 seconds to appear. Leave it at 0 unless
an application drops characters.

With `method: auto`, short dictations are typed (feels natural, no clipboard
touch) while dictations of `clipboard_threshold` characters or more are pasted
via the clipboard, landing instantly regardless of length. Set it to `0` to
always type; an explicit `method` disables the automatic switch entirely.

`punctuation_commands` (default on) turns spoken commands into punctuation and
formatting: "period" / "full stop", "comma", "question mark", "exclamation
mark", "colon", "semicolon", "ellipsis", "new line", and "new paragraph".
Sentence starts are capitalised automatically — "hello period how are you"
becomes `Hello. How are you`. Set it to `false` to type such words literally.

### Voice Activity Detection

```yaml
vad:
  trim_silence: true       # trim leading/trailing silence before transcription
  trim_threshold_db: -40.0 # frames quieter than this (dBFS) count as silence
```

Before batch transcription, leading and trailing silence is trimmed with a
lightweight energy-based detector (no extra dependencies). Whisper additionally
segments speech internally with faster-whisper's built-in Silero VAD; the trim
mainly helps Vosk and Moonshine, which otherwise receive the raw capture. A
recording with no audible speech at all skips transcription entirely. Raise the
threshold towards `-30` in noisy environments, or lower it towards `-50` if
quiet speech gets clipped.

### Dictionary

```yaml
dictionary:
  enabled: true
  fuzzy_threshold: 0.82  # 0-1; lower catches more mishearings, higher is stricter
  path: null             # defaults to ~/.config/verbal-code/dictionary.json
```

A persisted list of custom terms — names, jargon, acronyms — that corrects
transcription output before injection. Known misheard variants are replaced
exactly; anything close enough (via fuzzy matching) is corrected too, so you
don't have to anticipate every way a term gets mangled. Corrections happen
before punctuation commands and capitalization. Empty until you add terms
(no behavior change out of the box).

Manage entries from the tray menu (**Dictionary...**): search, add, edit,
enable/disable, and delete terms. Auto-learned entries (none exist yet —
that's future work) would show a ✨ marker.

### System Tray

```yaml
tray:
  enabled: true
  notifications: true
```

The tray menu shows the current status and active engine/model. The **Model**
submenu switches between the models of every installed engine on the fly — the
new model loads in the background and the choice is saved to the config file.

### Logging

```yaml
logging:
  level: "INFO"        # DEBUG|INFO|WARNING|ERROR
  file: null           # or path to log file
```

Every completed dictation logs its end-to-end latency (hotkey release →
text on screen) as a single greppable line: `dictation_latency_ms=432`.

## Architecture

```
verbal-code/
├── assets/
│   └── verbal-code.svg  # Application icon (installed to ~/.local/share/icons/)
├── config.yaml          # Default configuration (copied to ~/.config/verbal-code/ on install)
├── install.sh           # One-step installer
├── uninstall.sh         # Uninstaller (removes venv, config, cache, launcher; keeps dictionary unless --purge)
├── pyproject.toml       # Python package definition
├── requirements.txt     # Dependencies
└── verbal_code/
    ├── __init__.py      # Package metadata (version)
    ├── __main__.py      # python -m verbal_code entry point
    ├── app.py           # Main orchestrator, config validation, CLI
    ├── audio.py         # Microphone capture (sounddevice)
    ├── hotkeys.py       # Global hotkey listener (pynput)
    ├── injector.py      # Text injection (xdotool/clipboard/ydotool)
    ├── transcriber.py   # STT engines (faster-whisper, parakeet, sherpa-onnx, moonshine, vosk)
    ├── sherpa_models.py # sherpa-onnx model download + checksum verification
    └── tray.py          # System tray indicator (GTK3, Ayatana/AppIndicator)
```

## CLI Options

```
verbal-code                      # Run with default/detected config
verbal-code -c /path/to.yaml    # Use specific config file
verbal-code --list-devices       # Show audio input devices
verbal-code --test-audio         # Record 3s, save to WAV
verbal-code --test-transcribe    # Record 5s, transcribe, print result
verbal-code --test-inject        # Inject test text into focused window
verbal-code --version            # Print version
verbal-code --help               # Show all options
```

## Benchmarking engines

`scripts/benchmark_cpu.py` compares every installed engine/model on your own
hardware: cold-load time, latency, real-time factor (RTF), peak memory, and —
given a reference transcript — word error rate.

```bash
VENV=~/.local/share/verbal-code/venv/bin
$VENV/python scripts/benchmark_cpu.py --record                 # record a 5s + 15s clip
$VENV/python scripts/benchmark_cpu.py --wav a.wav --wav b.wav  # or use WAV files
$VENV/python scripts/benchmark_cpu.py --wav a.wav --engines parakeet,whisper
```

A `a.txt` next to `a.wav` (or `--reference "..."`) adds a WER column. For batch
engines latency is the transcription on release; for live engines (sherpa,
vosk) it is the final flush on release, and RTF covers all streaming compute.
Each model runs in its own process, so memory is per model and an engine that
isn't installed or fails to load is listed as skipped. Models download on
first use.

## Requirements

- Linux Mint (or any X11-based Linux desktop; Wayland works with extra setup, see below)
- Python 3.10+
- A working microphone
- `xdotool` (installed automatically by `install.sh`)
- For GPU acceleration: NVIDIA GPU with CUDA toolkit

### Wayland

On a Wayland session the app switches automatically:

- **Hotkeys** are read straight from the kernel input devices via `evdev`
  (Wayland compositors don't expose global keyboard events). Your user must be
  able to read `/dev/input`: `sudo usermod -aG input $USER`, then log out and
  back in.
- **Injection** prefers `ydotool`. Install it (`sudo apt install ydotool`) and
  make sure the `ydotoold` daemon is running; `xdotool`/`xclip` only reach
  XWayland windows and are kept as a last resort.

## Troubleshooting

**No text appears after dictation:**
On X11, check that `xdotool` is installed (`which xdotool`). On Wayland, install `ydotool` and ensure the `ydotoold` daemon is running — injection prefers it there automatically.

**Hotkey does nothing on Wayland:**
The evdev listener needs read access to `/dev/input`. Add your user to the `input` group (`sudo usermod -aG input $USER`), log out and back in. The log says which listener is in use at startup.

**"Model not found" error:**
First run downloads the selected model (Parakeet ~660 MB with the default config). Ensure you have internet access. Models cache in `~/.cache/huggingface/` (Whisper, Parakeet), `~/.cache/verbal-code/sherpa-onnx/` (sherpa), or `~/.cache/verbal-code/models/` (Vosk).

**High latency:**
Switch to a smaller model (`tiny` or `base`) or ensure CUDA is working if you have a GPU. Check `device: "auto"` in config.

**Permission denied on hotkeys:**
pynput needs access to `/dev/input/` devices. Add your user to the `input` group: `sudo usermod -aG input $USER` then log out/in.

**Audio not captured:**
Run `verbal-code --list-devices` to see available inputs. Set `audio.device` in config to your mic's device index.

**STT engine not installed:**
If the app says an engine's package isn't installed, run the installer again (it upgrades the existing venv). Parakeet, sherpa and whisper are always installed; moonshine and vosk are optional extras — choose them in the installer, or install manually from the repo: `~/.local/share/verbal-code/venv/bin/pip install -e '.[moonshine,vosk]'`

**`Python.h: No such file or directory` / "Failed building wheel for evdev" during install:**
`pynput` pulls in `evdev`, which compiles from source on Python versions without a prebuilt wheel and needs the Python development headers. Install them and re-run the installer: `sudo apt install -y python3-dev` (current `install.sh` does this automatically).

## License

MIT
