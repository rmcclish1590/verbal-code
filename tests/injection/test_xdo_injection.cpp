// Include gtest before xdo — X11/Xlib.h #defines None which conflicts with gtest internals
#include <gtest/gtest.h>

#include "xdo_injection_service.hpp"

using verbal::XdoInjectionService;

TEST(XdoInjectionService, InitialState) {
    XdoInjectionService service;
    EXPECT_FALSE(service.is_running());
    EXPECT_EQ(service.last_injection_length(), 0u);
}

TEST(XdoInjectionService, InjectWithoutStart) {
    XdoInjectionService service;
    auto result = service.inject_text("test");
    EXPECT_TRUE(result.is_err());
}
