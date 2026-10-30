# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Verbal Code is a push-to-talk speech-to-text daemon for Linux (built for Linux Mint): hold a hotkey, speak, release, and the transcription is typed into whatever window is focused. Pure Python, no web stack, no build step.

## Commands

The app installs **editable from this repo** into a dedicated venv (`~/.local/share/verbal-code/venv`, created by `./install.sh`), so merged changes are live after restarting the app. Use that venv's interpreter for everything — pytest and ruff are installed there, not globally (the git-ignored `.venv/` in the repo is a stale leftover without the onnx-asr/sherpa engines):

```bash
VENV=~/.local/share/verbal-code/venv/bin
$VENV/python -m pytest -q                          # full suite (~1s, no audio hardware needed)
$VENV/python -m pytest tests/test_injector.py -q   # one file
$VENV/python -m pytest -k "clipboard" -q           # by keyword
$VENV/python -m ruff check .                       # lint (config in pyproject.toml)
$VENV/python scripts/benchmark_cpu.py --record     # on-device engine benchmark (see README)
```

Run the app: `verbal-code` (launcher) or `$VENV/python -m verbal_code`. Diagnostic flags: `--list-devices`, `--test-audio`, `--test-transcribe`, `--test-inject`, `-c <config>`. Model flags (used by `install.sh`): `--list-models`, `--set-model ENGINE MODEL`, `--download-model`. User config lives at `~/.config/verbal-code/config.yaml`; the repo's `config.yaml` is the commented template `install.sh` copies there.

## Architecture

`verbal_code/app.py` holds `VerbalCode`, the orchestrator that wires everything; the other modules are subsystems it composes:

- **`audio.py`** — `AudioCapture` buffers mic chunks (sounddevice callback → list); a read cursor lets the streaming consumer walk the same list that `stop()` concatenates for batch transcription, so audio is never stored twice. `trim_silence` is the energy-based VAD.
- **`transcriber.py`** — `TranscriberBase` with Parakeet (onnx-asr, INT8), sherpa-onnx (streaming transducers), Whisper (faster-whisper, batched), Moonshine, and Vosk backends. The key contract is `supports_live_streaming`: True only when `transcribe_stream` yields *final* text the engine will never revise (sherpa, Vosk). Parakeet/Whisper/Moonshine have no final-text streaming, so batch transcription on hotkey release is their only output path; `TestEngineContract` pins the flag per engine. Every engine implements `unload_model()`. `stt.cpu_threads` (default: physical cores via `physical_core_count()`) reaches Parakeet/sherpa/Whisper. Also owns the tray quick-switch model catalog (`AVAILABLE_MODELS`, first entry = engine default; `current_selection`, `apply_selection`). `sherpa_models.py` downloads only allow-listed sherpa models and verifies a pinned SHA-256 before extracting.
- **`injector.py`** — injection strategies (xdotool / ydotool for Wayland / clipboard-paste / Hybrid that pastes past a length threshold) plus `TextProcessor` (spoken punctuation commands, sentence capitalization carried across segments). **Injectors must raise `InjectionError` on failure, never log-and-return** — the app converts exceptions into the error tray state; a swallowed failure silently loses the user's dictation (MCC-39). The clipboard injector only save/restores plain-text clipboards and skips the restore whenever that could destroy data (MCC-43).
- **`hotkeys.py` / `hotkeys_evdev.py`** — two listener implementations behind one callback contract. `create_hotkey_listener` picks pynput on X11 and the evdev listener on Wayland (reads `/dev/input`; requires the user in the `input` group). `ComboState` in the evdev module is the pure, evdev-free state machine used for unit tests.
- **`tray.py`** — GTK AppIndicator. GTK runs on its own thread; every UI mutation must go through `GLib.idle_add` (see `set_state`/`set_model`). Tray menu callbacks arrive on the GTK thread — hand real work to another thread (model switches do).
- **`config_store.py`** — `update_config(path, mutate)` is the **only** way to write the user's config: ruamel.yaml round-trip (preserves the comments that document every option), atomic temp-file + `os.replace`, process-wide lock. Never `yaml.safe_dump` over the user's config (MCC-40). Reading still uses PyYAML (`load_config` in app.py).

### Concurrency model

Hotkey callbacks, the streaming loop, model switches, and the max-duration watchdog all run on separate threads. Two locks in `VerbalCode` keep them coherent: `_dictation_lock` guards the recording start/stop transitions, and `_model_switch_lock` serializes tray switches. A dictation is in progress while `_recording` (hotkey held) **or** `_processing` (released, still transcribing/injecting) is set. A model switch loads the new transcriber from a **copy** of the config and commits the swap (config + `self.transcriber` + `_live_injection`) atomically under `_dictation_lock`, cancelling — and unloading the new model — if a dictation is in progress (MCC-44). Only after a commit is the previous transcriber's `unload_model()` called, so it stays the fallback until then and is never unloaded under a running transcription (MCC-125). The streaming thread starts only when `_live_injection` is true — running it for revisable-partial engines is O(n²) CPU for nothing (MCC-42).

### Config validation is fail-fast

`validate_config` exits (via `sys.exit(1)`) on bad values: unknown `stt.engine`, bad `hotkey.mode`, numeric values outside `_NUMERIC_CONFIG_BOUNDS`, a missing package for the selected engine (`_STT_ENGINE_PACKAGES`), and unsupported sample rates (Whisper needs 16 kHz; Parakeet accepts `_PARAKEET_SAMPLE_RATES`). Add new numeric options to the bounds table rather than ad-hoc checks.

## Testing conventions

Tests construct a bare `VerbalCode` via `object.__new__(VerbalCode)` and assign fakes directly (see `_make_app` in `tests/test_app_dictation.py`, `test_model_switch.py`, `test_model_persistence.py`, and the `_make_*_app` helpers in `test_engine_swap.py`). **If you add an attribute that any dictation/switch code path reads, you must also add it to those helpers** or previously-green tests fail with AttributeError. Subprocess-driven injectors are tested by mocking `subprocess.run` with ordered `side_effect` lists — the call sequence is part of the assertion.

## Privacy rule

Transcribed text is whatever the user speaks — treat it like a password. Never log transcript content at INFO or by default; content logging is gated behind `logging.log_transcripts` (default off, MCC-38). Keep new logging to metadata (char counts, durations).

## Workflow

- Linear (team "McClish Products", project "Verbal-Code", issues `MCC-NN`) is the backlog's source of truth. One branch/PR per issue, branch name = Linear's suggested `gitBranchName`; after merge, delete the branch and comment the PR link on the issue. Linear's GitHub integration moves an issue to Done when its PR merges.
- **Before any commit, rebuild the install and uninstall scripts** — see the next section. Tests never exercise them, so they drift silently.
- Update `CHANGELOG.md` (Keep a Changelog, `[Unreleased]` section) with every user-visible change, referencing the MCC issue.
- Leave PRs for the user to merge unless they ask you to merge. For dependent issues, stack each branch on the previous one. To merge a squash-merged stack, record every branch tip first, then per PR `git rebase --onto origin/main <old-parent-tip> <branch>`, run the tests, force-push, retarget with `gh api -X PATCH "repos/{owner}/{repo}/pulls/N" -f base=main` (`gh pr edit --base` fails here on a Projects-classic GraphQL error), and `gh pr merge N --squash`.
- `specs/` are historical slice documents, not current requirements. `docs/sherpa-onnx-evaluation.md` is the MCC-21 evaluation that led to the sherpa engine (MCC-121).

## Install and uninstall scripts

Before committing, check `install.sh` and `uninstall.sh` against the change, update them, and rebuild the app from them:

- **`install.sh`** must install everything the code needs. Python deps go through `pip install -e "<repo>[extras]"` so the `pyproject.toml` pins apply — never `pip install <pkg>` by bare name. Its engine menu lists only the optional extras (`[project.optional-dependencies]`: moonshine, vosk); parakeet, sherpa and whisper are core dependencies. New system packages go in `APT_PACKAGES`. Its model menu (MCC-130) saves the choice with `--set-model` and fetches it with `--download-model`; option 4 lists `AVAILABLE_MODELS` automatically, but the three Parakeet entries and their sizes are hardcoded there.
- **`uninstall.sh`** must remove everything the installer or the app creates: launcher, desktop entry, icon, venv, `~/.config/verbal-code/` (except the user's dictionary — see below), `~/.cache/verbal-code/` (sherpa-onnx and vosk models, icons), and every Hugging Face repo an engine downloads (the `HF_MODELS` globs, one per org — faster-whisper's `_MODELS` table spans Systran, distil-whisper and mobiuslabsgmbh). A new engine, model source, cache path or installed file needs a matching entry; the missing distil globs left ~4 GB behind until MCC-127.
- **Verify:** `bash -n install.sh uninstall.sh`; test cleanup with `HOME=<scratch dir> ./uninstall.sh` against fake cache dirs. `--force` still kills a *real* running instance (its process match ignores `HOME`), so if the app is running, skip `--force` and pipe the answers instead: `printf 'n\ny\n'` (don't kill; continue) — when it isn't running, the first prompt is the confirmation; then rebuild the real venv by re-running `./install.sh` (two interactive menus: pipe in the extras choice that keeps the extras already installed, then an empty line so the model menu keeps the current model, e.g. `printf '4\n\n' | ./install.sh`) and confirm the suite passes.
- `uninstall.sh` keeps the user's dictionary (`dictionary.json`, or a custom `dictionary.path` it reads from `config.yaml` with the system `python3`) and deletes everything else in `~/.config/verbal-code/`; `--purge` removes the dictionary too (MCC-128). Never keep backups of user config in that directory.
