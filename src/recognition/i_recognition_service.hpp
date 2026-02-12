#pragma once

#include "i_service.hpp"
#include "types.hpp"

namespace verbal {

class IRecognitionService : public IService {
public:
    ~IRecognitionService() override = default;

    // Callbacks for partial (streaming) and final results
    virtual void set_on_partial(TextCallback cb) = 0;
    virtual void set_on_final(TextCallback cb) = 0;

    // Feed audio data for processing
    virtual void feed_audio(const AudioSample* data, size_t count) = 0;

    // Reset recognizer state for new utterance
    virtual void reset() = 0;

    // Get the final result after stopping
    virtual std::string final_result() = 0;
};

} // namespace verbal
