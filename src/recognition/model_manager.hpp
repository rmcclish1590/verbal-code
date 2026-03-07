#pragma once

#include "result.hpp"

#include <string>

namespace verbal {

class ModelManager {
public:
    explicit ModelManager(const std::string& data_dir = "");

    // Get path to Vosk model directory. Returns error if not found.
    Result<std::string> vosk_model_path(const std::string& model_name) const;

    // Get path to Whisper model file. Returns error if not found.
    Result<std::string> whisper_model_path(const std::string& model_name) const;

private:
    std::string data_dir_;
    std::string models_dir_;
};

} // namespace verbal
