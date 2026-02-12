#pragma once

#include "types.hpp"

#include <cstddef>
#include <mutex>
#include <vector>

namespace verbal {

// Accumulator buffer that stores a full copy of the recording for Whisper post-processing.
// Thread-safe: audio thread writes, STT thread may read after recording stops.
class AudioBuffer {
public:
    explicit AudioBuffer(size_t reserve_samples = DEFAULT_SAMPLE_RATE * 60) {
        samples_.reserve(reserve_samples);
    }

    void append(const AudioSample* data, size_t count) {
        std::lock_guard<std::mutex> lock(mutex_);
        samples_.insert(samples_.end(), data, data + count);
    }

    void clear() {
        std::lock_guard<std::mutex> lock(mutex_);
        samples_.clear();
    }

    std::vector<AudioSample> get_samples() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return samples_;
    }

    size_t size() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return samples_.size();
    }

    bool empty() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return samples_.empty();
    }

    // Duration in milliseconds
    size_t duration_ms() const {
        std::lock_guard<std::mutex> lock(mutex_);
        return samples_.size() / SAMPLES_PER_MS;
    }

private:
    std::vector<AudioSample> samples_;
    mutable std::mutex mutex_;
};

} // namespace verbal
