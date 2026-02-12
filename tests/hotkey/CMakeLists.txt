if(NOT TARGET verbal_hotkey)
    return()
endif()

verbal_add_test(test_xcb_hotkey_service test_xcb_hotkey_service.cpp verbal_hotkey)
