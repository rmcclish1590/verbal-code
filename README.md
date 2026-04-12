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
  engine: "whisper"    # or "vosk"
  whisper:
    model: "base"      # tiny|base|small|medium|large-v3
    device: "auto"     # auto|cpu|cuda
    compute_type: "int8"
    language: "en"
    beam_size: 5
  vosk:
    model_name: "vosk-model-small-en-us-0.15"
```

**Whisper models** (accuracy vs speed):

| Model    | Size   | Speed   | Accuracy | Best for          |
|----------|--------|---------|----------|-------------------|
| tiny     | ~75MB  | Fastest | Fair     | Quick notes       |
| base     | ~140MB | Fast    | Good     | General use       |
| small    | ~460MB | Medium  | Better   | Emails, messages  |
| medium   | ~1.5GB | Slower  | Great    | Important docs    |
| large-v3 | ~3GB   | Slowest | Best     | GPU recommended   |

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

### Voice Activity Detection

```yaml
vad:
  enabled: true        # requires torch (optional, ~2GB)
  threshold: 0.5
  min_speech_ms: 250
  silence_ms: 500
```

VAD uses Silero to filter silence from the audio stream, reducing unnecessary transcription work. If `torch` is not installed, VAD is skipped gracefully.

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
├── config.yaml          # Default configuration
├── install.sh           # One-step installer
├── pyproject.toml       # Python package definition
├── requirements.txt     # Dependencies
└── verbal_code/
    ├── __init__.py      # Package metadata (version)
    ├── __main__.py      # python -m verbal_code entry point
    ├── app.py           # Main orchestrator, config validation, CLI
    ├── audio.py         # Microphone capture (sounddevice)
    ├── hotkeys.py       # Global hotkey listener (pynput)
    ├── injector.py      # Text injection (xdotool/clipboard/ydotool)
    ├── transcriber.py   # STT engines (faster-whisper, vosk)
    ├── tray.py          # System tray indicator (GTK3/AppIndicator)
    └── vad.py           # Voice activity detection (Silero VAD)
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

## License

MIT
