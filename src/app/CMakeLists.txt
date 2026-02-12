add_library(verbal_app
    application.cpp
    transcription_store.cpp
)

target_include_directories(verbal_app PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(verbal_app PUBLIC verbal_core verbal_recognition)

# Optional dependencies based on available system libs
if(TARGET verbal_audio)
    target_link_libraries(verbal_app PUBLIC verbal_audio)
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_AUDIO=1)
endif()

if(TARGET verbal_hotkey)
    target_link_libraries(verbal_app PUBLIC verbal_hotkey)
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_HOTKEY=1)
endif()

if(TARGET verbal_injection)
    target_link_libraries(verbal_app PUBLIC verbal_injection)
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_INJECTION=1)
endif()

if(TARGET verbal_overlay)
    target_link_libraries(verbal_app PUBLIC verbal_overlay)
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_OVERLAY=1)
endif()

# Main executable
add_executable(verbal-code main.cpp)
target_link_libraries(verbal-code PRIVATE verbal_app)
