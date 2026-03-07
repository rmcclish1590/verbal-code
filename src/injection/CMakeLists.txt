# Wayland injection service (no compile-time deps)
add_library(verbal_wayland_injection
    wayland_injection_service.cpp
)
target_include_directories(verbal_wayland_injection PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(verbal_wayland_injection PUBLIC verbal_core)

# X11 injection service (requires libxdo)
if(NOT XDO_FOUND)
    message(STATUS "Skipping X11 injection module (libxdo not found)")
    # Still create verbal_injection as alias to wayland-only
    add_library(verbal_injection ALIAS verbal_wayland_injection)
    return()
endif()

add_library(verbal_injection
    xdo_injection_service.cpp
)

target_include_directories(verbal_injection PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} ${XDO_INCLUDE_DIRS})
target_link_libraries(verbal_injection
    PUBLIC verbal_core ${XDO_LIBRARIES}
)
