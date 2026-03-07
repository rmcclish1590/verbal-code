# Testing Patterns

**Analysis Date:** 2026-03-07

## Test Framework

**Runner:**
- GoogleTest (gtest) via FetchContent in CMake
- GoogleMock (gmock) linked but not heavily used (hand-written mocks preferred)
- Config: `tests/CMakeLists.txt` defines `verbal_add_test()` helper function

**Assertion Library:**
- GoogleTest built-in: `EXPECT_EQ`, `EXPECT_TRUE`, `ASSERT_EQ`, `EXPECT_THROW`, `EXPECT_NEAR`, `EXPECT_DOUBLE_EQ`, `EXPECT_STREQ`

**Run Commands:**
```bash
cd build && ctest --output-on-failure    # Run all tests
./build/tests/<test_binary_name>         # Run a single test binary
./build/tests/<test_binary_name> --gtest_filter="TestSuite.TestName"  # Run specific test
```

## Test File Organization

**Location:**
- Separate `tests/` directory tree mirroring `src/` module structure
- Tests are NOT co-located with source

**Naming:**
- Test files: `test_<module_or_class>.cpp`
- Test binaries: same name as test file (without `.cpp`)

**Structure:**
```
tests/
  CMakeLists.txt              # Top-level test config, defines verbal_add_test()
  mocks/
    mock_services.hpp          # Hand-written mock implementations
  core/
    CMakeLists.txt
    test_ring_buffer.cpp       # Tests for src/core/ring_buffer.hpp
    test_result.cpp            # Tests for src/core/result.hpp
    test_config.cpp            # Tests for src/core/config.hpp
    test_session.cpp           # Tests for src/core/session.hpp
  audio/
    CMakeLists.txt
    test_audio_buffer.cpp      # Tests for src/audio/audio_buffer.hpp
  recognition/
    CMakeLists.txt
    test_transcription_orchestrator.cpp  # Tests for src/recognition/transcription_orchestrator.hpp
  hotkey/
    CMakeLists.txt
    test_evdev_hotkey_service.cpp    # Tests for src/hotkey/evdev_hotkey_service.hpp
    test_xcb_hotkey_service.cpp      # Tests for src/hotkey/xcb_hotkey_service.hpp
    test_portal_hotkey_service.cpp   # Tests for src/hotkey/portal_hotkey_service.hpp
  injection/
    CMakeLists.txt
    test_xdo_injection.cpp           # Tests for src/injection/xdo_injection_service.hpp
    test_wayland_injection.cpp       # Tests for src/injection/wayland_injection_service.hpp
  overlay/
    CMakeLists.txt
    test_gtk_overlay.cpp             # Tests for src/overlay/gtk_overlay_service.hpp
  app/
    CMakeLists.txt
    test_transcription_store.cpp     # Tests for src/app/transcription_store.hpp
```

## CMake Test Registration

**Helper Function (defined in `tests/CMakeLists.txt`):**
```cmake
function(verbal_add_test TEST_NAME TEST_SOURCE LINK_LIBS)
    add_executable(${TEST_NAME} ${TEST_SOURCE})
    target_link_libraries(${TEST_NAME} PRIVATE ${LINK_LIBS} GTest::gtest_main GTest::gmock)
    gtest_discover_tests(${TEST_NAME})
endfunction()
```

**Usage (e.g., `tests/core/CMakeLists.txt`):**
```cmake
verbal_add_test(test_ring_buffer test_ring_buffer.cpp verbal_core)
verbal_add_test(test_config test_config.cpp verbal_core)
```

**Conditional Tests (e.g., `tests/hotkey/CMakeLists.txt`):**
```cmake
if(TARGET verbal_hotkey)
    verbal_add_test(test_xcb_hotkey_service test_xcb_hotkey_service.cpp verbal_hotkey)
endif()
if(TARGET verbal_evdev_hotkey)
    verbal_add_test(test_evdev_hotkey_service test_evdev_hotkey_service.cpp verbal_evdev_hotkey)
endif()
```

**Mock Include Path:**
```cmake
target_include_directories(test_transcription_orchestrator PRIVATE ${CMAKE_SOURCE_DIR}/tests/mocks)
```

## Test Structure

**Simple Tests (no fixture):**
Use `TEST(SuiteName, TestName)` with PascalCase suite name matching the class under test:
```cpp
TEST(RingBuffer, BasicWriteRead) {
    RingBuffer<int> buf(16);
    int data[] = {1, 2, 3, 4, 5};
    EXPECT_EQ(buf.write(data, 5), 5u);
    // ...
}

TEST(Result, OkValue) {
    auto r = Result<int>::ok(42);
    EXPECT_TRUE(r.is_ok());
    EXPECT_EQ(r.value(), 42);
}
```

**Fixture Tests (shared setup/teardown):**
Use `TEST_F(FixtureName, TestName)` with `::testing::Test` base class:
```cpp
class TranscriptionStoreTest : public ::testing::Test {
protected:
    void SetUp() override {
        test_dir_ = fs::temp_directory_path() / "verbal_test_store";
        fs::create_directories(test_dir_);
        test_path_ = (test_dir_ / "transcriptions.json").string();
    }

    void TearDown() override {
        fs::remove_all(test_dir_);
    }

    fs::path test_dir_;
    std::string test_path_;
};
```

**Fixture with Mocks:**
```cpp
class OrchestratorTest : public ::testing::Test {
protected:
    void SetUp() override {
        recognition_ptr_ = std::make_unique<MockRecognitionService>();
        refinement_ptr_ = std::make_unique<MockRefinementService>();
        recognition_ = recognition_ptr_.get();
        refinement_ = refinement_ptr_.get();
        refinement_->init();
    }

    std::unique_ptr<MockRecognitionService> recognition_ptr_;
    std::unique_ptr<MockRefinementService> refinement_ptr_;
    MockRecognitionService* recognition_;
    MockRefinementService* refinement_;
};
```

## Mocking

**Framework:** Hand-written mocks (NOT gmock `MOCK_METHOD`). gmock is linked but only for `GTest::gtest_main`.

**Mock Location:** `tests/mocks/mock_services.hpp`

**Pattern -- Manual Mocks:**
Implement the interface with minimal logic and public state for test assertions:
```cpp
class MockRecognitionService : public IRecognitionService {
public:
    // IService
    Result<void> start() override { running_ = true; return Result<void>::ok(); }
    void stop() override { running_ = false; }
    bool is_running() const override { return running_; }

    // IRecognitionService
    void set_on_partial(TextCallback cb) override { on_partial_ = std::move(cb); }
    void feed_audio(const AudioSample*, size_t) override {}
    void reset() override { reset_called_ = true; }
    std::string final_result() override { return final_result_; }
    void start_streaming() override { streaming_ = true; }
    void stop_streaming() override { streaming_ = false; }

    // Test helpers -- simulate events
    void emit_partial(const std::string& text) {
        if (on_partial_) on_partial_(text);
    }
    void set_final_result(const std::string& text) { final_result_ = text; }

    // Public state for assertions
    bool reset_called_ = false;
    bool streaming_ = false;

private:
    bool running_ = false;
    std::string final_result_;
    TextCallback on_partial_;
};
```

**Key Mock Characteristics:**
- Public boolean flags for state verification: `reset_called_`, `streaming_`
- `emit_*()` helpers to trigger callbacks from tests
- `set_*()` helpers to configure mock return values
- `set_should_fail(bool)` to simulate failure paths

**What to Mock:**
- Service interfaces (`IRecognitionService`, `IRefinementService`) when testing orchestration logic
- Use mocks for anything that requires hardware (audio devices, display servers)

**What NOT to Mock:**
- Value types and data structures (`RingBuffer`, `AudioBuffer`, `Result`, `Config`)
- Pure logic functions (`edit_distance_ratio`, `build_paste_command`, `check_modifiers`)
- These are tested directly

## Testing Without Hardware

**Static Method Testing:**
Services expose pure-logic static methods that can be tested without starting the service:
```cpp
// tests/injection/test_wayland_injection.cpp
TEST(WaylandInjection, BuildPasteCommandNonTerminal) {
    std::string cmd = WaylandInjectionService::build_paste_command(false);
    EXPECT_EQ(cmd, "ydotool key 29:1 47:1 47:0 29:0");
}
```

**Event Processing Testing:**
Services expose event-processing methods for testing without device I/O:
```cpp
// tests/hotkey/test_evdev_hotkey_service.cpp
TEST(EvdevHotkeyService, ProcessKeyEventFiresCallbacks) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl", "super", "alt"});

    int press_count = 0;
    service.set_on_press([&]() { ++press_count; });

    service.process_key_event(LCTRL, 1);
    service.process_key_event(LSUPER, 1);
    service.process_key_event(LALT, 1);
    EXPECT_EQ(press_count, 1);
}
```

**State-Only Testing:**
For services requiring system resources (GTK, X11), test only state management:
```cpp
// tests/overlay/test_gtk_overlay.cpp
TEST(GtkOverlayService, InitialState) {
    GtkOverlayService service;
    EXPECT_FALSE(service.is_running());
    EXPECT_EQ(service.x(), -1);
    EXPECT_EQ(service.y(), -1);
}

TEST(GtkOverlayService, SetPosition) {
    GtkOverlayService service;
    service.set_position(100, 200);
    EXPECT_EQ(service.x(), 100);
    EXPECT_EQ(service.y(), 200);
}
```

## Fixtures and Factories

**Temporary File/Directory Pattern:**
Tests needing filesystem access use `std::filesystem::temp_directory_path()`:
```cpp
void SetUp() override {
    test_dir_ = fs::temp_directory_path() / "verbal_test_config";
    fs::create_directories(test_dir_);
    test_path_ = (test_dir_ / "config.json").string();
}

void TearDown() override {
    fs::remove_all(test_dir_);
}
```

**Inline Test Data:**
Small test data is constructed inline. No shared fixture files:
```cpp
int data[] = {1, 2, 3, 4, 5};
std::vector<AudioSample> one_second(16000, 0);
```

**Kernel Keycode Aliases (for readability):**
```cpp
constexpr uint16_t LCTRL  = KEY_LEFTCTRL;
constexpr uint16_t LSUPER = KEY_LEFTMETA;
constexpr uint16_t LALT   = KEY_LEFTALT;
```

## Coverage

**Requirements:** None enforced. No coverage tooling configured.

**To add coverage:**
```bash
cmake -B build -DCMAKE_BUILD_TYPE=Debug -DCMAKE_CXX_FLAGS="--coverage"
cmake --build build -j$(nproc)
cd build && ctest --output-on-failure
lcov --capture --directory . --output-file coverage.info
```

## Test Types

**Unit Tests:**
- All existing tests are unit tests
- Test individual classes and functions in isolation
- Mock external dependencies via hand-written mocks in `tests/mocks/`
- 13 test files, ~69 test cases total

**Concurrency Tests:**
- `RingBuffer::ConcurrentReadWrite` -- producer/consumer thread test with 100k items
- `AudioBuffer::ThreadSafety` -- concurrent append/read stress test
- Verify correctness and absence of crashes under concurrent access

**Integration Tests:**
- Not present. Services requiring hardware (PipeWire, X11, Wayland) are only tested at the unit level via state checks and static methods.

**E2E Tests:**
- Not present.

## Common Patterns

**Testing Error Paths:**
```cpp
TEST(Result, ValueOnErrorThrows) {
    auto r = Result<int>::err("bad");
    EXPECT_THROW(r.value(), std::runtime_error);
}

TEST(XdoInjectionService, InjectWithoutStart) {
    XdoInjectionService service;
    auto result = service.inject_text("test");
    EXPECT_TRUE(result.is_err());
}
```

**Testing Callbacks:**
```cpp
TEST_F(OrchestratorTest, PartialCallbackFires) {
    TranscriptionOrchestrator orch(recognition_, refinement_);

    std::string received;
    orch.set_on_partial([&](const std::string& text) { received = text; });

    orch.on_recording_start();
    recognition_->emit_partial("hello world");

    EXPECT_EQ(received, "hello world");
}
```

**Testing State Transitions:**
```cpp
TEST(EvdevHotkeyService, IsPressedReflectsState) {
    EvdevHotkeyService service;
    service.set_modifiers({"ctrl"});
    service.set_on_press([]() {});
    service.set_on_release([]() {});

    EXPECT_FALSE(service.is_pressed());
    service.process_key_event(LCTRL, 1);
    EXPECT_TRUE(service.is_pressed());
    service.process_key_event(LCTRL, 0);
    EXPECT_FALSE(service.is_pressed());
}
```

**Testing Boundary Conditions:**
```cpp
TEST(RingBuffer, WriteFullBuffer) {
    RingBuffer<int> buf(4);
    int data[] = {1, 2, 3, 4};
    EXPECT_EQ(buf.write(data, 4), 4u);
    EXPECT_EQ(buf.available_write(), 0u);
    int more[] = {5};
    EXPECT_EQ(buf.write(more, 1), 0u);
}

TEST(EvdevHotkeyService, EmptyModifiers) {
    EvdevHotkeyService service;
    service.set_modifiers({});
    verbal::ModifierState state{true, true, true, true};
    EXPECT_FALSE(service.check_modifiers(state));
}
```

**Testing Persistence (Save/Load Round-Trip):**
```cpp
TEST_F(ConfigTest, SaveAndLoad) {
    {
        verbal::Config config;
        config.load(test_path_);
        config.set_overlay_position(100, 200);
        EXPECT_TRUE(config.save(test_path_));
    }
    {
        verbal::Config config;
        EXPECT_TRUE(config.load(test_path_));
        EXPECT_EQ(config.overlay_x(), 100);
        EXPECT_EQ(config.overlay_y(), 200);
    }
}
```

**Testing Environment Variables:**
```cpp
TEST(SessionDetection, ReturnsWaylandWhenSet) {
    setenv("XDG_SESSION_TYPE", "wayland", 1);
    EXPECT_EQ(detect_session_type(), SessionType::WAYLAND);
}

TEST(SessionDetection, ReturnsUnknownWhenUnset) {
    unsetenv("XDG_SESSION_TYPE");
    EXPECT_EQ(detect_session_type(), SessionType::UNKNOWN);
}
```

## Adding New Tests

**For a new module `src/foo/bar_service.hpp`:**

1. Create `tests/foo/test_bar_service.cpp`
2. Create or update `tests/foo/CMakeLists.txt`:
```cmake
if(TARGET verbal_foo)
    verbal_add_test(test_bar_service test_bar_service.cpp verbal_foo)
endif()
```
3. If mocks are needed, add to `tests/mocks/mock_services.hpp` or create a new mock header
4. Add mock include path if needed:
```cmake
target_include_directories(test_bar_service PRIVATE ${CMAKE_SOURCE_DIR}/tests/mocks)
```

**For a new pure-logic function:**
- Use `TEST(ClassName, MethodBehavior)` without fixtures
- Test edge cases: empty input, max values, error conditions

**For a new service with hardware dependencies:**
- Expose pure-logic methods as `static` or `public` for direct testing
- Test initial state, callback registration, and state management without calling `start()`
- Create hand-written mock implementing the interface for integration with other components

---

*Testing analysis: 2026-03-07*
