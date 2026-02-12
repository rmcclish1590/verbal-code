#include "result.hpp"

#include <gtest/gtest.h>

using verbal::Result;

TEST(Result, OkValue) {
    auto r = Result<int>::ok(42);
    EXPECT_TRUE(r.is_ok());
    EXPECT_FALSE(r.is_err());
    EXPECT_TRUE(static_cast<bool>(r));
    EXPECT_EQ(r.value(), 42);
}

TEST(Result, ErrValue) {
    auto r = Result<int>::err("something failed");
    EXPECT_FALSE(r.is_ok());
    EXPECT_TRUE(r.is_err());
    EXPECT_FALSE(static_cast<bool>(r));
    EXPECT_EQ(r.error(), "something failed");
}

TEST(Result, ValueOnErrorThrows) {
    auto r = Result<int>::err("bad");
    EXPECT_THROW(r.value(), std::runtime_error);
}

TEST(Result, ErrorOnOkThrows) {
    auto r = Result<int>::ok(1);
    EXPECT_THROW(r.error(), std::runtime_error);
}

TEST(Result, ValueOr) {
    auto ok = Result<int>::ok(10);
    EXPECT_EQ(ok.value_or(0), 10);

    auto err = Result<int>::err("fail");
    EXPECT_EQ(err.value_or(99), 99);
}

TEST(Result, Map) {
    auto r = Result<int>::ok(5);
    auto doubled = r.map([](int x) { return x * 2; });
    EXPECT_TRUE(doubled.is_ok());
    EXPECT_EQ(doubled.value(), 10);

    auto e = Result<int>::err("nope");
    auto mapped = e.map([](int x) { return x * 2; });
    EXPECT_TRUE(mapped.is_err());
    EXPECT_EQ(mapped.error(), "nope");
}

TEST(Result, MoveSemantics) {
    auto r = Result<std::string>::ok("hello");
    std::string val = std::move(r).value();
    EXPECT_EQ(val, "hello");
}

TEST(ResultVoid, OkVoid) {
    auto r = Result<void>::ok();
    EXPECT_TRUE(r.is_ok());
    EXPECT_FALSE(r.is_err());
    EXPECT_TRUE(static_cast<bool>(r));
}

TEST(ResultVoid, ErrVoid) {
    auto r = Result<void>::err("failed");
    EXPECT_FALSE(r.is_ok());
    EXPECT_TRUE(r.is_err());
    EXPECT_EQ(r.error(), "failed");
}

TEST(ResultVoid, ErrorOnOkThrows) {
    auto r = Result<void>::ok();
    EXPECT_THROW(r.error(), std::runtime_error);
}
