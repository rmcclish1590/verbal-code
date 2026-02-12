if(NOT GTK3_FOUND)
    message(STATUS "Skipping overlay module (GTK3 not found)")
    return()
endif()

add_library(verbal_overlay
    gtk_overlay_service.cpp
)

target_include_directories(verbal_overlay PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} ${GTK3_INCLUDE_DIRS})
target_link_libraries(verbal_overlay
    PUBLIC verbal_core ${GTK3_LIBRARIES}
)
target_compile_options(verbal_overlay PRIVATE ${GTK3_CFLAGS_OTHER})
