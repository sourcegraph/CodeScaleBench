#!/usr/bin/env bash
# ==============================================================================
#  MosaicBoard Studio – run.sh
# ------------------------------------------------------------------------------
#  A robust orchestration script for building, testing and launching the
#  MosaicBoard Studio server together with all discovered plug-in tiles.
#
#  Responsibilities:
#   1. Configure environment variables (build type, port, log level, etc.)
#   2. Verify tool-chain availability (cmake, ninja/g++, sqlite3, openssl)
#   3. Build core + plug-ins with explicit error handling
#   4. Optionally run unit / integration tests
#   5. Launch the MosaicBoard daemon with hot-reload support
#
#  Usage:
#       ./scripts/run.sh [OPTIONS]
#
#     Options:
#       -d, --debug            Build/Run in Debug mode            (default: Release)
#       -t, --with-tests       Execute unit/integration tests     (default: off)
#       -c, --clean            Perform a clean rebuild
#       -p, --port <PORT>      HTTP/WS listening port             (default: 8080)
#       -l, --log <LEVEL>      Log verbosity {trace,debug,info}   (default: info)
#       --asan                 Enable address sanitizer
#       -h, --help             Show this help message
#
# ==============================================================================

set -euo pipefail
IFS=$'\n\t'

# ---------------------------------------------------------------------- Logging
COLOR_RESET="\033[0m"
COLOR_RED="\033[0;31m"
COLOR_GREEN="\033[0;32m"
COLOR_YELLOW="\033[0;33m"
COLOR_BLUE="\033[0;34m"

log()   { printf "${COLOR_BLUE}[run.sh]${COLOR_RESET} %s\n" "$*"; }
warn()  { printf "${COLOR_YELLOW}[warn]${COLOR_RESET} %s\n" "$*" >&2; }
error() { printf "${COLOR_RED}[error]${COLOR_RESET} %s\n" "$*" >&2; exit 1; }

# ----------------------------------------------------------- Helper / Clean-ups
cleanup() {
    if [[ -n "${MBSTUDIO_PID-}" ]] && kill -0 "$MBSTUDIO_PID" 2>/dev/null; then
        warn "Stopping MosaicBoard Studio (pid: $MBSTUDIO_PID)…"
        kill "$MBSTUDIO_PID" && wait "$MBSTUDIO_PID"
    fi
}
trap cleanup EXIT INT TERM

# ----------------------------------------------------------------- CLI Parsing
BUILD_TYPE=Release
RUN_TESTS=0
CLEAN=0
PORT=8080
LOG_LEVEL=info
ENABLE_ASAN=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        -d|--debug)      BUILD_TYPE=Debug ;;
        -t|--with-tests) RUN_TESTS=1 ;;
        -c|--clean)      CLEAN=1 ;;
        -p|--port)       PORT="${2:?Missing port}" ; shift ;;
        -l|--log)        LOG_LEVEL="${2:?Missing level}" ; shift ;;
        --asan)          ENABLE_ASAN=1 ;;
        -h|--help)
            grep '^#  ' "$0" | cut -c4-
            exit 0
            ;;
        *)
            error "Unknown option: $1 (use -h for help)"
            ;;
    esac
    shift
done

# ---------------------------------------------------------------- Environment
PROJECT_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )"/.. && pwd )"
BUILD_DIR="${PROJECT_ROOT}/build/${BUILD_TYPE,,}"
PLUGINS_DIR="${PROJECT_ROOT}/plugins"
BIN_DIR="${BUILD_DIR}/bin"
DAEMON="${BIN_DIR}/mosaicboardd"

export MBSTUDIO_PORT="$PORT"
export MBSTUDIO_LOG_LEVEL="$LOG_LEVEL"
export MBSTUDIO_PLUGIN_DIR="$PLUGINS_DIR"
export LD_LIBRARY_PATH="${BIN_DIR}:${LD_LIBRARY_PATH:-}"

if [[ "$ENABLE_ASAN" -eq 1 ]]; then
    export ASAN_OPTIONS=detect_leaks=1:abort_on_error=1
fi

# ---------------------------------------------------------------- Tool-chain Check
require() {
    command -v "$1" >/dev/null 2>&1 || error "Missing dependency '$1'. Install and retry."
}
log "Validating build dependencies…"
require cmake
require g++
require ninja

# -------------------------------------------------------------- Clean Rebuild
if [[ "$CLEAN" -eq 1 ]]; then
    log "Cleaning build directory '$BUILD_DIR'…"
    rm -rf "$BUILD_DIR"
fi
mkdir -p "$BUILD_DIR"

# ---------------------------------------------------------- Configure & Build
cmake_flags=(
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE"
    -G Ninja
)

if [[ "$ENABLE_ASAN" -eq 1 ]]; then
    cmake_flags+=(
      -DENABLE_ASAN=ON
    )
fi

log "Configuring project with CMake (${cmake_flags[*]})…"
cmake -S "$PROJECT_ROOT" -B "$BUILD_DIR" "${cmake_flags[@]}"

log "Building MosaicBoard Studio core + plugins…"
cmake --build "$BUILD_DIR" --target all -j"$(nproc)" | sed "s/^/[compile] /"

# ---------------------------------------------------------- Unit / Integration Tests
if [[ "$RUN_TESTS" -eq 1 ]]; then
    log "Running unit & integration tests…"
    ctest -C "$BUILD_TYPE" --test-dir "$BUILD_DIR" --output-on-failure \
        | sed "s/^/[test] /"
fi

# ---------------------------------------------------------- Launch Daemon
if [[ ! -x "$DAEMON" ]]; then
    error "Daemon binary not found: $DAEMON"
fi

log "Starting MosaicBoard Studio on port ${COLOR_GREEN}${PORT}${COLOR_RESET}…"
"$DAEMON" &
MBSTUDIO_PID=$!
sleep 1

if ! kill -0 "$MBSTUDIO_PID" 2>/dev/null; then
    error "Failed to launch MosaicBoard Studio (see logs above)."
fi

log "MosaicBoard Studio is running with PID $MBSTUDIO_PID."
log "Press Ctrl+C to stop."

# Tail logs if external file logger is configured
if [[ -f "${BUILD_DIR}/mosaicboard.log" ]]; then
    tail -n 0 -f "${BUILD_DIR}/mosaicboard.log" &
    LOG_TAIL_PID=$!
    wait "$MBSTUDIO_PID"
    kill "$LOG_TAIL_PID" 2>/dev/null || true
else
    wait "$MBSTUDIO_PID"
fi