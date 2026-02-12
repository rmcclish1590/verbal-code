add_library(verbal_recognition
    vosk_recognition_service.cpp
    model_manager.cpp
    transcription_orchestrator.cpp
)

target_include_directories(verbal_recognition PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(verbal_recognition
    PUBLIC verbal_core vosk
)

if(ENABLE_WHISPER)
    target_sources(verbal_recognition PRIVATE whisper_refinement_service.cpp)
    target_link_libraries(verbal_recognition PRIVATE whisper)
    target_compile_definitions(verbal_recognition PUBLIC VERBAL_ENABLE_WHISPER=1)
endif()
