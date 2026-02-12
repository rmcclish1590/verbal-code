#include "application.hpp"
#include "logger.hpp"

#include <csignal>
#include <iostream>

static verbal::Application* g_app = nullptr;

static void signal_handler(int sig) {
    (void)sig;
    if (g_app) {
        g_app->quit();
    }
}

int main(int argc, char* argv[]) {
    verbal::Logger::instance().set_level(verbal::LogLevel::INFO);

    verbal::Application app;
    g_app = &app;

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    auto result = app.init(argc, argv);
    if (result.is_err()) {
        std::cerr << "Failed to initialize: " << result.error() << "\n";
        return 1;
    }

    return app.run();
}
