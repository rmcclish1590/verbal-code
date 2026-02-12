if(NOT PIPEWIRE_FOUND)
    message(STATUS "Skipping audio module (PipeWire not found)")
    return()
endif()

add_library(verbal_audio
    pipewire_audio_service.cpp
)

target_include_directories(verbal_audio PUBLIC ${CMAKE_CURRENT_SOURCE_DIR} ${PIPEWIRE_INCLUDE_DIRS})
target_link_libraries(verbal_audio
    PUBLIC verbal_core ${PIPEWIRE_LIBRARIES}
)
target_compile_options(verbal_audio PRIVATE ${PIPEWIRE_CFLAGS_OTHER} -Wno-pedantic -Wno-missing-field-initializers)
