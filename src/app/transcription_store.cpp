#include "transcription_store.hpp"

#include <chrono>
#include <ctime>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <sstream>

namespace fs = std::filesystem;

namespace verbal {

TranscriptionStore::TranscriptionStore(const std::string& path, int max_entries)
    : path_(path)
    , max_entries_(max_entries)
{
}

Result<void> TranscriptionStore::load() {
    std::lock_guard<std::mutex> lock(mutex_);

    if (!fs::exists(path_)) {
        return Result<void>::ok(); // Empty store is fine
    }

    try {
        std::ifstream file(path_);
        if (!file.is_open()) {
            return Result<void>::err("Cannot open transcriptions file: " + path_);
        }

        auto j = nlohmann::json::parse(file);
        entries_.clear();

        if (j.is_array()) {
            for (const auto& item : j) {
                TranscriptionEntry entry;
                entry.timestamp = item.value("timestamp", "");
                entry.text = item.value("text", "");
                entry.source = string_to_source(item.value("source", "vosk"));
                entries_.push_back(std::move(entry));
            }
        }

        return Result<void>::ok();
    } catch (const std::exception& e) {
        return Result<void>::err("Failed to parse transcriptions: " + std::string(e.what()));
    }
}

Result<void> TranscriptionStore::save() const {
    std::lock_guard<std::mutex> lock(mutex_);

    try {
        fs::create_directories(fs::path(path_).parent_path());
        std::ofstream file(path_);
        if (!file.is_open()) {
            return Result<void>::err("Cannot write transcriptions file: " + path_);
        }

        nlohmann::json j = nlohmann::json::array();
        for (const auto& entry : entries_) {
            j.push_back({
                {"timestamp", entry.timestamp},
                {"text", entry.text},
                {"source", source_to_string(entry.source)}
            });
        }

        file << j.dump(2) << "\n";
        return Result<void>::ok();
    } catch (const std::exception& e) {
        return Result<void>::err("Failed to save transcriptions: " + std::string(e.what()));
    }
}

void TranscriptionStore::append(const std::string& text, TranscriptionSource source) {
    std::lock_guard<std::mutex> lock(mutex_);

    TranscriptionEntry entry;
    entry.timestamp = current_timestamp();
    entry.text = text;
    entry.source = source;
    entries_.push_back(std::move(entry));

    // Enforce max entries
    if (max_entries_ > 0 && static_cast<int>(entries_.size()) > max_entries_) {
        entries_.erase(entries_.begin(),
                       entries_.begin() + (static_cast<int>(entries_.size()) - max_entries_));
    }
}

size_t TranscriptionStore::size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return entries_.size();
}

void TranscriptionStore::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    entries_.clear();
}

std::string TranscriptionStore::current_timestamp() {
    auto now = std::chrono::system_clock::now();
    auto time = std::chrono::system_clock::to_time_t(now);
    std::tm tm_buf{};
    localtime_r(&time, &tm_buf);
    std::ostringstream oss;
    oss << std::put_time(&tm_buf, "%Y-%m-%dT%H:%M:%S");
    return oss.str();
}

std::string TranscriptionStore::source_to_string(TranscriptionSource src) {
    switch (src) {
        case TranscriptionSource::VOSK: return "vosk";
        case TranscriptionSource::WHISPER: return "whisper";
    }
    return "unknown";
}

TranscriptionSource TranscriptionStore::string_to_source(const std::string& s) {
    if (s == "whisper") return TranscriptionSource::WHISPER;
    return TranscriptionSource::VOSK;
}

} // namespace verbal
