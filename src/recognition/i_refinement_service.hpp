#pragma once

#include "result.hpp"
#include "types.hpp"

#include <string>
#include <vector>

namespace verbal {

class IRefinementService {
public:
    virtual ~IRefinementService() = default;

    virtual Result<void> init() = 0;
    virtual Result<std::string> refine(const std::vector<AudioSample>& audio, int sample_rate = DEFAULT_SAMPLE_RATE) = 0;
    virtual bool is_initialized() const = 0;

    /// Set an initial prompt to guide recognition (e.g., vocabulary hints).
    /// Default implementation is a no-op so existing services (Vosk) are unaffected.
    virtual void set_initial_prompt(const std::string& /*prompt*/) {}
};

} // namespace verbal
