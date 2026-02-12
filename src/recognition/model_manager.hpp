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

    // Check if a model exists
    bool has_vosk_model(const std::string& model_name) const;
    bool has_whisper_model(const std::string& model_name) const;

    const std::string& data_dir() const { return data_dir_; }
    const std::string& models_dir() const { return models_dir_; }

private:
    std::string data_dir_;
    std::string models_dir_;
};

} // namespace verbal
