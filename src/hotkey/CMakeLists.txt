# Evdev hotkey service (Linux only, no external deps)
if(EVDEV_HOTKEY_AVAILABLE)
    add_library(verbal_evdev_hotkey
        evdev_hotkey_service.cpp
    )
    target_include_directories(verbal_evdev_hotkey PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
    )
    target_link_libraries(verbal_evdev_hotkey
        PUBLIC verbal_core
    )
    message(STATUS "Evdev hotkey service enabled")
endif()

# Portal hotkey service (requires GIO/GLib from GTK3)
if(PORTAL_HOTKEY_DEPS_FOUND)
    add_library(verbal_portal_hotkey
        portal_hotkey_service.cpp
    )
    target_include_directories(verbal_portal_hotkey PUBLIC
        ${CMAKE_CURRENT_SOURCE_DIR}
        ${GIO_INCLUDE_DIRS}
    )
    target_link_libraries(verbal_portal_hotkey
        PUBLIC verbal_core ${GIO_LIBRARIES}
    )
    target_compile_options(verbal_portal_hotkey PRIVATE ${GIO_CFLAGS_OTHER})
    message(STATUS "Portal hotkey service enabled (GIO found)")
endif()

# XCB hotkey service (requires XCB + xkbcommon)
if(NOT HOTKEY_DEPS_FOUND)
    message(STATUS "Skipping XCB hotkey module (XCB/xkbcommon not found)")
    if(PORTAL_HOTKEY_DEPS_FOUND)
        # Create verbal_hotkey as alias to portal backend
        add_library(verbal_hotkey ALIAS verbal_portal_hotkey)
    endif()
    return()
endif()

add_library(verbal_hotkey
    xcb_hotkey_service.cpp
)

target_include_directories(verbal_hotkey PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${XCB_INCLUDE_DIRS}
    ${XCB_XINPUT_INCLUDE_DIRS}
    ${XKBCOMMON_INCLUDE_DIRS}
    ${XKBCOMMON_X11_INCLUDE_DIRS}
)
target_link_libraries(verbal_hotkey
    PUBLIC verbal_core
        ${XCB_LIBRARIES}
        ${XCB_XINPUT_LIBRARIES}
        ${XKBCOMMON_LIBRARIES}
        ${XKBCOMMON_X11_LIBRARIES}
)
