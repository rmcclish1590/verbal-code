if(NOT XDO_FOUND)
    message(STATUS "Skipping injection module (libxdo not found)")
    return()
endif()

add_library(verbal_injection
    xdo_injection_service.cpp
)

target_include_directories(verbal_injection PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} ${XDO_INCLUDE_DIRS})
target_link_libraries(verbal_injection
    PUBLIC verbal_core ${XDO_LIBRARIES}
)
