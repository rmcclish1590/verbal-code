include(FetchContent)
include(ExternalProject)
find_package(PkgConfig REQUIRED)

# ── FetchContent dependencies (always available) ──────────────────────

# nlohmann/json
FetchContent_Declare(
    nlohmann_json
    GIT_REPOSITORY https://github.com/nlohmann/json.git
    GIT_TAG        v3.11.3
    GIT_SHALLOW    TRUE
)
set(JSON_BuildTests OFF CACHE INTERNAL "")
FetchContent_MakeAvailable(nlohmann_json)

# GoogleTest
if(BUILD_TESTS)
    FetchContent_Declare(
        googletest
        GIT_REPOSITORY https://github.com/google/googletest.git
        GIT_TAG        v1.14.0
        GIT_SHALLOW    TRUE
    )
    set(BUILD_GMOCK ON CACHE INTERNAL "")
    set(INSTALL_GTEST OFF CACHE INTERNAL "")
    FetchContent_MakeAvailable(googletest)
endif()

# whisper.cpp
if(ENABLE_WHISPER)
    FetchContent_Declare(
        whisper
        GIT_REPOSITORY https://github.com/ggerganov/whisper.cpp.git
        GIT_TAG        v1.7.3
        GIT_SHALLOW    TRUE
    )
    set(WHISPER_BUILD_TESTS OFF CACHE INTERNAL "")
    set(WHISPER_BUILD_EXAMPLES OFF CACHE INTERNAL "")
    set(BUILD_SHARED_LIBS OFF CACHE INTERNAL "")
    FetchContent_MakeAvailable(whisper)
endif()

# ── Vosk (pre-built library) ─────────────────────────────────────────

set(VOSK_VERSION "0.3.45")
set(VOSK_DIR "${CMAKE_BINARY_DIR}/_deps/vosk")

if(CMAKE_SYSTEM_PROCESSOR MATCHES "x86_64|amd64|AMD64")
    set(VOSK_ARCH "linux-x86_64")
elseif(CMAKE_SYSTEM_PROCESSOR MATCHES "aarch64|arm64")
    set(VOSK_ARCH "linux-aarch64")
else()
    message(FATAL_ERROR "Unsupported architecture for Vosk: ${CMAKE_SYSTEM_PROCESSOR}")
endif()

set(VOSK_ARCHIVE "vosk-${VOSK_ARCH}-${VOSK_VERSION}.zip")
set(VOSK_URL "https://github.com/alphacep/vosk-api/releases/download/v${VOSK_VERSION}/${VOSK_ARCHIVE}")

if(NOT EXISTS "${VOSK_DIR}/libvosk.so")
    message(STATUS "Downloading Vosk ${VOSK_VERSION} for ${VOSK_ARCH}...")
    file(DOWNLOAD
        "${VOSK_URL}"
        "${CMAKE_BINARY_DIR}/_deps/${VOSK_ARCHIVE}"
        SHOW_PROGRESS
        STATUS VOSK_DL_STATUS
    )
    list(GET VOSK_DL_STATUS 0 VOSK_DL_CODE)
    if(NOT VOSK_DL_CODE EQUAL 0)
        message(FATAL_ERROR "Failed to download Vosk: ${VOSK_DL_STATUS}")
    endif()

    file(ARCHIVE_EXTRACT
        INPUT "${CMAKE_BINARY_DIR}/_deps/${VOSK_ARCHIVE}"
        DESTINATION "${CMAKE_BINARY_DIR}/_deps"
    )
    file(RENAME
        "${CMAKE_BINARY_DIR}/_deps/vosk-${VOSK_ARCH}-${VOSK_VERSION}"
        "${VOSK_DIR}"
    )
endif()

# Create imported target for Vosk
add_library(vosk INTERFACE IMPORTED GLOBAL)
set_target_properties(vosk PROPERTIES
    INTERFACE_INCLUDE_DIRECTORIES "${VOSK_DIR}"
    INTERFACE_LINK_DIRECTORIES "${VOSK_DIR}"
    INTERFACE_LINK_LIBRARIES "-lvosk"
)

# ── System dependencies (pkg-config) ─────────────────────────────────

# PipeWire
pkg_check_modules(PIPEWIRE libpipewire-0.3)
if(PIPEWIRE_FOUND)
    message(STATUS "Found PipeWire: ${PIPEWIRE_VERSION}")
else()
    message(WARNING "PipeWire not found. Install libpipewire-0.3-dev. Audio service will not build.")
endif()

# XCB + XInput2
pkg_check_modules(XCB xcb)
pkg_check_modules(XCB_XINPUT xcb-xinput)
pkg_check_modules(XKBCOMMON xkbcommon)
pkg_check_modules(XKBCOMMON_X11 xkbcommon-x11)
if(XCB_FOUND AND XCB_XINPUT_FOUND AND XKBCOMMON_FOUND AND XKBCOMMON_X11_FOUND)
    message(STATUS "Found XCB + xkbcommon for hotkey support")
    set(HOTKEY_DEPS_FOUND TRUE)
else()
    message(WARNING "XCB/xkbcommon not fully available. Install: libxcb1-dev libxcb-xinput-dev libxkbcommon-dev libxkbcommon-x11-dev")
    set(HOTKEY_DEPS_FOUND FALSE)
endif()

# GTK3
pkg_check_modules(GTK3 gtk+-3.0)
if(GTK3_FOUND)
    message(STATUS "Found GTK3: ${GTK3_VERSION}")
else()
    message(WARNING "GTK3 not found. Install libgtk-3-dev. Overlay will not build.")
endif()

# libxdo (no .pc file on some distros, fall back to manual detection)
pkg_check_modules(XDO libxdo)
if(NOT XDO_FOUND)
    find_path(XDO_INCLUDE_DIR xdo.h)
    find_library(XDO_LIBRARY NAMES xdo)
    if(XDO_INCLUDE_DIR AND XDO_LIBRARY)
        set(XDO_FOUND TRUE)
        set(XDO_INCLUDE_DIRS ${XDO_INCLUDE_DIR})
        set(XDO_LIBRARIES ${XDO_LIBRARY})
        message(STATUS "Found libxdo (manual): ${XDO_LIBRARY}")
    else()
        message(WARNING "libxdo not found. Install libxdo-dev. Text injection will not build.")
    endif()
else()
    message(STATUS "Found libxdo: ${XDO_VERSION}")
endif()
