---
phase: 1
slug: recognition-upgrade
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-07
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | GoogleTest v1.14.0 (via FetchContent) |
| **Config file** | CMakeLists.txt + tests/CMakeLists.txt |
| **Quick run command** | `cd build && ctest --output-on-failure -R recognition` |
| **Full suite command** | `cd build && ctest --output-on-failure` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd build && ctest --output-on-failure -R recognition`
- **After every plan wave:** Run `cd build && ctest --output-on-failure`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 01-01-01 | 01 | 1 | RECG-01 | unit | `./build/tests/test_whisper_refinement --gtest_filter="*Init*"` | No - W0 | pending |
| 01-01-02 | 01 | 1 | RECG-01 | unit | `./build/tests/test_whisper_refinement --gtest_filter="*InitialPrompt*"` | No - W0 | pending |
| 01-01-03 | 01 | 1 | RECG-01 | unit | `./build/tests/test_whisper_refinement --gtest_filter="*ThreadCount*"` | No - W0 | pending |
| 01-01-04 | 01 | 1 | RECG-01 | smoke | `cmake -B build -DGGML_VULKAN=ON && cmake --build build -j$(nproc)` | N/A (build) | pending |
| 01-02-01 | 02 | 1 | RECG-02 | manual-only | Speak test phrases, compare output | N/A | pending |
| 01-02-02 | 02 | 1 | RECG-02 | smoke | `bash scripts/download_models.sh` | Exists (update) | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/recognition/test_whisper_refinement.cpp` — stubs for RECG-01 (init params, initial_prompt, thread count)
- [ ] Mock or stub for whisper context to test parameter wiring without actual model file

*Existing infrastructure (GoogleTest, CMake test setup) covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Upgraded model produces accurate transcription | RECG-02 | Requires audio hardware and human judgment | 1. Build with v1.8.3 2. Load small.en-q5_1 model 3. Speak test phrases 4. Compare output to v1.7.3 baseline |
| Vulkan acceleration active on iGPU | RECG-01 | Hardware-dependent, log output verification | 1. Build with GGML_VULKAN=ON 2. Run verbal-code 3. Check logs for Vulkan device detection |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
