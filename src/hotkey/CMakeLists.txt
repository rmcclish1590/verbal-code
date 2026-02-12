if(NOT HOTKEY_DEPS_FOUND)
    message(STATUS "Skipping hotkey module (XCB/xkbcommon not found)")
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
