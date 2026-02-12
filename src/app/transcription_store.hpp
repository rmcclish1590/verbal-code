#pragma once

#include "result.hpp"
#include "types.hpp"

#include <nlohmann/json.hpp>

#include <mutex>
#include <string>
#include <vector>

namespace verbal {

struct TranscriptionEntry {
    std::string timestamp;
    std::string text;
    TranscriptionSource source;
};

class TranscriptionStore {
public:
    explicit TranscriptionStore(const std::string& path, int max_entries = 1000);

    Result<void> load();
    Result<void> save() const;

    void append(const std::string& text, TranscriptionSource source);
    const std::vector<TranscriptionEntry>& entries() const { return entries_; }
    size_t size() const;
    void clear();

private:
    static std::string current_timestamp();
    static std::string source_to_string(TranscriptionSource src);
    static TranscriptionSource string_to_source(const std::string& s);

    std::string path_;
    int max_entries_;
    std::vector<TranscriptionEntry> entries_;
    mutable std::mutex mutex_;
};

} // namespace verbal
