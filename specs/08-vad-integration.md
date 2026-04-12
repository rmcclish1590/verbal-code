# Slice 8: Voice Activity Detection (Silero VAD)

## Goal
Add Silero VAD as a pre-filter on audio chunks to skip silence and reduce unnecessary transcription work. This improves responsiveness and reduces CPU usage — the transcriber only processes chunks that contain actual speech.

## Depends On
- Slice 4 (push-to-talk loop)
- Slice 6 (streaming transcription loop)

## Acceptance Criteria
- [ ] `verbal_code/vad.py` module with `VoiceActivityDetector` class
- [ ] `__init__(threshold, min_speech_ms, silence_ms, sample_rate)` loads Silero VAD model via `torch.hub`
- [ ] `is_speech(audio_chunk: np.ndarray) -> bool` returns True if speech probability > threshold
- [ ] `process_chunk(chunk) -> Optional[np.ndarray]` implements state machine:
  - Accumulates speech chunks when speech is detected
  - After `silence_ms` of non-speech, returns the accumulated speech audio
  - Returns None while still accumulating or during silence
- [ ] `reset()` clears internal buffers
- [ ] Integrated into `_streaming_loop()`: only pass chunks to transcriber when VAD says speech is present
- [ ] Integrated into `_on_dictation_stop()`: can optionally trim silence from start/end of full audio before batch transcription
- [ ] Graceful fallback: if torch/silero not available, skip VAD (pass all audio through)
- [ ] Config: `vad.enabled`, `vad.threshold` (0.5), `vad.min_speech_ms` (250), `vad.silence_ms` (500)

## Files to Create/Modify
- CREATE: `verbal_code/vad.py`
- MODIFY: `verbal_code/app.py` — integrate VAD into streaming loop and batch path
- MODIFY: `requirements.txt` — add `torch>=2.0` (or note as optional heavy dep)

## Technical Notes
- Silero VAD: `torch.hub.load('snakers4/silero-vad', 'silero_vad')` returns `(model, utils)`
- Model expects 16kHz audio, chunks of 512 samples (32ms) — may need to re-chunk
- `model(torch.from_numpy(chunk), sample_rate)` returns speech probability float
- Silero VAD is tiny (<1ms per 30ms chunk on CPU) — negligible overhead
- `torch` is a heavy dependency (~2GB). Consider making it optional and documenting that VAD requires it.
- Alternative: if user has faster-whisper already, its built-in `vad_filter=True` parameter uses Silero internally — so VAD on the streaming path is the main value-add

## Test It
```bash
pip install torch
python -m verbal_code
# Set logging.level: "DEBUG" in config
# Hold hotkey — should see VAD filtering in logs:
#   [vad] Speech detected (prob=0.92)
#   [vad] Silence detected (prob=0.03)
#   [vad] Speech segment: 2.3s
```
