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

The installer handles everything: system packages, Python venv, STT model selection, and config file creation.

Then run:

```bash
verbal-code
```

To uninstall completely:

```bash
./uninstall.sh
```

## Configuration

Config lives at `~/.config/verbal-code/config.yaml`. Key settings:

### Hotkey

```yaml
hotkey:
  modifiers: ["super", "alt"]
  key: "space"
```

Any combination of `ctrl`, `alt`, `shift`, `super` plus a trigger key. Special keys like `space`, `tab`, `enter` are supported.

### STT Engine

```yaml
stt:
  engine: "whisper"          # "whisper" | "moonshine" | "vosk"
  whisper:
    model: "distil-small.en" # see table below
    device: "auto"           # auto|cpu|cuda
    compute_type: "int8"
    language: "en"
    beam_size: 5
    batch_size: 8            # parallel-decode batch for the batched pipeline
    initial_prompt: ""       # vocabulary hint, e.g. names/jargon to spell
  moonshine:
    model: "moonshine/base"  # or "moonshine/tiny"
  vosk:
    model_name: "vosk-model-small-en-us-0.15"
```

**Engines:**

- **whisper** (default) — most accurate; batched single-pass on release.
- **moonshine** — fast English-only ASR on onnxruntime (no torch). Lowest
  latency on weak CPUs; great for short dictation. `base` ≈ Whisper-base
  accuracy, `tiny` is faster. Install with `pip install useful-moonshine-onnx`.
- **vosk** — lightweight streaming recognizer; lowest resource use, lower accuracy.

Transcription runs as a single batched pass on hotkey release via faster-whisper's
`BatchedInferencePipeline`, which segments the audio with Silero VAD and decodes
segments in parallel — several times faster than a sequential pass on multi-segment
audio. `condition_on_previous_text` is disabled to avoid repetition/hallucination
loops on short dictations.

**Whisper models** (accuracy vs speed). For English the `.en` / `distil` variants
are more accurate than the multilingual models at the same size:

| Model           | Size   | Speed   | Accuracy | Best for                  |
|-----------------|--------|---------|----------|---------------------------|
| tiny.en         | ~75MB  | Fastest | Fair     | Quick notes, weak CPUs    |
| base.en         | ~140MB | Fast    | Good     | General use               |
| distil-small.en | ~330MB | Medium  | Better   | Default — balanced on CPU |
| small.en        | ~460MB | Medium  | Better+  | Emails, messages          |
| large-v3-turbo  | ~1.6GB | Slower  | Great    | GPU recommended           |

### Audio

```yaml
audio:
  sample_rate: 16000
  channels: 1
  chunk_size: 1024
  device: null         # null = default mic, or device index
```

### Text Injection

```yaml
injection:
  method: "auto"       # auto|xdotool|clipboard|ydotool
  delay_ms: 50
```

> **Note:** Voice-activity detection no longer needs a separate `torch`/`silero-vad`
> install. The Whisper pipeline segments speech with faster-whisper's bundled Silero
> VAD (onnxruntime), and Moonshine/Vosk handle short audio directly.

### System Tray

```yaml
tray:
  enabled: true
  notifications: true
```

### Logging

```yaml
logging:
  level: "INFO"        # DEBUG|INFO|WARNING|ERROR
  file: null           # or path to log file
```

## Architecture

```
verbal-code/
├── assets/
│   └── verbal-code.svg  # Application icon (installed to ~/.local/share/icons/)
├── config.yaml          # Default configuration (copied to ~/.config/verbal-code/ on install)
├── install.sh           # One-step installer
├── uninstall.sh         # Full uninstaller (removes venv, config, cache, launcher)
├── pyproject.toml       # Python package definition
├── requirements.txt     # Dependencies
└── verbal_code/
    ├── __init__.py      # Package metadata (version)
    ├── __main__.py      # python -m verbal_code entry point
    ├── app.py           # Main orchestrator, config validation, CLI
    ├── audio.py         # Microphone capture (sounddevice)
    ├── hotkeys.py       # Global hotkey listener (pynput)
    ├── injector.py      # Text injection (xdotool/clipboard/ydotool)
    ├── transcriber.py   # STT engines (faster-whisper, moonshine, vosk)
    └── tray.py          # System tray indicator (GTK3/AppIndicator)
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

## Requirements

- Linux Mint (or any X11-based Linux desktop)
- Python 3.10+
- A working microphone
- `xdotool` (installed automatically by `install.sh`)
- For GPU acceleration: NVIDIA GPU with CUDA toolkit

## Troubleshooting

**No text appears after dictation:**
Check that `xdotool` is installed (`which xdotool`) and that you're on X11, not Wayland. If on Wayland, set `injection.method: "clipboard"` or `"ydotool"` in config.

**"Model not found" error:**
First run downloads the Whisper model. Ensure you have internet access. Models cache in `~/.cache/huggingface/` (Whisper) or `~/.cache/verbal-code/models/` (Vosk).

**High latency:**
Switch to a smaller model (`tiny` or `base`) or ensure CUDA is working if you have a GPU. Check `device: "auto"` in config.

**Permission denied on hotkeys:**
pynput needs access to `/dev/input/` devices. Add your user to the `input` group: `sudo usermod -aG input $USER` then log out/in.

**Audio not captured:**
Run `verbal-code --list-devices` to see available inputs. Set `audio.device` in config to your mic's device index.

**STT engine not installed:**
If you see `ModuleNotFoundError: No module named 'faster_whisper'`, run the installer again or manually install: `~/.local/share/verbal-code/venv/bin/pip install faster-whisper`

**`Python.h: No such file or directory` / "Failed building wheel for evdev" during install:**
`pynput` pulls in `evdev`, which compiles from source on Python versions without a prebuilt wheel and needs the Python development headers. Install them and re-run the installer: `sudo apt install -y python3-dev` (current `install.sh` does this automatically).

## License

MIT
