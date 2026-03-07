#pragma once

#include "i_recognition_service.hpp"
#include "i_refinement_service.hpp"

#include <string>
#include <vector>

namespace verbal {
namespace testing {

class MockRecognitionService : public IRecognitionService {
public:
    // IService
    Result<void> start() override { running_ = true; return Result<void>::ok(); }
    void stop() override { running_ = false; }
    bool is_running() const override { return running_; }

    // IRecognitionService
    void set_on_partial(TextCallback cb) override { on_partial_ = std::move(cb); }
    void set_on_final(TextCallback cb) override { on_final_ = std::move(cb); }
    void feed_audio(const AudioSample*, size_t) override {}
    void reset() override { reset_called_ = true; }
    std::string final_result() override { return final_result_; }
    void start_streaming() override { streaming_ = true; }
    void stop_streaming() override { streaming_ = false; }

    // Test helpers — simulate recognition events
    void emit_partial(const std::string& text) {
        if (on_partial_) on_partial_(text);
    }

    void emit_final(const std::string& text) {
        if (on_final_) on_final_(text);
    }

    void set_final_result(const std::string& text) { final_result_ = text; }

    bool reset_called_ = false;
    bool streaming_ = false;

private:
    bool running_ = false;
    std::string final_result_;
    TextCallback on_partial_;
    TextCallback on_final_;
};

class MockRefinementService : public IRefinementService {
public:
    Result<void> init() override { initialized_ = true; return Result<void>::ok(); }

    Result<std::string> refine(const std::vector<AudioSample>&, int) override {
        if (should_fail_) return Result<std::string>::err("refinement failed");
        return Result<std::string>::ok(refined_text_);
    }

    bool is_initialized() const override { return initialized_; }

    // Test helpers
    void set_refined_text(const std::string& text) { refined_text_ = text; }
    void set_should_fail(bool fail) { should_fail_ = fail; }

    bool initialized_ = false;

private:
    std::string refined_text_;
    bool should_fail_ = false;
};

} // namespace testing
} // namespace verbal
