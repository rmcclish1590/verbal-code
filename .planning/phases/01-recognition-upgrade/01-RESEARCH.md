# Phase 1: Recognition Upgrade - Research

**Researched:** 2026-03-07
**Domain:** whisper.cpp upgrade (v1.7.3 -> v1.8.3), Vulkan GPU acceleration, initial_prompt support
**Confidence:** HIGH

## Summary

This phase upgrades whisper.cpp from v1.7.3 to v1.8.3, enables Vulkan iGPU acceleration, switches the default model from base.en to small.en with q5_1 quantization, and wires the `initial_prompt` parameter for Phase 2's vocabulary feature.

The repository has moved from `ggerganov/whisper.cpp` to `ggml-org/whisper.cpp`. The v1.8.x series introduced flash attention enabled by default. The `whisper_context_params` struct is structurally identical between v1.7.3 and v1.8.3 -- the `use_gpu` bool controls GPU backend selection (including Vulkan when built with `-DGGML_VULKAN=ON`). The `initial_prompt` field already exists in `whisper_full_params` and just needs to be wired through the existing `WhisperRefinementService`.

**Primary recommendation:** Update FetchContent URL and tag, set `GGML_VULKAN=ON` in CMake, wire `initial_prompt` via the `whisper_full_params` struct, update download script for new model variants, and add thread auto-detection.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- Default model: small.en (upgrade from base.en) with q5_1 quantization
- Model size is configurable via config.json -- user can select base.en, small.en, or medium.en
- English-only models (.en variants) for v1
- Download script grabs all three English model sizes (base.en, small.en, medium.en) upfront
- If configured model file doesn't exist at startup, fail with a clear error and download instructions -- no silent fallback
- Use q5_1 quantized variants as default -- ~40% smaller, ~30% faster, minimal accuracy loss
- Auto-detect thread count using std::thread::hardware_concurrency() instead of hardcoded 4
- Cap at a reasonable max to avoid oversubscription

### Claude's Discretion
- Vulkan acceleration strategy (require vs prefer with CPU fallback vs optional)
- Accuracy validation approach (test phrases, pass/fail criteria)
- Initial_prompt plumbing design (how to expose it for Phase 2)
- Download script implementation details (URLs, error handling)
- Whisper.cpp repo URL (verify ggerganov vs ggml-org for v1.8.3)
- Which quantization variants to download alongside q5_1

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| RECG-01 | Upgrade whisper.cpp to v1.8.3 with Vulkan iGPU acceleration and initial_prompt support | FetchContent URL/tag change, GGML_VULKAN cmake option, whisper_full_params.initial_prompt field, whisper_context_params.use_gpu field |
| RECG-02 | Validate recognition accuracy improvement with upgraded model | Model size upgrade (base.en -> small.en q5_1), accuracy test approach documented below |

</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| whisper.cpp | v1.8.3 | Speech-to-text inference | Locked decision; latest stable with Vulkan support |
| ggml (bundled) | (whisper.cpp internal) | Tensor computation, Vulkan backend | Bundled as `ggml/` subdirectory inside whisper.cpp |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| Vulkan SDK | 1.3.280+ | GPU acceleration | Already installed on target system; enables iGPU inference |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Vulkan | CUDA | NVIDIA-only; user has Intel/AMD iGPU, Vulkan is cross-vendor |
| q5_1 quantization | q8_0 | q8_0 is higher quality but larger (264MB vs 190MB for small.en) |
| small.en | medium.en | medium.en is more accurate but 539MB (q5_0) and slower |

## Architecture Patterns

### Changes to Existing Code

The upgrade is primarily a configuration change with minimal code modifications:

```
cmake/Dependencies.cmake     # URL + tag change, GGML_VULKAN option
src/recognition/
  whisper_refinement_service.hpp  # Add initial_prompt setter, thread config
  whisper_refinement_service.cpp  # Wire initial_prompt, use_gpu, thread count
  model_manager.hpp/cpp           # Support q5_1 filename pattern
config/default_config.json        # Update default model name
scripts/download_models.sh        # Multiple models, q5_1 variants
```

### Pattern 1: Vulkan GPU with CPU Fallback (Recommended)

**What:** Build with `-DGGML_VULKAN=ON` and set `cparams.use_gpu = true`. If Vulkan is unavailable at runtime, whisper.cpp's ggml backend system falls back to CPU automatically.
**When to use:** Always -- this is the safest strategy.
**Example:**
```cpp
// whisper_refinement_service.cpp init()
struct whisper_context_params cparams = whisper_context_default_params();
cparams.use_gpu = true;    // Prefer GPU; falls back to CPU if unavailable
cparams.flash_attn = true; // Default in v1.8.x, explicit for clarity
ctx_ = whisper_init_from_file_with_params(model_path_.c_str(), cparams);
```

**Recommendation on Vulkan strategy:** Use "prefer with CPU fallback" -- set `use_gpu = true` in context params. The ggml backend system handles fallback transparently. No need to check Vulkan availability in application code. Log which backend was selected after init.

### Pattern 2: Initial Prompt Plumbing

**What:** Add a method to set `initial_prompt` on the refinement service, wire it through to `whisper_full_params.initial_prompt`.
**When to use:** Phase 2 will call this with vocabulary hints.
**Example:**
```cpp
// In WhisperRefinementService
void set_initial_prompt(const std::string& prompt) {
    initial_prompt_ = prompt;
}

// In refine():
struct whisper_full_params wparams = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
wparams.initial_prompt = initial_prompt_.empty() ? nullptr : initial_prompt_.c_str();
```

**Note on `initial_prompt` behavior:** The prompt is only used for the first 30-second segment. For longer audio, `carry_initial_prompt` (a bool field in `whisper_full_params`) should be set to `true` to persist the prompt across segments. This is available in v1.8.3.

**Recommendation on initial_prompt plumbing:** Add `set_initial_prompt(const std::string&)` to `IRefinementService` interface (virtual method with empty default implementation so Vosk refinement is unaffected). Store as `std::string` member. Wire to `wparams.initial_prompt` in `refine()`. Also set `wparams.carry_initial_prompt = true` when prompt is non-empty.

### Pattern 3: Thread Count Auto-Detection

**What:** Replace hardcoded `WHISPER_THREAD_COUNT = 4` with auto-detection.
**Example:**
```cpp
#include <thread>
#include <algorithm>

int thread_count() {
    unsigned int hw = std::thread::hardware_concurrency();
    if (hw == 0) hw = 4; // fallback
    return static_cast<int>(std::min(hw, 8u)); // cap at 8
}
```

### Pattern 4: Model Path with Quantization Suffix

**What:** `ModelManager::whisper_model_path()` currently constructs `ggml-{model_name}.bin`. With q5_1 variants, filenames become `ggml-{model_name}-q5_1.bin`.
**Example:**
```cpp
// Current: model_name = "base.en" -> "ggml-base.en.bin"
// New:     model_name = "small.en-q5_1" -> "ggml-small.en-q5_1.bin"
// The model_name in config already encodes the quantization suffix.
// No code change needed in ModelManager -- just update config value.
```

**Recommendation:** Store the full model variant name in config (e.g., `"small.en-q5_1"`) so ModelManager constructs the right filename without special quantization logic.

### Anti-Patterns to Avoid
- **Hardcoding Vulkan requirement:** Never fail if Vulkan is absent. The `use_gpu = true` + ggml backend fallback handles this.
- **Hardcoding thread count:** Always use `hardware_concurrency()` with a cap.
- **Modifying TranscriptionOrchestrator:** This phase should NOT change the Vosk+Whisper pipeline orchestration -- only the Whisper service internals.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| GPU backend selection | Custom Vulkan initialization | `cparams.use_gpu = true` | ggml handles backend discovery, device selection, fallback |
| Model quantization | Custom quantization code | Pre-quantized models from HuggingFace | Models are pre-converted, just download the right file |
| Thread count detection | Platform-specific detection | `std::thread::hardware_concurrency()` | Standard C++11, cross-platform |

## Common Pitfalls

### Pitfall 1: Repository URL Change
**What goes wrong:** FetchContent fails because `ggerganov/whisper.cpp` redirects or is stale.
**Why it happens:** The repo moved to `ggml-org/whisper.cpp`.
**How to avoid:** Update GIT_REPOSITORY to `https://github.com/ggml-org/whisper.cpp.git`.
**Warning signs:** CMake clone/fetch errors during configure.

### Pitfall 2: Missing GGML_VULKAN Cache Variable
**What goes wrong:** Vulkan backend not compiled even though `-DGGML_VULKAN=ON` is set.
**Why it happens:** When whisper.cpp is a FetchContent dependency, cmake cache variables must be set BEFORE `FetchContent_MakeAvailable`.
**How to avoid:** Use `set(GGML_VULKAN ON CACHE INTERNAL "")` before `FetchContent_MakeAvailable(whisper)`.
**Warning signs:** No Vulkan-related compilation output during build; `use_gpu = true` silently falls back to CPU.

### Pitfall 3: Flash Attention Default Change
**What goes wrong:** Unexpected behavior differences between v1.7.3 and v1.8.x.
**Why it happens:** Flash attention is enabled by default in v1.8.x (was off in v1.7.x).
**How to avoid:** Explicitly set `cparams.flash_attn = true` for clarity. If issues arise, can be set to `false` for debugging.

### Pitfall 4: Model Filename Pattern for Quantized Models
**What goes wrong:** Model file not found at startup.
**Why it happens:** Quantized models have suffix like `-q5_1` in filename but existing code expects `ggml-{name}.bin`.
**How to avoid:** Store full variant name in config (e.g., `"small.en-q5_1"`) so the path resolves correctly.

### Pitfall 5: medium.en Has No q5_1 Variant
**What goes wrong:** Download script tries to fetch `ggml-medium.en-q5_1.bin` which does not exist.
**Why it happens:** HuggingFace repo only has q5_0 for medium.en, not q5_1.
**How to avoid:** Download q5_0 for medium.en, q5_1 for base.en and small.en. Document this asymmetry.

### Pitfall 6: initial_prompt Lifetime
**What goes wrong:** Dangling pointer crash if `initial_prompt_` string is modified while whisper is running.
**Why it happens:** `wparams.initial_prompt` is a `const char*` pointing to the `std::string`'s buffer.
**How to avoid:** Store `initial_prompt_` as a stable member variable. Set it before calling `refine()`, never during.

## Code Examples

### FetchContent Update
```cmake
# cmake/Dependencies.cmake - whisper.cpp section
if(ENABLE_WHISPER)
    FetchContent_Declare(
        whisper
        GIT_REPOSITORY https://github.com/ggml-org/whisper.cpp.git
        GIT_TAG        v1.8.3
        GIT_SHALLOW    TRUE
    )
    set(WHISPER_BUILD_TESTS OFF CACHE INTERNAL "")
    set(WHISPER_BUILD_EXAMPLES OFF CACHE INTERNAL "")
    set(BUILD_SHARED_LIBS OFF CACHE INTERNAL "")
    set(GGML_VULKAN ON CACHE INTERNAL "")  # Enable Vulkan backend
    FetchContent_MakeAvailable(whisper)
endif()
```

### Updated WhisperRefinementService Constructor/Init
```cpp
WhisperRefinementService::WhisperRefinementService(const std::string& model_path)
    : model_path_(model_path)
{
}

Result<void> WhisperRefinementService::init() {
#ifdef VERBAL_ENABLE_WHISPER
    if (ctx_) return Result<void>::ok();

    struct whisper_context_params cparams = whisper_context_default_params();
    cparams.use_gpu = true;
    cparams.flash_attn = true;
    ctx_ = whisper_init_from_file_with_params(model_path_.c_str(), cparams);
    if (!ctx_) {
        return Result<void>::err("Failed to load Whisper model from: " + model_path_);
    }

    LOG_INFO(TAG, "Whisper model loaded: " + model_path_);
    return Result<void>::ok();
#else
    return Result<void>::err("Whisper support not compiled in");
#endif
}
```

### Updated refine() with initial_prompt and thread auto-detection
```cpp
Result<std::string> WhisperRefinementService::refine(
    const std::vector<AudioSample>& audio, int sample_rate)
{
#ifdef VERBAL_ENABLE_WHISPER
    if (!ctx_) return Result<std::string>::err("Whisper not initialized");
    if (audio.empty()) return Result<std::string>::ok("");

    std::vector<float> float_audio(audio.size());
    for (size_t i = 0; i < audio.size(); ++i) {
        float_audio[i] = static_cast<float>(audio[i]) / PCM_INT16_SCALE;
    }
    (void)sample_rate;

    struct whisper_full_params wparams = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    wparams.print_realtime = false;
    wparams.print_progress = false;
    wparams.print_timestamps = false;
    wparams.single_segment = true;
    wparams.no_context = true;
    wparams.language = "en";

    // Auto-detect thread count, cap at 8
    unsigned int hw_threads = std::thread::hardware_concurrency();
    wparams.n_threads = static_cast<int>(std::min(hw_threads > 0 ? hw_threads : 4u, 8u));

    // Wire initial_prompt for vocabulary hints (Phase 2)
    if (!initial_prompt_.empty()) {
        wparams.initial_prompt = initial_prompt_.c_str();
        wparams.carry_initial_prompt = true;
    }

    int ret = whisper_full(ctx_, wparams, float_audio.data(), static_cast<int>(float_audio.size()));
    // ... rest unchanged
#endif
}
```

### Download Script Model URLs
```bash
# HuggingFace base URL
HF_BASE="https://huggingface.co/ggerganov/whisper.cpp/resolve/main"

# Models to download (name -> filename)
declare -A WHISPER_MODELS=(
    ["base.en-q5_1"]="ggml-base.en-q5_1.bin"
    ["small.en-q5_1"]="ggml-small.en-q5_1.bin"
    ["medium.en-q5_0"]="ggml-medium.en-q5_0.bin"  # No q5_1 for medium
)
```

### Config Update
```json
{
    "recognition": {
        "vosk_model": "vosk-model-small-en-us-0.15",
        "whisper_model": "small.en-q5_1",
        "enable_whisper_refinement": true
    }
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `ggerganov/whisper.cpp` repo | `ggml-org/whisper.cpp` repo | ~2024 (PR #3005) | Must update FetchContent URL |
| flash_attn disabled by default | flash_attn enabled by default | v1.8.0 | Minor perf improvement, set explicitly |
| Manual GPU backend init | ggml automatic backend discovery | v1.8.x | Just set `use_gpu = true`, ggml handles rest |
| base.en (148MB) | small.en-q5_1 (190MB) | This phase | Better accuracy, similar speed with GPU |

## Open Questions

1. **Vulkan performance on user's specific iGPU**
   - What we know: Vulkan gives ~10x speedup on supported hardware
   - What's unclear: Exact speedup on user's specific Intel/AMD iGPU
   - Recommendation: Build with Vulkan, benchmark before/after, log backend selection

2. **Thread cap value**
   - What we know: Oversubscription hurts performance
   - What's unclear: Optimal cap for different hardware
   - Recommendation: Cap at 8 initially, make configurable later if needed

3. **Accuracy validation methodology**
   - What we know: small.en should be more accurate than base.en
   - What's unclear: How to objectively measure improvement
   - Recommendation: Use a set of test phrases, compare Vosk-only vs Vosk+Whisper(old) vs Vosk+Whisper(new). Manual validation is acceptable for this phase -- run the app, speak test phrases, observe output quality. No need for automated accuracy scoring.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | GoogleTest v1.14.0 (via FetchContent) |
| Config file | CMakeLists.txt + tests/CMakeLists.txt |
| Quick run command | `cd build && ctest --output-on-failure -R recognition` |
| Full suite command | `cd build && ctest --output-on-failure` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| RECG-01 | Whisper v1.8.3 loads model with GPU params | unit | `./build/tests/test_whisper_refinement --gtest_filter="*Init*"` | No - Wave 0 |
| RECG-01 | initial_prompt is wired to whisper_full_params | unit | `./build/tests/test_whisper_refinement --gtest_filter="*InitialPrompt*"` | No - Wave 0 |
| RECG-01 | Thread count auto-detected and capped | unit | `./build/tests/test_whisper_refinement --gtest_filter="*ThreadCount*"` | No - Wave 0 |
| RECG-01 | FetchContent builds with Vulkan enabled | smoke | `cmake -B build -DGGML_VULKAN=ON && cmake --build build -j$(nproc)` | N/A (build test) |
| RECG-02 | Upgraded model produces transcription output | manual-only | Speak test phrases, compare output | N/A (requires audio hardware) |
| RECG-02 | Model download script fetches all variants | smoke | `bash scripts/download_models.sh` | Exists (needs update) |

### Sampling Rate
- **Per task commit:** `cd build && ctest --output-on-failure -R recognition`
- **Per wave merge:** `cd build && ctest --output-on-failure`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/recognition/test_whisper_refinement.cpp` -- covers RECG-01 (unit tests for init params, initial_prompt, thread count)
- [ ] Mock or stub for whisper context to test parameter wiring without actual model file

*(Note: Full accuracy testing (RECG-02) requires audio hardware and is manual-only. Unit tests verify parameter wiring, not transcription quality.)*

## Sources

### Primary (HIGH confidence)
- [whisper.cpp v1.8.3 whisper.h](https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.8.3/include/whisper.h) - struct definitions for whisper_context_params and whisper_full_params
- [whisper.cpp v1.7.3 whisper.h](https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.7.3/include/whisper.h) - compared struct definitions, confirmed API compatibility
- [whisper.cpp v1.8.3 CMakeLists.txt](https://raw.githubusercontent.com/ggml-org/whisper.cpp/v1.8.3/CMakeLists.txt) - confirmed ggml subdirectory integration, GGML_VULKAN passthrough
- [HuggingFace model repo](https://huggingface.co/ggerganov/whisper.cpp/tree/main) - exact model filenames and sizes
- Existing codebase - current whisper integration code reviewed

### Secondary (MEDIUM confidence)
- [whisper.cpp GitHub releases](https://github.com/ggml-org/whisper.cpp/releases) - v1.8.3 changelog
- [whisper.cpp README / build docs](https://github.com/ggml-org/whisper.cpp) - GGML_VULKAN build instructions
- [PR #2302](https://github.com/ggml-org/whisper.cpp/pull/2302) - Vulkan backend integration
- [Issue #637](https://github.com/ggml-org/whisper.cpp/issues/637) - initial_prompt implementation details

### Tertiary (LOW confidence)
- Vulkan ~10x speedup claim - reported in community discussions, hardware-dependent

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - verified whisper.h headers for both versions, confirmed API compatibility
- Architecture: HIGH - reviewed existing codebase, changes are minimal and well-understood
- Pitfalls: HIGH - verified repo URL change, medium.en q5_1 absence, flash_attn default change
- Validation: MEDIUM - accuracy testing is inherently subjective/manual

**Research date:** 2026-03-07
**Valid until:** 2026-04-07 (whisper.cpp releases are monthly-ish)
