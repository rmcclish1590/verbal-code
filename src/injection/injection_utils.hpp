#pragma once

#include <cstdlib>
#include <string>
#include <sys/wait.h>

namespace verbal {
namespace injection {

// Run a shell command via std::system. Returns the exit code (0 = success),
// or -1 if the process did not exit normally (signal, etc.).
inline int run_cmd(const std::string& cmd) {
    int ret = std::system(cmd.c_str());
    return WIFEXITED(ret) ? WEXITSTATUS(ret) : -1;
}

// Returns true if 'name' is found on PATH.
inline bool command_exists(const char* name) {
    std::string cmd = std::string("which ") + name + " >/dev/null 2>&1";
    return run_cmd(cmd) == 0;
}

} // namespace injection
} // namespace verbal
