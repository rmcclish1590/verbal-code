# Phase 1: Recognition Upgrade - Context

**Gathered:** 2026-03-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Upgrade whisper.cpp from v1.7.3 to v1.8.3 with Vulkan iGPU acceleration, validate accuracy improvement over the current baseline, and wire initial_prompt support for Phase 2's vocabulary feature.

</domain>

<decisions>
## Implementation Decisions

### Model Selection
- Default model: small.en (upgrade from base.en) with q5_1 quantization
- Model size is configurable via config.json — user can select base.en, small.en, or medium.en
- English-only models (.en variants) for v1
- Download script grabs all three English model sizes (base.en, small.en, medium.en) upfront
- If configured model file doesn't exist at startup, fail with a clear error and download instructions — no silent fallback

### Quantization
- Use q5_1 quantized variants as default — ~40% smaller, ~30% faster, minimal accuracy loss
- Which quantization variants to download alongside q5_1 is Claude's discretion

### Thread Count
- Auto-detect thread count using std::thread::hardware_concurrency() instead of hardcoded 4
- Cap at a reasonable max to avoid oversubscription

### Claude's Discretion
- Vulkan acceleration strategy (require vs prefer with CPU fallback vs optional)
- Accuracy validation approach (test phrases, pass/fail criteria)
- Initial_prompt plumbing design (how to expose it for Phase 2)
- Download script implementation details (URLs, error handling)
- Whisper.cpp repo URL (verify ggerganov vs ggml-org for v1.8.3)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `WhisperRefinementService`: Current whisper integration — needs update for v1.8.3 API changes, initial_prompt, and Vulkan params
- `ModelManager` (`src/recognition/model_manager.hpp`): Manages model paths — needs extension for model size selection
- `Config` (`src/core/config.hpp`): JSON-backed config — add whisper model name setting
- `TranscriptionOrchestrator`: Coordinates Vosk + Whisper pipeline — no changes expected

### Established Patterns
- FetchContent for whisper.cpp in `cmake/Dependencies.cmake` — update GIT_TAG and possibly GIT_REPOSITORY URL
- `whisper_context_default_params()` used with no GPU flags — needs Vulkan params added
- `whisper_full_default_params(WHISPER_SAMPLING_GREEDY)` with no `initial_prompt` — needs wiring
- Conditional compilation via `VERBAL_ENABLE_WHISPER` / `#ifdef VERBAL_ENABLE_WHISPER`

### Integration Points
- `cmake/Dependencies.cmake` line 31-42: whisper.cpp FetchContent declaration
- `src/recognition/whisper_refinement_service.cpp`: Main integration point for API changes
- `scripts/download_models.sh`: Model download script — needs new model URLs
- `config/default_config.json`: Default config template — add model name field

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 01-recognition-upgrade*
*Context gathered: 2026-03-07*
