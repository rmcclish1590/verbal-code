if(TARGET verbal_hotkey)
    verbal_add_test(test_xcb_hotkey_service test_xcb_hotkey_service.cpp verbal_hotkey)
endif()

if(TARGET verbal_portal_hotkey)
    verbal_add_test(test_portal_hotkey_service test_portal_hotkey_service.cpp verbal_portal_hotkey)
endif()

if(TARGET verbal_evdev_hotkey)
    verbal_add_test(test_evdev_hotkey_service test_evdev_hotkey_service.cpp verbal_evdev_hotkey)
endif()
