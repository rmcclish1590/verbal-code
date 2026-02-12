#pragma once

#include <nlohmann/json.hpp>
#include <string>
#include <vector>
#include <mutex>

namespace verbal {

class Config {
public:
    Config();

    // Load config from file. Falls back to defaults if file doesn't exist.
    bool load(const std::string& path = "");
    bool save(const std::string& path = "") const;

    // Default config path: ~/.config/verbal-code/config.json
    static std::string default_config_path();
    static std::string default_data_dir();

    // Typed accessors
    std::vector<std::string> hotkey_modifiers() const;
    int sample_rate() const;
    int channels() const;
    std::string vosk_model() const;
    std::string whisper_model() const;
    bool whisper_refinement_enabled() const;
    int overlay_x() const;
    int overlay_y() const;
    int overlay_size() const;
    std::string transcriptions_path() const;
    int max_transcriptions() const;

    // Setters
    void set_overlay_position(int x, int y);
    void set_hotkey_modifiers(const std::vector<std::string>& mods);

    // Raw access
    const nlohmann::json& data() const { return data_; }

private:
    void apply_defaults();
    static std::string expand_path(const std::string& path);

    nlohmann::json data_;
    std::string config_path_;
    mutable std::mutex mutex_;
};

} // namespace verbal
