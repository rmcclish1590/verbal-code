#pragma once

#include "result.hpp"

namespace verbal {

// Base interface for all services
class IService {
public:
    virtual ~IService() = default;
    virtual Result<void> start() = 0;
    virtual void stop() = 0;
    virtual bool is_running() const = 0;
};

} // namespace verbal
