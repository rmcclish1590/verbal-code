add_library(verbal_core
    config.cpp
    logger.cpp
)

target_include_directories(verbal_core PUBLIC ${CMAKE_CURRENT_SOURCE_DIR})
target_link_libraries(verbal_core PUBLIC nlohmann_json::nlohmann_json)
