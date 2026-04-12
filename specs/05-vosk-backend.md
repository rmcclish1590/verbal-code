# Slice 5: Vosk Lightweight STT Backend

## Goal
Add `VoskTranscriber` as an alternative STT backend in `transcriber.py`. Vosk is lightweight (~40MB model), runs on CPU, and has native streaming support. Users can switch between Whisper and Vosk via config.

## Depends On
- Slice 2 (transcriber base class and factory)
- Slice 4 (push-to-talk MVP working)

## Acceptance Criteria
- [ ] `VoskTranscriber` class implementing `TranscriberBase`
- [ ] `load_model()` downloads model to `~/.cache/verbal-code/models/` if not present, or loads from disk
- [ ] `transcribe_batch(audio)` feeds PCM chunks to a fresh `KaldiRecognizer`, returns joined text
- [ ] `transcribe_stream(chunk)` feeds each chunk to a persistent recognizer, yields text on `AcceptWaveform()` == True (final results only, not partials)
- [ ] `reset()` creates a fresh `KaldiRecognizer` instance
- [ ] Audio conversion: float32 [-1,1] → int16 PCM bytes (`(audio * 32767).astype(np.int16).tobytes()`)
- [ ] `create_transcriber()` factory handles `engine: "vosk"` config
- [ ] Config: `stt.vosk.model_name` (default: `"vosk-model-small-en-us-0.15"`)
- [ ] `--test-transcribe` works with both engines based on config

## Files to Modify
- MODIFY: `verbal_code/transcriber.py` — add `VoskTranscriber`, update factory
- MODIFY: `requirements.txt` — add `vosk>=0.3.45` (commented, optional)
- MODIFY: `pyproject.toml` — add `[project.optional-dependencies] vosk = ["vosk>=0.3.45"]`

## Technical Notes
- `vosk.Model(model_name="vosk-model-small-en-us-0.15")` auto-downloads from the Vosk model repo
- `vosk.SetLogLevel(-1)` to suppress noisy debug output
- `KaldiRecognizer(model, sample_rate)` — call `.SetWords(True)` for word-level output
- `.AcceptWaveform(bytes)` returns True when a final result is ready
- `.Result()` and `.FinalResult()` return JSON strings — parse with `json.loads()`
- Vosk models are not as accurate as Whisper but transcribe with essentially zero latency

## Test It
```bash
pip install vosk
# Edit config.yaml: stt.engine: "vosk"
python -m verbal_code --test-transcribe
# Speak for 5 seconds — should see transcribed text
# Then test full push-to-talk:
python -m verbal_code
```
