# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Verbal Code is a push-to-talk speech-to-text daemon for Linux (built for Linux Mint): hold a hotkey, speak, release, and the transcription is typed into whatever window is focused. Pure Python, no web stack, no build step.

## Commands

The app installs **editable from this repo** into a dedicated venv (`~/.local/share/verbal-code/venv`, created by `./install.sh`), so merged changes are live after restarting the app. Use that venv's interpreter for everything — pytest and ruff are installed there, not globally:

```bash
VENV=~/.local/share/verbal-code/venv/bin
$VENV/python -m pytest -q                          # full suite (~1s, no audio hardware needed)
$VENV/python -m pytest tests/test_injector.py -q   # one file
$VENV/python -m pytest -k "clipboard" -q           # by keyword
$VENV/python -m ruff check .                       # lint (config in pyproject.toml)
```

Run the app: `verbal-code` (launcher) or `$VENV/python -m verbal_code`. Diagnostic flags: `--list-devices`, `--test-audio`, `--test-transcribe`, `--test-inject`, `-c <config>`. User config lives at `~/.config/verbal-code/config.yaml`; the repo's `config.yaml` is the commented template `install.sh` copies there.

## Architecture

`verbal_code/app.py` holds `VerbalCode`, the orchestrator that wires everything; the other modules are subsystems it composes:

- **`audio.py`** — `AudioCapture` buffers mic chunks (sounddevice callback → list); a read cursor lets the streaming consumer walk the same list that `stop()` concatenates for batch transcription, so audio is never stored twice. `trim_silence` is the energy-based VAD.
- **`transcriber.py`** — `TranscriberBase` with Whisper (faster-whisper, batched), Vosk, and Moonshine backends. The key contract is `supports_live_streaming`: True only when `transcribe_stream` yields *final* text the engine will never revise (Vosk). Whisper/Moonshine partials are revisable, so they must never be injected live — batch transcription on hotkey release is their only output path. Also owns the tray quick-switch model catalog (`AVAILABLE_MODELS`, `current_selection`, `apply_selection`).
- **`injector.py`** — injection strategies (xdotool / ydotool for Wayland / clipboard-paste / Hybrid that pastes past a length threshold) plus `TextProcessor` (spoken punctuation commands, sentence capitalization carried across segments). **Injectors must raise `InjectionError` on failure, never log-and-return** — the app converts exceptions into the error tray state; a swallowed failure silently loses the user's dictation (MCC-39). The clipboard injector only save/restores plain-text clipboards and skips the restore whenever that could destroy data (MCC-43).
- **`hotkeys.py` / `hotkeys_evdev.py`** — two listener implementations behind one callback contract. `create_hotkey_listener` picks pynput on X11 and the evdev listener on Wayland (reads `/dev/input`; requires the user in the `input` group). `ComboState` in the evdev module is the pure, evdev-free state machine used for unit tests.
- **`tray.py`** — GTK AppIndicator. GTK runs on its own thread; every UI mutation must go through `GLib.idle_add` (see `set_state`/`set_model`). Tray menu callbacks arrive on the GTK thread — hand real work to another thread (model switches do).
- **`config_store.py`** — `update_config(path, mutate)` is the **only** way to write the user's config: ruamel.yaml round-trip (preserves the comments that document every option), atomic temp-file + `os.replace`, process-wide lock. Never `yaml.safe_dump` over the user's config (MCC-40). Reading still uses PyYAML (`load_config` in app.py).

### Concurrency model

Hotkey callbacks, the streaming loop, model switches, and the max-duration watchdog all run on separate threads. Two locks in `VerbalCode` keep them coherent: `_dictation_lock` guards the recording start/stop transitions, and `_model_switch_lock` serializes tray switches. A model switch loads the new transcriber from a **copy** of the config and commits the swap (config + `self.transcriber` + `_live_injection`) atomically under `_dictation_lock`, cancelling if a dictation started mid-load (MCC-44). The streaming thread starts only when `_live_injection` is true — running it for revisable-partial engines is O(n²) CPU for nothing (MCC-42).

### Config validation is fail-fast

`validate_config` exits (via `sys.exit(1)`) on bad values: unknown `stt.engine`, bad `hotkey.mode`, numeric values outside `_NUMERIC_CONFIG_BOUNDS`, non-16k sample rate with Whisper. Add new numeric options to the bounds table rather than ad-hoc checks.

## Testing conventions

Tests construct a bare `VerbalCode` via `object.__new__(VerbalCode)` and assign fakes directly (see `_make_app` in `tests/test_app_dictation.py`, `test_model_switch.py`, `test_model_persistence.py`). **If you add an attribute that any dictation/switch code path reads, you must also add it to those helpers** or previously-green tests fail with AttributeError. Subprocess-driven injectors are tested by mocking `subprocess.run` with ordered `side_effect` lists — the call sequence is part of the assertion.

## Privacy rule

Transcribed text is whatever the user speaks — treat it like a password. Never log transcript content at INFO or by default; content logging is gated behind `logging.log_transcripts` (default off, MCC-38). Keep new logging to metadata (char counts, durations).

## Workflow

- Linear (team "McClish Products", project "Verbal-Code", issues `MCC-NN`) is the backlog's source of truth. One branch/PR per issue, branch name = Linear's suggested `gitBranchName`; after merge, delete the branch and comment the PR link on the issue.
- Update `CHANGELOG.md` (Keep a Changelog, `[Unreleased]` section) with every user-visible change, referencing the MCC issue.
- `specs/` are historical slice documents, not current requirements. `docs/sherpa-onnx-evaluation.md` sketches a possible future `stt.engine: "sherpa"` backend.
