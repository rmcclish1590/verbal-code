#pragma once

#include "i_service.hpp"
#include "ring_buffer.hpp"
#include "types.hpp"

#include <functional>

namespace verbal {

class IAudioService : public IService {
public:
    ~IAudioService() override = default;

    virtual void set_ring_buffer(RingBuffer<AudioSample>* buffer) = 0;

    // Start/stop audio capture
    virtual Result<void> start_capture() = 0;
    virtual void stop_capture() = 0;
    virtual bool is_capturing() const = 0;

    // Get the full recorded audio since last start_capture (for Whisper post-processing)
    virtual const std::vector<AudioSample>& recorded_audio() const = 0;

    // Callback for stream state changes
    using StateCallback = std::function<void(bool active)>;
    virtual void set_on_state_change(StateCallback cb) = 0;
};

} // namespace verbal
