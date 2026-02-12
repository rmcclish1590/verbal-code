if(NOT TARGET verbal_audio)
    return()
endif()

verbal_add_test(test_audio_buffer test_audio_buffer.cpp verbal_audio)
