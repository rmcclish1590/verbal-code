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
    if(HOTKEY_DEPS_FOUND)
        target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_XCB_HOTKEY=1)
    endif()
endif()

if(TARGET verbal_evdev_hotkey)
    target_link_libraries(verbal_app PUBLIC verbal_evdev_hotkey)
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_EVDEV_HOTKEY=1)
endif()

if(TARGET verbal_portal_hotkey)
    # Link portal hotkey if it's a real target (not just an alias)
    get_target_property(_aliased verbal_portal_hotkey ALIASED_TARGET)
    if(NOT _aliased)
        target_link_libraries(verbal_app PUBLIC verbal_portal_hotkey)
    endif()
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_PORTAL_HOTKEY=1)
endif()

if(TARGET verbal_injection)
    target_link_libraries(verbal_app PUBLIC verbal_injection)
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_INJECTION=1)
    if(XDO_FOUND)
        target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_XDO_INJECTION=1)
    endif()
endif()

if(TARGET verbal_wayland_injection)
    # Link wayland injection if it's a real target (not just an alias)
    get_target_property(_wl_aliased verbal_wayland_injection ALIASED_TARGET)
    if(NOT _wl_aliased)
        target_link_libraries(verbal_app PUBLIC verbal_wayland_injection)
    endif()
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_WAYLAND_INJECTION=1)
endif()

if(TARGET verbal_overlay)
    target_link_libraries(verbal_app PUBLIC verbal_overlay)
    target_compile_definitions(verbal_app PUBLIC VERBAL_HAS_OVERLAY=1)
endif()

# Main executable
add_executable(verbal-code main.cpp)
target_link_libraries(verbal-code PRIVATE verbal_app)
