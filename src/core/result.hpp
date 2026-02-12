#pragma once

#include <string>
#include <stdexcept>
#include <utility>

namespace verbal {

// Lightweight Result<T, E> type for service boundaries.
// Uses a bool tag + storage to avoid the std::variant same-type issue.
template<typename T, typename E = std::string>
class Result {
public:
    static Result ok(T value) {
        Result r;
        r.is_ok_ = true;
        r.value_ = std::move(value);
        return r;
    }

    static Result err(E error) {
        Result r;
        r.is_ok_ = false;
        r.error_ = std::move(error);
        return r;
    }

    bool is_ok() const { return is_ok_; }
    bool is_err() const { return !is_ok_; }
    explicit operator bool() const { return is_ok_; }

    const T& value() const& {
        if (!is_ok_) throw std::runtime_error("Result::value() called on error");
        return value_;
    }

    T& value() & {
        if (!is_ok_) throw std::runtime_error("Result::value() called on error");
        return value_;
    }

    T&& value() && {
        if (!is_ok_) throw std::runtime_error("Result::value() called on error");
        return std::move(value_);
    }

    const E& error() const& {
        if (is_ok_) throw std::runtime_error("Result::error() called on ok value");
        return error_;
    }

    template<typename F>
    auto map(F&& f) const -> Result<decltype(f(std::declval<T>())), E> {
        using U = decltype(f(std::declval<T>()));
        if (is_ok_) return Result<U, E>::ok(f(value_));
        return Result<U, E>::err(error_);
    }

    T value_or(T default_value) const {
        if (is_ok_) return value_;
        return default_value;
    }

private:
    Result() = default;
    bool is_ok_ = false;
    T value_{};
    E error_{};
};

// Specialization for void success type
template<typename E>
class Result<void, E> {
public:
    static Result ok() {
        Result r;
        r.is_ok_ = true;
        return r;
    }

    static Result err(E error) {
        Result r;
        r.is_ok_ = false;
        r.error_ = std::move(error);
        return r;
    }

    bool is_ok() const { return is_ok_; }
    bool is_err() const { return !is_ok_; }
    explicit operator bool() const { return is_ok_; }

    const E& error() const {
        if (is_ok_) throw std::runtime_error("Result::error() called on ok value");
        return error_;
    }

private:
    Result() = default;
    bool is_ok_ = false;
    E error_;
};

} // namespace verbal
