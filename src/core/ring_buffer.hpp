#pragma once

#include <atomic>
#include <cstddef>
#include <cstring>
#include <memory>
#include <vector>

namespace verbal {

// Lock-free single-producer, single-consumer ring buffer.
// Designed for the audio capture → recognition pipeline.
// Uses acquire/release memory ordering for thread safety.
template<typename T>
class RingBuffer {
public:
    explicit RingBuffer(size_t capacity)
        : capacity_(capacity)
        , buffer_(std::make_unique<T[]>(capacity))
        , read_pos_(0)
        , write_pos_(0)
    {
    }

    // Non-copyable, non-movable (atomic members)
    RingBuffer(const RingBuffer&) = delete;
    RingBuffer& operator=(const RingBuffer&) = delete;

    // Write a contiguous block of items. Returns number actually written.
    size_t write(const T* data, size_t count) {
        const size_t wp = write_pos_.load(std::memory_order_relaxed);
        const size_t rp = read_pos_.load(std::memory_order_acquire);
        const size_t available = available_write(wp, rp);
        const size_t to_write = (count <= available) ? count : available;

        if (to_write == 0) return 0;

        const size_t first = capacity_ - (wp % capacity_);
        if (to_write <= first) {
            std::memcpy(&buffer_[wp % capacity_], data, to_write * sizeof(T));
        } else {
            std::memcpy(&buffer_[wp % capacity_], data, first * sizeof(T));
            std::memcpy(&buffer_[0], data + first, (to_write - first) * sizeof(T));
        }

        write_pos_.store(wp + to_write, std::memory_order_release);
        return to_write;
    }

    // Read a contiguous block of items. Returns number actually read.
    size_t read(T* data, size_t count) {
        const size_t rp = read_pos_.load(std::memory_order_relaxed);
        const size_t wp = write_pos_.load(std::memory_order_acquire);
        const size_t available = wp - rp;
        const size_t to_read = (count <= available) ? count : available;

        if (to_read == 0) return 0;

        const size_t first = capacity_ - (rp % capacity_);
        if (to_read <= first) {
            std::memcpy(data, &buffer_[rp % capacity_], to_read * sizeof(T));
        } else {
            std::memcpy(data, &buffer_[rp % capacity_], first * sizeof(T));
            std::memcpy(data + first, &buffer_[0], (to_read - first) * sizeof(T));
        }

        read_pos_.store(rp + to_read, std::memory_order_release);
        return to_read;
    }

    // Peek at available data without consuming it. Returns number copied.
    size_t peek(T* data, size_t count) const {
        const size_t rp = read_pos_.load(std::memory_order_relaxed);
        const size_t wp = write_pos_.load(std::memory_order_acquire);
        const size_t available = wp - rp;
        const size_t to_read = (count <= available) ? count : available;

        if (to_read == 0) return 0;

        const size_t first = capacity_ - (rp % capacity_);
        if (to_read <= first) {
            std::memcpy(data, &buffer_[rp % capacity_], to_read * sizeof(T));
        } else {
            std::memcpy(data, &buffer_[rp % capacity_], first * sizeof(T));
            std::memcpy(data + first, &buffer_[0], (to_read - first) * sizeof(T));
        }

        return to_read;
    }

    size_t available_read() const {
        const size_t rp = read_pos_.load(std::memory_order_relaxed);
        const size_t wp = write_pos_.load(std::memory_order_acquire);
        return wp - rp;
    }

    size_t available_write() const {
        const size_t wp = write_pos_.load(std::memory_order_relaxed);
        const size_t rp = read_pos_.load(std::memory_order_acquire);
        return available_write(wp, rp);
    }

    size_t capacity() const { return capacity_; }

    void reset() {
        read_pos_.store(0, std::memory_order_relaxed);
        write_pos_.store(0, std::memory_order_relaxed);
    }

private:
    size_t available_write(size_t wp, size_t rp) const {
        return capacity_ - (wp - rp);
    }

    const size_t capacity_;
    std::unique_ptr<T[]> buffer_;
    alignas(64) std::atomic<size_t> read_pos_;
    alignas(64) std::atomic<size_t> write_pos_;
};

} // namespace verbal
