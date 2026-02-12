#include "ring_buffer.hpp"

#include <gtest/gtest.h>
#include <thread>
#include <vector>
#include <numeric>

using verbal::RingBuffer;

TEST(RingBuffer, BasicWriteRead) {
    RingBuffer<int> buf(16);
    int data[] = {1, 2, 3, 4, 5};
    EXPECT_EQ(buf.write(data, 5), 5u);
    EXPECT_EQ(buf.available_read(), 5u);

    int out[5] = {};
    EXPECT_EQ(buf.read(out, 5), 5u);
    for (int i = 0; i < 5; ++i) {
        EXPECT_EQ(out[i], i + 1);
    }
    EXPECT_EQ(buf.available_read(), 0u);
}

TEST(RingBuffer, WriteFullBuffer) {
    RingBuffer<int> buf(4);
    int data[] = {1, 2, 3, 4};
    EXPECT_EQ(buf.write(data, 4), 4u);
    EXPECT_EQ(buf.available_write(), 0u);

    // Write should return 0 when full
    int more[] = {5};
    EXPECT_EQ(buf.write(more, 1), 0u);
}

TEST(RingBuffer, Wraparound) {
    RingBuffer<int> buf(4);

    // Fill partially
    int data1[] = {1, 2, 3};
    EXPECT_EQ(buf.write(data1, 3), 3u);

    // Read some to advance read pointer
    int out[2] = {};
    EXPECT_EQ(buf.read(out, 2), 2u);
    EXPECT_EQ(out[0], 1);
    EXPECT_EQ(out[1], 2);

    // Now write wraps around
    int data2[] = {4, 5, 6};
    EXPECT_EQ(buf.write(data2, 3), 3u);

    // Read everything
    int out2[4] = {};
    EXPECT_EQ(buf.read(out2, 4), 4u);
    EXPECT_EQ(out2[0], 3);
    EXPECT_EQ(out2[1], 4);
    EXPECT_EQ(out2[2], 5);
    EXPECT_EQ(out2[3], 6);
}

TEST(RingBuffer, Peek) {
    RingBuffer<int> buf(8);
    int data[] = {10, 20, 30};
    buf.write(data, 3);

    int out[3] = {};
    EXPECT_EQ(buf.peek(out, 3), 3u);
    EXPECT_EQ(out[0], 10);

    // Peek doesn't consume data
    EXPECT_EQ(buf.available_read(), 3u);
}

TEST(RingBuffer, Reset) {
    RingBuffer<int> buf(8);
    int data[] = {1, 2, 3};
    buf.write(data, 3);
    EXPECT_EQ(buf.available_read(), 3u);

    buf.reset();
    EXPECT_EQ(buf.available_read(), 0u);
    EXPECT_EQ(buf.available_write(), 8u);
}

TEST(RingBuffer, PartialRead) {
    RingBuffer<int> buf(8);
    int data[] = {1, 2};
    buf.write(data, 2);

    int out[10] = {};
    // Request more than available
    EXPECT_EQ(buf.read(out, 10), 2u);
    EXPECT_EQ(out[0], 1);
    EXPECT_EQ(out[1], 2);
}

TEST(RingBuffer, ConcurrentReadWrite) {
    constexpr size_t BUF_SIZE = 1024;
    constexpr size_t TOTAL_ITEMS = 100000;
    constexpr size_t CHUNK_SIZE = 64;

    RingBuffer<int> buf(BUF_SIZE);
    std::atomic<bool> done{false};
    std::vector<int> received;
    received.reserve(TOTAL_ITEMS);

    // Writer thread
    std::thread writer([&]() {
        std::vector<int> chunk(CHUNK_SIZE);
        size_t written = 0;
        while (written < TOTAL_ITEMS) {
            size_t to_write = std::min(CHUNK_SIZE, TOTAL_ITEMS - written);
            for (size_t i = 0; i < to_write; ++i) {
                chunk[i] = static_cast<int>(written + i);
            }
            size_t n = buf.write(chunk.data(), to_write);
            written += n;
            if (n == 0) {
                std::this_thread::yield();
            }
        }
        done.store(true, std::memory_order_release);
    });

    // Reader thread
    std::thread reader([&]() {
        std::vector<int> chunk(CHUNK_SIZE);
        while (!done.load(std::memory_order_acquire) || buf.available_read() > 0) {
            size_t n = buf.read(chunk.data(), CHUNK_SIZE);
            for (size_t i = 0; i < n; ++i) {
                received.push_back(chunk[i]);
            }
            if (n == 0) {
                std::this_thread::yield();
            }
        }
    });

    writer.join();
    reader.join();

    // Verify all items received in order
    ASSERT_EQ(received.size(), TOTAL_ITEMS);
    for (size_t i = 0; i < TOTAL_ITEMS; ++i) {
        EXPECT_EQ(received[i], static_cast<int>(i)) << "Mismatch at index " << i;
    }
}
