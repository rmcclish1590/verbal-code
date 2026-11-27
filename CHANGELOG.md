# Changelog

All notable changes to Verbal Code are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).
Development history before this file existed is recorded as numbered slice
documents in `specs/`; the work backlog lives in Linear (issues are referenced
below as MCC-NN).

## [Unreleased]

### Added

- Uninstalling asks whether to keep your dictionary (MCC-200). In a
  terminal, `./uninstall.sh` shows the dictionary's path and entry count
  and asks keep or delete. Enter keeps it. A delete has to be confirmed by
  typing `delete`, and the confirmation says it can't be undone.
  `--keep-dictionary` and `--purge-dictionary` (`--purge` still works)
  answer up front. A scripted run needs `--force` and keeps the dictionary
  unless told otherwise. The summary always says what happened to the
  dictionary and where it is.
- `./install.sh` reports an existing dictionary (path, entry count,
  last-modified date) before changing anything, and leaves it as it is.
  An unreadable dictionary is reported and left alone, and the install
  still finishes (MCC-200).

- `verbal-code --doctor` reports whether GPU transcription can work and,
  if not, the failing check and how to fix it: detected AMD/NVIDIA GPUs
  with their gfx target or compute capability, VRAM used/total, the
  ROCm/CUDA runtime status, the installed CTranslate2 build, the visible
  GPU count, the relevant environment variables and the effective Whisper
  device. It needs no audio hardware or valid config, and exits 1 when an
  installed GPU backend isn't working. `verbal-code --gpu-detect` prints
  the same detection as one machine-readable line for the installer
  (MCC-194).
- GPU-accelerated Whisper on AMD Radeon GPUs. On a machine with a
  supported AMD GPU and the ROCm 7.2+ runtime, `./install.sh` now
  replaces PyPI's CUDA-only CTranslate2 with the ROCm build from the
  CTranslate2 release, pinned to one version and checked against SHA-256
  hashes stored in the repo. It then verifies a GPU is visible. If any
  step fails, the installer puts the PyPI build back and Whisper runs on
  CPU. NVIDIA machines keep the PyPI build and are checked for the CUDA
  12 libraries. Machines without a GPU install exactly as before. There is
  no new prompt; set `VERBAL_CODE_GPU_BACKEND=rocm|cuda|cpu` to override
  the detection. `verbal-code --doctor --fix` reruns the same step later,
  for example after a pip upgrade replaced the ROCm build (MCC-195).
- `./update.sh` keeps the GPU backend: when the deploy's pip run replaced
  the ROCm build of CTranslate2 (or the pin moved), it reinstalls the
  pinned wheel from the local cache before the health check. If that
  fails, the whole update rolls back, so an update never silently drops
  you to CPU. `--dry-run` shows the backend plan (keep / reinstall ROCm
  wheel / none). A GPU added since the install is offered in the
  summary, never switched to. `install.sh` and `update.sh` end with the
  doctor's one-line GPU verdict. `uninstall.sh` removes the wheel cache
  and the backend marker (MCC-196).
- Whisper picks its device and precision automatically. `stt.whisper.device:
  auto` uses the GPU when CTranslate2 can see one (`cuda` means the GPU on
  AMD/ROCm too). The new `compute_type: auto` default means float16 on GPU
  and int8 on CPU; an explicit value, such as an existing `int8`, is still
  used as given. The new `stt.whisper.device_index` picks a GPU. Any GPU
  problem falls back to CPU with one log line saying why: a failed load or
  warmup, a device index that isn't there, or a ROCm build replaced by a
  pip upgrade. A GPU failure in the middle of a dictation retries that
  dictation on CPU, so nothing is lost, and Whisper stays on CPU for the
  rest of the session. An explicit `device: cuda` that can't be honoured
  logs an error and shows one tray notification. When the GPU is usable,
  the tray's Model menu marks Whisper models "(GPU)", and the installer's
  model menu adds a "Whisper distil-small.en on your GPU" choice as option
  7. Options 1-6 are unchanged (MCC-197).
- Before loading Whisper on the GPU, Verbal Code checks free VRAM (AMD
  through sysfs, NVIDIA through `nvidia-smi`). If another app, typically
  Ollama, holds too much of it, Whisper starts on CPU with a warning that
  names the cause and the fix (`ollama stop <model>`, a shorter
  `OLLAMA_KEEP_ALIVE`). Unreadable VRAM never blocks the GPU. The new
  `stt.whisper.ct2_allocator` (or an exported `CT2_CUDA_ALLOCATOR`) sets
  CTranslate2's GPU allocator before CTranslate2 is first imported. On a
  ROCm install whose libraries load only from `/opt/rocm/lib`, the
  launcher puts that directory on `LD_LIBRARY_PATH`; nobody else's
  launcher changes (MCC-198).
- GPU detection now checks every library the ROCm build of CTranslate2
  loads, not only the HIP runtime: hipBLAS and hipRAND, and what those
  need in turn, such as rocRAND (which the `hiprand` package doesn't pull
  in) and rocBLAS. It finds all of them in one pass. Each problem is named
  with its fix. A missing library gives the apt package to install. A
  library that is installed but missing from the loader cache gives
  `sudo ldconfig`. Nothing is installed or run with `sudo` for you.
  `./install.sh` runs this check before it downloads anything, so a
  machine with missing libraries stays on CPU with one hint, instead of
  swapping the wheel in and rolling it back. `./update.sh` and
  `verbal-code --doctor --fix` check first too. `--doctor` lists each
  library with its status and package, then the fix commands. When
  `import ctranslate2` still fails on a missing library, the warning
  names the library and its package (MCC-201).
- README "GPU acceleration" section: supported AMD and NVIDIA hardware,
  requirements (including the hipBLAS, hipRAND and rocRAND packages ROCm's
  runtime package doesn't ship, and the `sudo ldconfig` step), how to verify it with `--doctor`, the config
  options, how to force the CPU, and fixes for the common problems:
  Ollama holding VRAM, a pip upgrade replacing the ROCm build, allocator
  and multi-GPU settings. The repo now runs CI (pytest, ruff, `bash -n`,
  shellcheck) on Python 3.10 and 3.12 (MCC-199).

### Security

- Transcribed text is no longer written to the logs by default — dictation
  can contain passwords or personal details, and logs persist in plaintext.
  Only character counts are logged now; set `logging.log_transcripts: true`
  to opt back in to full transcript logging. A configured log file is also
  restricted to owner-only permissions (0600) (MCC-38).

### Fixed

- A dictionary file that isn't valid JSON (or has the wrong shape) no
  longer stops Verbal Code from starting. It runs without the dictionary,
  logs a warning, and refuses to save over the file so nothing in it is
  lost (MCC-200).
- A non-interactive `./uninstall.sh` without `--force` used to exit at
  the first prompt with no explanation. It now says to use `--force`, and
  still changes nothing (MCC-200).
- Verbal Code failed to start on Python 3.10, the oldest supported
  version and Ubuntu 22.04's default: the dictionary module imported
  `datetime.UTC`, which only exists from Python 3.11. Found by the new CI
  (MCC-199).

- Fuzzy dictionary matching no longer swallows a neighbouring word. With a
  multi-word variant in the dictionary, "at liatrio" was close enough to
  the term "liatrio" to be replaced whole, dropping the "at". Fuzzy matches
  now compare only phrases with the same number of words (MCC-192).

- Model downloads from Hugging Face could crash with `TypeError: process() takes no keyword arguments` on systems with
  Linux Mint's `python3-brotli` 1.1, which the venv picks up from the system
  site-packages. Brotli 1.2 is now a pinned dependency (MCC-130).

- uninstall.sh now removes every Whisper model it can find in the Hugging
  Face cache. It used to match only `Systran/faster-whisper-*`, leaving the
  distil models (including the old default `distil-small.en`),
  `distil-large-v3.5` and `large-v3-turbo` behind — several GB (MCC-127).

- Switching models from the tray now unloads the previous model as soon as
  the new one is in place, instead of leaving its memory to the garbage
  collector; a failed or cancelled switch unloads whatever it had loaded.
  A switch that finishes loading while a dictation is still being
  transcribed is now cancelled too (previously only while recording),
  since the old model is unloaded once the switch commits (MCC-125).

- uninstall.sh now matches only the launcher's exact interpreter invocation
  (`verbal-code/venv/bin/python -m verbal_code`) when stopping running
  instances, instead of the broad `python.*verbal_code` pattern that could
  kill unrelated processes — an editor's language server, a pytest run, or
  any tool whose command line mentioned the repo (MCC-46).

- An unknown `stt.engine` value (e.g. a typo like "wisper") now fails
  startup with a clear error listing the valid engines, instead of silently
  falling back to the Whisper backend (MCC-45).

- A dictation started while a tray model switch was still loading no longer
  gets its transcriber swapped out mid-session: the swap now commits under
  the dictation lock and is cancelled (with a notification) if recording
  began during the load, and the in-memory config is only modified when the
  swap actually commits (MCC-44).

- The clipboard-paste injector no longer clobbers the clipboard: non-text
  content (images, file copies) and unreadable/empty clipboards skip the
  restore instead of being replaced with an empty string, and anything the
  user copies during the paste settle window wins over the restore
  (MCC-43).

- With `stt.streaming_enabled: true` and an engine whose partials are
  revisable (Whisper/Moonshine), the streaming thread no longer runs at
  all: it re-transcribed the entire session every 1.5s — O(n²) CPU over a
  dictation — only to produce debug-log lines, since the injected text
  always came from the batch pass on release anyway. Live streaming still
  works unchanged with the vosk engine (MCC-42).

- Recordings are now capped by `audio.max_seconds` (default 300, 0 to
  disable): a toggle-mode dictation left running no longer grows the
  in-memory audio buffer without bound (~3.8 MB/min). Hitting the cap stops
  the recording with a notification and transcribes what was captured
  (MCC-41).

- Switching models from the tray or saving a hotkey no longer destroys the
  comments in config.yaml: config rewrites now round-trip through
  ruamel.yaml (new dependency), are written atomically (temp file +
  rename, so a crash can't truncate the config), and are serialized behind
  a lock so concurrent saves can't lose each other's changes (MCC-40).

- A failed injection (xdotool/ydotool/xclip error or timeout) now raises and
  surfaces the error tray state and notification instead of silently
  reporting success while the dictated text was lost. The hybrid injector
  falls back to typing when a clipboard paste fails, and a paste-keystroke
  failure leaves the dictated text on the clipboard so it can be recovered
  with a manual paste (MCC-39).

### Added

- `./update.sh` upgrades an existing install in place, without an
  uninstall. It builds the current checkout (`--pull` fast-forwards it
  first), stops a running Verbal Code, and replaces only the application
  files: the venv's packages, the launcher, the desktop entry and the icon.
  It restarts the app afterwards, unless you pass `--no-restart`. Your
  config, saved hotkeys and model, dictionary, logs and downloaded models
  are never touched; the script checksums them and confirms they're
  unchanged. A failed build changes nothing. A failed or interrupted deploy
  rolls back to the previous version. The summary shows the old and new
  version and commit, and `--dry-run` shows what would change (MCC-193).
- `install.sh` now builds the package before it installs anything, so a
  broken build stops the install with a clear error. It also prints the
  version and commit it installed (MCC-193).

- Spoken email addresses and URLs are typed in written form: "ryan at
  example dot com" becomes `ryan@example.com`, and "github dot com slash
  anthropics" becomes `github.com/anthropics`. Say "begin address" …
  "finish address" to mark an address explicitly. Addresses in ordinary
  dictation are also recognised, but only when they end in a known TLD or
  start with a protocol, so prose such as "look at that" is left alone.
  Configure or disable this under the new `address` config section
  (MCC-189, MCC-190).

- Inside an address, names can be spelled letter by letter ("r y a n at
  example dot com") or with the phonetic alphabet ("romeo yankee alpha
  november"). Also supported: "b as in bravo", "capital r" for an
  uppercase letter in a URL path, and spoken digits ("k two f s a" →
  `k2fsa`). Parakeet's hyphenated spelling (`R-Y-N`) is recognised too
  (MCC-191).

- Dictionary entries can be marked as a domain or address term. Next to an
  address, these terms are tried first, also match with the spaces removed
  ("lia trio" → `liatrio`), and are typed lowercase. A variant such as "lee
  at treo" repairs a domain the model split up before address conversion
  sees the stray "at". A name you spell inside an address is added as a
  disabled 🔤 *spelled* candidate, so enabling it once saves spelling it
  again (`address.suggest_spelled_terms`) (MCC-192).

- install.sh now downloads the speech model during installation, so the
  first dictation doesn't wait on a ~660 MB download. Its model menu
  defaults to Parakeet TDT 0.6B v2 and offers Parakeet v3 (multilingual),
  the new Parakeet TDT-CTC 110M (English, ~140 MB, for slower CPUs), any
  other installed engine's model, or skipping the download; the choice is
  saved to the config. On a re-run the default keeps the current model, and
  a model already in the cache isn't downloaded again. A failed download
  only warns: the app fetches the model on first start. New
  `verbal-code --list-models`, `--set-model ENGINE MODEL` and
  `--download-model` do the same from the command line (MCC-130).

- README "Logging" section: enabling `logging.file`, the
  `dictation_latency_ms` log format, the tray's Logging... window, using the
  latency entries for tuning, and troubleshooting. The config template now
  explains `logging.file` (MCC-129).
- `scripts/benchmark_cpu.py`: compares every installed engine/model on the
  local CPU — cold load, latency on release, real-time factor, peak RSS per
  model, and WER against an optional reference — over recorded or supplied
  WAV clips. Engines that aren't installed or fail to load are reported and
  skipped (MCC-126).

- Two new speech engines, selectable via `stt.engine` and the tray's Model
  menu (MCC-119):
  - **parakeet** — NVIDIA Parakeet TDT 0.6B (v2 English, v3 multilingual)
    running INT8 on onnxruntime via onnx-asr. Batch on hotkey release with
    punctuation and capitalisation; recordings over 25s are split at the
    quietest point near each boundary rather than mid-word (MCC-120).
  - **sherpa** — sherpa-onnx streaming transducers (Kroko Zipformer,
    Nemotron 0.6B) for true live dictation with `stt.streaming_enabled:
    true`: each utterance is typed, punctuated and capitalised, as soon as
    a pause ends it. Models download on first use from the sherpa-onnx
    GitHub releases and are verified against a pinned SHA-256 before being
    unpacked into `~/.cache/verbal-code/sherpa-onnx/` (MCC-121).

- New tray "Logging..." window showing the hotkey-release-to-injection
  latency measurements (`dictation_latency_ms=`, MCC-30) recorded in the
  configured log file — a filtered, read-only view rather than the full
  application log, with a Refresh button. Shows a placeholder if
  `logging.file` isn't configured or no entries have been logged yet
  (MCC-58).

- New tray "Dictionary..." window for viewing and managing dictionary
  entries: search by term or variant, sortable columns, add/edit terms and
  their variants, toggle enabled/disabled, and delete (with confirmation).
  Auto-learned entries are marked with a ✨ indicator. There's no review
  queue for pending auto-learned candidates yet — that depends on MCC-56,
  which is deliberately deferred, so every entry shown here is already
  active. Renaming a term isn't supported; the term is the store's
  identity (MCC-57).

- Dictionary corrections are now applied to transcribed text before
  injection: known misheard variants are replaced with the canonical term
  exactly, and anything close enough (fuzzy-matched, configurable via
  `dictionary.fuzzy_threshold`) is corrected too, so every mishearing
  doesn't need to be anticipated as a variant up front. Runs for both batch
  and live-streaming injection paths, before punctuation commands and
  capitalization; disabled entries are skipped, and an empty dictionary is
  a no-op. New `dictionary:` config section (`enabled`, `fuzzy_threshold`,
  `path`) (MCC-55).

- New `verbal_code.dictionary` module: a persisted store of user-defined
  custom terms (names, jargon, acronyms) for correcting transcription
  output, backed by `~/.config/verbal-code/dictionary.json` with atomic
  writes. Supports add/update/delete/lookup; matching is case-insensitive
  and supports multi-word phrases, while the canonical term's casing is
  preserved on output. Data layer only — applying corrections during
  transcription and a management UI are tracked separately (MCC-54).

- Regression tests prove the selected transcription model survives a
  restart: the tray quick-switch's save round-trips through `load_config()`
  exactly like a fresh start would, unrelated config sections are preserved,
  and a missing config file is created on first switch. The persistence
  itself already worked (MCC-16); this closes the gap in coverage (MCC-33).

- Every completed dictation logs its hotkey-release→text-on-screen latency as
  `dictation_latency_ms=<value>` at INFO, for performance monitoring
  (MCC-30).

- Test coverage grew from 23 to 158 tests, now spanning transcriber stream
  gating and delta logic, Vosk streaming, silence trimming, audio-capture
  buffering, hotkey capture/dispatch, injector routing, config validation,
  and the app's dictation, model-switch, and live-streaming orchestration
  (MCC-25).

- Tray menu shows the active engine/model and offers a Model submenu for
  switching between installed engines' models on the fly; the choice loads in
  the background and persists to the config file (MCC-16).

- Spoken punctuation and formatting commands ("period", "comma", "question
  mark", "new line", "new paragraph", ...), with automatic capitalisation of
  sentence starts; disable with `injection.punctuation_commands: false`
  (MCC-15).

- Automatic clipboard paste for long dictations (`injection.clipboard_threshold`,
  default 100 characters): short fragments are still typed, long ones land
  instantly via the clipboard (MCC-14).

- Toggle-to-dictate mode (`hotkey.mode: "toggle"`): press the hotkey once to
  start recording and again to stop, alongside the default push-to-talk
  (MCC-13).

- Wayland support: on a Wayland session, global hotkeys are read via an evdev
  listener (requires membership in the `input` group) and injection prefers
  ydotool automatically (MCC-12).

- Live streaming injection with the Vosk engine: each utterance is typed into
  the focused window as it finalises, and hotkey release just flushes the last
  utterance — no duplicate batch pass (MCC-11).
- Modifier-only hotkey combos (e.g. Alt+Ctrl+Super): the hotkey dialog captures
  them on key release, and the listener accepts a modifier as the trigger key
  (MCC-26).
- Moonshine STT engine (`stt.engine: moonshine`) — fast English-only ASR on
  onnxruntime, no torch required.
- Energy-based silence trimming before batch transcription
  (`vad.trim_silence`, `vad.trim_threshold_db`); a silent recording now skips
  transcription entirely (MCC-7).
- Startup validation of numeric config values (sample rate, chunk size, beam
  size, batch size, injection delay, trim threshold) with errors that name the
  offending key (MCC-8).
- This changelog (MCC-17).

### Changed

- `uninstall.sh` and `update.sh` only stop the Verbal Code that belongs to
  the current `HOME`, so a scratch-`HOME` test run never stops the real
  instance (MCC-193).

- uninstall.sh now keeps your custom dictionary (`dictionary.json`, or the
  file named by `dictionary.path`) so a reinstall picks it up — curated terms
  take time to build. Everything else is still removed; the output says where
  the dictionary was kept. Pass `--purge` to delete the dictionary as well.
  install.sh reports when it finds an existing dictionary (MCC-128).

- install.sh's engine menu now offers only the optional extras (moonshine,
  vosk; default none), since parakeet, sherpa and whisper are always
  installed. Everything installs through the package and its extras, so the
  version pins in pyproject.toml apply (previously core and engine packages
  were installed unpinned). The installer also installs ruff and warns when
  a running instance needs a restart to pick up the update (MCC-127).

- The template config (copied by install.sh on a fresh install) now
  defaults to the parakeet engine, with the sherpa live-streaming preset
  documented alongside it. New optional `stt.cpu_threads` (1-256) sets
  inference threads for parakeet, sherpa, and whisper; unset means one per
  physical core. Existing configs are unchanged, and a config without
  `stt.engine` still uses whisper (MCC-123).

- Whisper now runs one CTranslate2 thread per physical CPU core (6 on a
  Ryzen 5 5600G) instead of CTranslate2's default of 4: about 11-13% lower
  latency across distil-small.en, distil-medium.en, and distil-large-v3.5 on
  that CPU. `distil-medium.en` and `distil-large-v3.5` were added to the
  tray's Whisper models (MCC-122).

- New core dependencies `onnx-asr[cpu,hub]` (NVIDIA Parakeet TDT models on
  onnxruntime, which faster-whisper already pulls in) and `sherpa-onnx`
  (true live-streaming transducers), groundwork for the Parakeet and
  sherpa engines. Both are hard dependencies rather than extras — together
  they add ~45 MB — so every install can offer the new engines in the tray.
  Moonshine stays on the optional `useful-moonshine-onnx` extra (MCC-118).

- Dependencies carry upper bounds (next major version) in requirements.txt
  and pyproject.toml so an incompatible release can't break an install
  (MCC-24).

- The tray prefers the maintained AyatanaAppIndicator3 library, falling back
  to the deprecated AppIndicator3 where Ayatana isn't available; install.sh
  installs whichever the distribution ships (MCC-23).

- Audio capture stores each chunk once: the streaming consumer walks the
  session buffer with a read cursor instead of a second queue (MCC-22).

- Default whisper `beam_size` lowered from 5 to 2 — roughly half the CPU
  latency with negligible accuracy loss on short dictations; set
  `stt.whisper.beam_size: 5` to restore the old behaviour (MCC-19).

- The default hotkey is `super+alt+space` everywhere; the code fallback
  previously disagreed with config.yaml and the README (MCC-5).
- `validate_config()` runs before the `--test-audio` / `--test-transcribe` /
  `--test-inject` diagnostic modes, so a missing STT package produces the
  friendly install hint instead of a traceback (MCC-6).
- `logging.file` is sanitized before use: `~` expands, symlinks and
  directories are refused, and an unusable path degrades to console-only
  logging instead of crashing (MCC-9).
- `--test-audio` writes its WAV through `tempfile.mkstemp` instead of a fixed
  `/tmp` path (MCC-10).
- Whisper batch transcription runs through faster-whisper's
  `BatchedInferencePipeline` with the built-in Silero VAD filter; the default
  model is `distil-small.en`.

### Fixed

- A malformed saved hotkey in config.yaml (wrong types, unknown modifier
  names) now falls back to the default combo with a warning instead of
  breaking startup; saved hotkeys are validated once and used consistently
  by the listener, ready banner, and hotkey editor (MCC-32).

- Streaming thread lifecycle: stop state is initialised (shutdown previously
  raised `AttributeError`), the per-session thread is joined on dictation stop
  instead of spinning forever, and queued audio is drained on stop so the tail
  of a dictation isn't lost (MCC-11).
- Streaming loop re-transcribed the entire buffer on every audio chunk,
  growing CPU cost quadratically with utterance length (P0).
- Streaming inference ran during recording even though its output was
  discarded (P0).
- Hotkeys combining Ctrl with a letter never activated on X11 (P0).
- Clipboard injection restored the clipboard before slow applications
  processed the paste (P0).
- `injection.delay_ms` is per keystroke, not a one-time delay; the shipped
  default is now 0 and the semantics are documented (P0).
- Non-16 kHz `audio.sample_rate` with the whisper engine silently produced
  garbled transcriptions; it is now rejected at startup (P0).
- `app.stop()` leaked the streaming thread (P1).

### Removed

- The torch/torchaudio dependency (~2 GB): voice-activity detection uses
  faster-whisper's bundled ONNX Silero VAD, and `install.sh` now uninstalls
  torch from existing venvs on upgrade (MCC-18).
- `BACKLOG.md` — the backlog moved to Linear.

## [0.1.0] - 2026-08-26

Initial development, built as vertical slices (specs 00–12 in `specs/`).

### Added

- Push-to-talk dictation for Linux Mint/X11: hold a global hotkey, speak,
  release, and the transcribed text is injected into the focused window
  (slices 00–04).
- Audio capture via sounddevice with per-session buffering (slice 01).
- Whisper transcription through faster-whisper (slice 02).
- Text injection via xdotool typing simulation with clipboard-paste fallback,
  plus a ydotool injector for future Wayland use (slice 03).
- Global hotkey listener built on pynput (slice 04).
- Vosk as a lightweight alternative STT engine (slice 05).
- Streaming transcription machinery (slice 06).
- System tray indicator with status states and notifications (slice 07).
- Silero voice-activity detection integration (slice 08).
- `install.sh` guided installer, launcher script, and `--list-devices` /
  `--test-audio` / `--test-transcribe` / `--test-inject` diagnostics
  (slice 09).
- `uninstall.sh` (slice 10).
- Application menu desktop entry and icon (slice 11).
- In-app hotkey editor dialog reachable from the tray menu (slice 12).
