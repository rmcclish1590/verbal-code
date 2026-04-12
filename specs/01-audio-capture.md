# Slice 1: Audio Capture Module

## Goal
Build `verbal_code/audio.py` — a module that captures microphone audio into a thread-safe queue and accumulates a session buffer. Prove it works by adding a `--test-audio` CLI flag that records 3 seconds of audio and saves it to a WAV file.

## Depends On
- Slice 0 (project scaffold, config loading)

## Acceptance Criteria
- [ ] `AudioCapture` class with `start()`, `stop()`, `get_chunk(timeout)`, `get_all_chunks()`
- [ ] `start()` opens a `sounddevice.InputStream` with configurable sample_rate (16000), channels (1), chunk_size (1024), device_index (None = default)
- [ ] Audio callback pushes float32 numpy arrays into a `queue.Queue`
- [ ] `stop()` returns the full session audio as a single concatenated `np.ndarray`
- [ ] Thread-safe: `start()`/`stop()` protected by a `threading.Lock`
- [ ] `list_devices()` static method returns `sounddevice.query_devices()` output
- [ ] `--list-devices` CLI flag prints device list and exits
- [ ] `--test-audio` CLI flag records 3 seconds, saves to `/tmp/verbal_code_test.wav`, prints duration and file path
- [ ] Config values read from `config.audio.*`

## Files to Create/Modify
- CREATE: `verbal_code/audio.py`
- MODIFY: `verbal_code/app.py` — add `--test-audio` flag, wire up AudioCapture
- MODIFY: `requirements.txt` — add `sounddevice>=0.4.6`

## Technical Notes
- `sounddevice.InputStream` with `callback=` is non-blocking and runs in its own thread
- Callback receives `(indata, frames, time_info, status)` — copy `indata[:, 0]` for mono
- For WAV saving in the test, use `scipy.io.wavfile.write` or `soundfile.write` (add as test-only dep) or raw `wave` stdlib module
- Float32 audio range is [-1.0, 1.0]

## Test It
```bash
pip install sounddevice
python -m verbal_code --list-devices   # shows audio devices
python -m verbal_code --test-audio     # records 3s, saves WAV
aplay /tmp/verbal_code_test.wav        # verify recording sounds right
```
