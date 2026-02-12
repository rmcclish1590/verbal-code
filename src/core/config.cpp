#include "config.hpp"

#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>

namespace fs = std::filesystem;

namespace verbal {

namespace {

nlohmann::json default_config() {
    return nlohmann::json{
        {"hotkey", {{"modifiers", {"ctrl", "super", "alt"}}}},
        {"audio", {{"sample_rate", 16000}, {"channels", 1}}},
        {"recognition", {
            {"vosk_model", "vosk-model-small-en-us-0.15"},
            {"whisper_model", "base.en"},
            {"enable_whisper_refinement", true}
        }},
        {"overlay", {{"position", {{"x", -1}, {"y", -1}}}, {"size", 20}}},
        {"storage", {
            {"transcriptions_path", "~/.config/verbal-code/transcriptions.json"},
            {"max_transcriptions", 1000}
        }}
    };
}

// Check if two JSON values have compatible types for merging.
// Treats all numeric types (int, unsigned, float) as compatible.
bool types_compatible(const nlohmann::json& a, const nlohmann::json& b) {
    if (a.type() == b.type()) return true;
    if (a.is_number() && b.is_number()) return true;
    return false;
}

// Recursively merge 'patch' into 'base', but only when the value type matches
// the default. Prevents old config schemas from corrupting the structure
// (e.g., a string "ctrl+alt+z" replacing an object {"modifiers": [...]}).
void merge_safe(nlohmann::json& base, const nlohmann::json& patch) {
    if (!base.is_object() || !patch.is_object()) return;
    for (auto it = patch.begin(); it != patch.end(); ++it) {
        auto base_it = base.find(it.key());
        if (base_it == base.end()) continue; // ignore unknown keys
        if (base_it->is_object() && it->is_object()) {
            merge_safe(*base_it, *it);
        } else if (types_compatible(*base_it, *it)) {
            *base_it = *it;
        }
        // else: type mismatch — keep the default
    }
}

} // namespace

Config::Config() : data_(default_config()) {}

std::string Config::expand_path(const std::string& path) {
    if (path.empty()) return path;
    if (path[0] == '~') {
        const char* home = std::getenv("HOME");
        if (home) {
            return std::string(home) + path.substr(1);
        }
    }
    return path;
}

std::string Config::default_config_path() {
    const char* xdg_config = std::getenv("XDG_CONFIG_HOME");
    if (xdg_config && xdg_config[0] != '\0') {
        return std::string(xdg_config) + "/verbal-code/config.json";
    }
    return expand_path("~/.config/verbal-code/config.json");
}

std::string Config::default_data_dir() {
    const char* xdg_data = std::getenv("XDG_DATA_HOME");
    if (xdg_data && xdg_data[0] != '\0') {
        return std::string(xdg_data) + "/verbal-code";
    }
    return expand_path("~/.local/share/verbal-code");
}

bool Config::load(const std::string& path) {
    std::lock_guard<std::mutex> lock(mutex_);

    config_path_ = path.empty() ? default_config_path() : path;

    if (!fs::exists(config_path_)) {
        apply_defaults();
        return false;
    }

    try {
        std::ifstream file(config_path_);
        if (!file.is_open()) {
            apply_defaults();
            return false;
        }
        nlohmann::json loaded = nlohmann::json::parse(file);
        // Start from defaults, then selectively merge only matching types
        data_ = default_config();
        merge_safe(data_, loaded);
        return true;
    } catch (const nlohmann::json::exception& e) {
        std::cerr << "Config parse error: " << e.what() << "\n";
        apply_defaults();
        return false;
    }
}

bool Config::save(const std::string& path) const {
    std::lock_guard<std::mutex> lock(mutex_);

    std::string save_path = path.empty() ? config_path_ : path;
    if (save_path.empty()) {
        save_path = default_config_path();
    }

    try {
        fs::create_directories(fs::path(save_path).parent_path());
        std::ofstream file(save_path);
        if (!file.is_open()) return false;
        file << data_.dump(4) << "\n";
        return true;
    } catch (const std::exception& e) {
        std::cerr << "Config save error: " << e.what() << "\n";
        return false;
    }
}

void Config::apply_defaults() {
    data_ = default_config();
}

std::vector<std::string> Config::hotkey_modifiers() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["hotkey"]["modifiers"].get<std::vector<std::string>>();
}

int Config::sample_rate() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["audio"]["sample_rate"].get<int>();
}

int Config::channels() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["audio"]["channels"].get<int>();
}

std::string Config::vosk_model() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["recognition"]["vosk_model"].get<std::string>();
}

std::string Config::whisper_model() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["recognition"]["whisper_model"].get<std::string>();
}

bool Config::whisper_refinement_enabled() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["recognition"]["enable_whisper_refinement"].get<bool>();
}

int Config::overlay_x() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["overlay"]["position"]["x"].get<int>();
}

int Config::overlay_y() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["overlay"]["position"]["y"].get<int>();
}

int Config::overlay_size() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["overlay"]["size"].get<int>();
}

std::string Config::transcriptions_path() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return expand_path(data_["storage"]["transcriptions_path"].get<std::string>());
}

int Config::max_transcriptions() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return data_["storage"]["max_transcriptions"].get<int>();
}

void Config::set_overlay_position(int x, int y) {
    std::lock_guard<std::mutex> lock(mutex_);
    data_["overlay"]["position"]["x"] = x;
    data_["overlay"]["position"]["y"] = y;
}

void Config::set_hotkey_modifiers(const std::vector<std::string>& mods) {
    std::lock_guard<std::mutex> lock(mutex_);
    data_["hotkey"]["modifiers"] = mods;
}

} // namespace verbal
