#pragma once

#include <string>
#include <mutex>
#include <iostream>

namespace verbal {

enum class LogLevel {
    DEBUG,
    INFO,
    WARN,
    ERROR
};

class Logger {
public:
    static Logger& instance();

    void set_level(LogLevel level) { level_ = level; }
    LogLevel level() const { return level_; }

    void log(LogLevel level, const std::string& tag, const std::string& msg);

    void debug(const std::string& tag, const std::string& msg) { log(LogLevel::DEBUG, tag, msg); }
    void info(const std::string& tag, const std::string& msg) { log(LogLevel::INFO, tag, msg); }
    void warn(const std::string& tag, const std::string& msg) { log(LogLevel::WARN, tag, msg); }
    void error(const std::string& tag, const std::string& msg) { log(LogLevel::ERROR, tag, msg); }

private:
    Logger() = default;
    Logger(const Logger&) = delete;
    Logger& operator=(const Logger&) = delete;

    static const char* level_str(LogLevel level);

    LogLevel level_ = LogLevel::INFO;
    std::mutex mutex_;
};

// Convenience macros
#define LOG_DEBUG(tag, msg) verbal::Logger::instance().debug(tag, msg)
#define LOG_INFO(tag, msg) verbal::Logger::instance().info(tag, msg)
#define LOG_WARN(tag, msg) verbal::Logger::instance().warn(tag, msg)
#define LOG_ERROR(tag, msg) verbal::Logger::instance().error(tag, msg)

} // namespace verbal
