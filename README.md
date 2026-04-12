# Verbal Code

Real-time speech-to-text dictation for Linux. Hold a hotkey, speak, and your words appear in whatever window is focused — terminal, browser, Slack, email, anywhere.

## How It Works

```
Hold Ctrl+Super+Alt+D → Speak → Release → Text appears in focused window
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
  modifiers: ["ctrl", "super", "alt"]
  key: "d"
```

Any combination of `ctrl`, `alt`, `shift`, `super` plus a trigger key.

### STT Engine

```yaml
stt:
  engine: "whisper"    # or "vosk"
  whisper:
    model: "base"      # tiny|base|small|medium|large-v3
    device: "auto"     # auto|cpu|cuda
    language: "en"
```

**Whisper models** (accuracy vs speed):

| Model    | Size   | Speed   | Accuracy | Best for          |
|----------|--------|---------|----------|-------------------|
| tiny     | ~75MB  | Fastest | Fair     | Quick notes       |
| base     | ~140MB | Fast    | Good     | General use       |
| small    | ~460MB | Medium  | Better   | Emails, messages  |
| medium   | ~1.5GB | Slower  | Great    | Important docs    |
| large-v3 | ~3GB   | Slowest | Best     | GPU recommended   |

### Text Injection

```yaml
injection:
  method: "xdotool"       # xdotool|clipboard|ydotool
  auto_capitalize: true
  trailing_space: true
```

## Architecture

```
verbal-code/
├── config.yaml          # Default configuration
├── install.sh           # One-step installer
├── pyproject.toml       # Python package definition
├── requirements.txt     # Dependencies
└── verbal_code/
    ├── __init__.py      # Package metadata
    ├── __main__.py      # python -m verbal_code entry point
    ├── app.py           # Main orchestrator (wires everything together)
    ├── audio.py         # Microphone capture (sounddevice)
    ├── hotkeys.py       # Global hotkey listener (pynput/evdev)
    ├── injector.py      # Text injection (xdotool/clipboard/ydotool)
    ├── transcriber.py   # STT engines (faster-whisper, vosk)
    └── tray.py          # System tray indicator (GTK3/AppIndicator)
```

## CLI Options

```
verbal-code                    # Run with default/detected config
verbal-code -c /path/to.yaml  # Use specific config file
verbal-code --list-devices     # Show audio input devices
verbal-code --version          # Print version
```

## Requirements

- Linux Mint (or any X11-based Linux desktop)
- Python 3.10+
- A working microphone
- `xdotool` (installed automatically)
- For GPU acceleration: NVIDIA GPU with CUDA toolkit

## Troubleshooting

**No text appears after dictation:**
Check that `xdotool` is installed (`which xdotool`) and that you're on X11, not Wayland. If on Wayland, set `injection.method: "clipboard"` or `"ydotool"` in config.

**"Model not found" error:**
First run downloads the Whisper model. Ensure you have internet access. Models cache in `~/.cache/verbal-code/models/`.

**High latency:**
Switch to a smaller model (`tiny` or `base`) or ensure CUDA is working if you have a GPU. Check `device: "auto"` in config.

**Permission denied on hotkeys:**
pynput needs access to `/dev/input/` devices. Add your user to the `input` group: `sudo usermod -aG input $USER` then log out/in.

**Audio not captured:**
Run `verbal-code --list-devices` to see available inputs. Set `audio.device_index` in config to your mic's index.

## License

MIT
