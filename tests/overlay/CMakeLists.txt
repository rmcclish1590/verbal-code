if(NOT TARGET verbal_overlay)
    return()
endif()

verbal_add_test(test_gtk_overlay test_gtk_overlay.cpp verbal_overlay)
