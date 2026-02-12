include(GoogleTest)

# Helper function to add a test
function(verbal_add_test TEST_NAME TEST_SOURCE LINK_LIBS)
    add_executable(${TEST_NAME} ${TEST_SOURCE})
    target_link_libraries(${TEST_NAME} PRIVATE ${LINK_LIBS} GTest::gtest_main GTest::gmock)
    gtest_discover_tests(${TEST_NAME})
endfunction()

# Core tests (always built)
add_subdirectory(core)

# Module tests (conditional on dependencies)
add_subdirectory(audio)
add_subdirectory(recognition)
add_subdirectory(hotkey)
add_subdirectory(injection)
add_subdirectory(overlay)
add_subdirectory(app)
