# Slice 6: Real-Time Streaming Transcription

## Goal
Implement the streaming transcription loop so users get real-time feedback while speaking. While the hotkey is held, a background thread feeds audio chunks to the transcriber's `transcribe_stream()` method. The final injection still uses `transcribe_batch()` for accuracy.

## Depends On
- Slice 4 (push-to-talk MVP)
- Slice 2 or 5 (at least one transcriber with streaming implemented)

## Acceptance Criteria
- [ ] `WhisperTranscriber.transcribe_stream(chunk)` accumulates audio in `_stream_buffer`, re-transcribes every ~1.5s of buffered audio, yields delta text (new words since last transcription)
- [ ] Uses reduced `beam_size` (half of batch value) for faster streaming
- [ ] `VoskTranscriber.transcribe_stream(chunk)` feeds each chunk directly to the persistent recognizer, yields final results (not partials) to avoid duplicates
- [ ] `VerbalCode._streaming_loop()` runs in a daemon thread during dictation:
  - Pulls chunks from `AudioCapture.get_chunk(timeout=0.1)`
  - Passes to `transcriber.transcribe_stream(chunk)`
  - Logs partial results at DEBUG level
  - Streaming text is NOT injected by default (to avoid duplicates with final batch pass)
  - Has a commented-out code path for live injection that users can enable
- [ ] `_on_dictation_start()` spawns the streaming thread, `_on_dictation_stop()` signals it to stop via `threading.Event`
- [ ] Streaming thread joins within 2 seconds on stop
- [ ] Final batch transcription still happens after stop for the authoritative text

## Files to Modify
- MODIFY: `verbal_code/transcriber.py` — implement `transcribe_stream()` for both backends
- MODIFY: `verbal_code/app.py` — add `_streaming_loop()`, threading management

## Technical Notes
- Whisper isn't natively streaming — we fake it by accumulating audio and re-transcribing. The delta detection compares new full text with `_last_text` to find what's new.
- For Whisper streaming, enable `vad_filter=True` with `min_silence_duration_ms=300` for responsive segmentation
- Vosk IS natively streaming — each `AcceptWaveform()` call processes just that chunk
- The streaming thread must check `_stream_stop.is_set()` on each iteration
- `AudioCapture.get_chunk(timeout=0.1)` returns None on timeout — loop continues

## Test It
```bash
python -m verbal_code
# Hold hotkey, speak a long sentence
# Watch terminal for DEBUG-level streaming results:
#   [stream] Hello
#   [stream] world this
#   [stream] is a test
# Release — final accurate text gets injected
```

Set `logging.level: "DEBUG"` in config to see streaming output.
