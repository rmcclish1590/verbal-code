# Slice 2: Whisper Batch Transcription

## Goal
Build `verbal_code/transcriber.py` with a `WhisperTranscriber` class that takes a numpy audio array and returns transcribed text. Prove it works with a `--test-transcribe` CLI flag that records 5 seconds of audio then transcribes and prints the result.

## Depends On
- Slice 0 (config loading)
- Slice 1 (audio capture)

## Acceptance Criteria
- [ ] `TranscriberBase` ABC with `load_model()`, `transcribe_batch(audio) -> str`, `transcribe_stream(chunk) -> Generator[str]`, `reset()`
- [ ] `WhisperTranscriber(model_size, device, compute_type, language, beam_size)` implements `TranscriberBase`
- [ ] `load_model()` initializes `faster_whisper.WhisperModel` (downloads on first run)
- [ ] `transcribe_batch(audio: np.ndarray) -> str` runs full transcription with VAD filter enabled, returns joined segment text
- [ ] `transcribe_stream()` can be a stub/no-op for now (just `yield ""`)
- [ ] `create_transcriber(config) -> TranscriberBase` factory reads `config.stt.*`
- [ ] `--test-transcribe` records 5s, runs batch transcription, prints the text and timing info
- [ ] Config values: `stt.engine`, `stt.whisper.model`, `stt.whisper.device`, `stt.whisper.compute_type`, `stt.whisper.language`, `stt.whisper.beam_size`

## Files to Create/Modify
- CREATE: `verbal_code/transcriber.py`
- MODIFY: `verbal_code/app.py` — add `--test-transcribe` flag
- MODIFY: `requirements.txt` — add `faster-whisper>=1.0.0`

## Technical Notes
- `faster_whisper.WhisperModel(model_size, device="auto", compute_type="int8")` — "auto" picks CUDA if available, else CPU
- `model.transcribe(audio_array, language="en", beam_size=5, vad_filter=True)` returns `(segments_generator, info)`
- Iterate segments and join `.text` with spaces
- Model downloads to `~/.cache/huggingface/` by default — mention this in output
- Thread safety: wrap `model.transcribe()` in a `threading.Lock` since it's not thread-safe
- Log: model load time, audio duration, transcription time, detected language + probability

## Test It
```bash
pip install faster-whisper
python -m verbal_code --test-transcribe
# Speak for 5 seconds after the "Recording..." prompt
# Should print transcribed text and timing
```
