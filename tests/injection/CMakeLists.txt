if(TARGET verbal_injection)
    verbal_add_test(test_xdo_injection test_xdo_injection.cpp verbal_injection)
endif()

if(TARGET verbal_wayland_injection)
    verbal_add_test(test_wayland_injection test_wayland_injection.cpp verbal_wayland_injection)
endif()
