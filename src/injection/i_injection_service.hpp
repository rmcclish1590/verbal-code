#pragma once

#include "i_service.hpp"

#include <string>

namespace verbal {

class IInjectionService : public IService {
public:
    ~IInjectionService() override = default;

    // Type text into the currently focused window
    virtual Result<void> inject_text(const std::string& text) = 0;

    // Check if there is a focused input/text field
    virtual bool has_focused_input() = 0;

    // Clear the last injected text (sends backspaces then retypes)
    virtual Result<void> replace_last_injection(const std::string& new_text) = 0;

    // Get the length of the last injection (in characters)
    virtual size_t last_injection_length() const = 0;
};

} // namespace verbal
