# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**verbal-code** — A desktop application that captures audio input and translates it into written text, injecting the result into any active text box on the computer. Think system-wide voice-to-text.

## Development Conventions

- **Language:** C++17 (minimum). Prefer C++20 features where supported.
- **Build system:** CMake (3.22+). Out-of-source builds in `build/`.
- **Compiler:** g++ 11+ (or clang++ 14+).
- **Style:** snake_case for variables/functions, PascalCase for classes/structs, UPPER_SNAKE_CASE for constants. Header files use `.hpp`, source files use `.cpp`.
- **Architecture:** Object-oriented with a microservices-inspired modular design. Each major concern (audio capture, speech recognition, text injection, IPC) is an isolated service with a well-defined interface.
- **Testing:** GoogleTest (gtest) for unit tests. Every service/module must have corresponding tests.
- **Optimization focus:** Develop for efficiency — prefer zero-copy, move semantics, and avoid unnecessary allocations in hot paths.

## Build Commands

```bash
# Configure (from repo root)
cmake -B build -DCMAKE_BUILD_TYPE=Release

# Build
cmake --build build -j$(nproc)

# Build debug
cmake -B build -DCMAKE_BUILD_TYPE=Debug && cmake --build build -j$(nproc)

# Run all tests
cd build && ctest --output-on-failure

# Run a single test binary
./build/tests/<test_binary_name>

# Run a specific test case within a binary
./build/tests/<test_binary_name> --gtest_filter="TestSuite.TestName"
```

## Architecture

The project follows a modular service architecture. Services communicate through defined interfaces (abstract base classes) and can be composed via dependency injection.

Planned top-level module layout:

```
src/
  core/           # Shared types, utilities, error handling
  audio/          # Audio capture service (microphone input, stream management)
  recognition/    # Speech-to-text engine integration
  injection/      # Text injection into active OS text fields
  ipc/            # Inter-process/inter-service communication
  app/            # Application entry point, service orchestration
tests/
  audio/
  recognition/
  injection/
  ipc/
  core/
```

Each `src/<module>/` directory contains:
- A public interface header (e.g., `i_audio_service.hpp`)
- Implementation files
- Internal headers not exposed to other modules

## Key Design Decisions

- Services are defined by abstract interfaces (`I`-prefixed, e.g., `IAudioService`) to allow mocking in tests and swapping implementations.
- Prefer `std::unique_ptr` for ownership, raw pointers/references for non-owning access.
- Use RAII for all resource management (audio streams, OS handles, etc.).
- Errors in service boundaries use `std::expected` (C++23) or a Result type; exceptions are reserved for truly exceptional/unrecoverable situations.
- Audio processing uses a lock-free ring buffer for the capture-to-recognition pipeline.
