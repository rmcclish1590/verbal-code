#include "audio_buffer.hpp"

#include <gtest/gtest.h>
#include <thread>

using verbal::AudioBuffer;
using verbal::AudioSample;

TEST(AudioBuffer, AppendAndRead) {
    AudioBuffer buf;
    AudioSample data[] = {100, 200, 300};
    buf.append(data, 3);
    EXPECT_EQ(buf.size(), 3u);

    auto samples = buf.get_samples();
    ASSERT_EQ(samples.size(), 3u);
    EXPECT_EQ(samples[0], 100);
    EXPECT_EQ(samples[1], 200);
    EXPECT_EQ(samples[2], 300);
}

TEST(AudioBuffer, Clear) {
    AudioBuffer buf;
    AudioSample data[] = {1, 2, 3};
    buf.append(data, 3);
    EXPECT_FALSE(buf.empty());

    buf.clear();
    EXPECT_TRUE(buf.empty());
    EXPECT_EQ(buf.size(), 0u);
}

TEST(AudioBuffer, DurationMs) {
    AudioBuffer buf;
    // 16000 samples = 1 second = 1000 ms
    std::vector<AudioSample> one_second(16000, 0);
    buf.append(one_second.data(), one_second.size());
    EXPECT_EQ(buf.duration_ms(), 1000u);
}

TEST(AudioBuffer, MultipleAppends) {
    AudioBuffer buf;
    AudioSample a[] = {1, 2};
    AudioSample b[] = {3, 4, 5};
    buf.append(a, 2);
    buf.append(b, 3);
    EXPECT_EQ(buf.size(), 5u);

    auto samples = buf.get_samples();
    EXPECT_EQ(samples[0], 1);
    EXPECT_EQ(samples[4], 5);
}

TEST(AudioBuffer, ThreadSafety) {
    AudioBuffer buf;
    constexpr int ITERATIONS = 10000;

    std::thread writer([&]() {
        for (int i = 0; i < ITERATIONS; ++i) {
            AudioSample s = static_cast<AudioSample>(i);
            buf.append(&s, 1);
        }
    });

    std::thread reader([&]() {
        for (int i = 0; i < ITERATIONS; ++i) {
            auto samples = buf.get_samples();
            // Just verify no crash
            (void)samples.size();
        }
    });

    writer.join();
    reader.join();

    EXPECT_EQ(buf.size(), static_cast<size_t>(ITERATIONS));
}
