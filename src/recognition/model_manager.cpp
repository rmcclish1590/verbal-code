#include "model_manager.hpp"
#include "config.hpp"

#include <filesystem>

namespace fs = std::filesystem;

namespace verbal {

ModelManager::ModelManager(const std::string& data_dir)
    : data_dir_(data_dir.empty() ? Config::default_data_dir() : data_dir)
    , models_dir_(data_dir_ + "/models")
{
}

Result<std::string> ModelManager::vosk_model_path(const std::string& model_name) const {
    if (model_name.find('/') != std::string::npos ||
        model_name.find("..") != std::string::npos) {
        return Result<std::string>::err("Invalid model name: " + model_name);
    }
    std::string path = models_dir_ + "/" + model_name;
    if (fs::exists(path) && fs::is_directory(path)) {
        return Result<std::string>::ok(path);
    }
    return Result<std::string>::err(
        "Vosk model not found at: " + path +
        "\nRun scripts/download_models.sh to download models.");
}

Result<std::string> ModelManager::whisper_model_path(const std::string& model_name) const {
    if (model_name.find('/') != std::string::npos ||
        model_name.find("..") != std::string::npos) {
        return Result<std::string>::err("Invalid model name: " + model_name);
    }
    std::string filename = "ggml-" + model_name + ".bin";
    std::string path = models_dir_ + "/" + filename;
    if (fs::exists(path) && fs::is_regular_file(path)) {
        return Result<std::string>::ok(path);
    }
    return Result<std::string>::err(
        "Whisper model not found at: " + path +
        "\nRun scripts/download_models.sh to download models.");
}

} // namespace verbal
