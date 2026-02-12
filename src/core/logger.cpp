#include "logger.hpp"

#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>

namespace verbal {

Logger& Logger::instance() {
    static Logger logger;
    return logger;
}

const char* Logger::level_str(LogLevel level) {
    switch (level) {
        case LogLevel::DEBUG: return "DEBUG";
        case LogLevel::INFO:  return "INFO ";
        case LogLevel::WARN:  return "WARN ";
        case LogLevel::ERROR: return "ERROR";
    }
    return "?????";
}

void Logger::log(LogLevel level, const std::string& tag, const std::string& msg) {
    if (level < level_) return;

    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(
        now.time_since_epoch()) % 1000;

    std::lock_guard<std::mutex> lock(mutex_);
    std::tm tm_buf{};
    localtime_r(&time, &tm_buf);

    std::ostringstream oss;
    oss << std::put_time(&tm_buf, "%H:%M:%S")
        << '.' << std::setfill('0') << std::setw(3) << ms.count()
        << " [" << level_str(level) << "] "
        << "[" << tag << "] "
        << msg << '\n';

    std::cerr << oss.str();
}

} // namespace verbal
