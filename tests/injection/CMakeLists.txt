if(NOT TARGET verbal_injection)
    return()
endif()

verbal_add_test(test_xdo_injection test_xdo_injection.cpp verbal_injection)
