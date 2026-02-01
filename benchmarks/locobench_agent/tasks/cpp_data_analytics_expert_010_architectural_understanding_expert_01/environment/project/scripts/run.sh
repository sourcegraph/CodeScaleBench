```bash
#!/usr/bin/env bash
#
# CardioInsight360 – Unified Healthcare Analytics Engine
# ------------------------------------------------------
# scripts/run.sh
#
# A production-grade orchestration script for building, testing, running and
# maintaining the monolithic C++17 binary.  The script is intentionally shipped
# with the source tree so that Clinical Engineering teams can reproduce the
# exact build pipeline on-prem, inside CI systems, or on developer laptops
# without bespoke tooling.
#
# Supported Sub-commands
#   build      – Configure & compile the project (Debug/Release)
#   start      – Launch the engine in foreground or daemonised
#   stop       – Gracefully terminate a running instance
#   status     – Verify liveness of the running instance
#   test       – Execute CTest-based unit/integration tests
#   clean      – Purge build artefacts
#   shell      – Open an interactive developer shell with env vars preset
#
# NB: Requires Bash ≥ 4.2
# ------------------------------------------------------

set -Eeuo pipefail
shopt -s inherit_errexit

# ──────────────────────────────────────────────────────────────────────────────
# Globals
# ──────────────────────────────────────────────────────────────────────────────

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly PROJECT_ROOT="${SCRIPT_DIR%/scripts}"
readonly BUILD_DIR="${PROJECT_ROOT}/build"
readonly BIN_DIR="${BUILD_DIR}/bin"
readonly ENGINE_BIN="${BIN_DIR}/cardio_insight_360"
readonly PID_FILE="${BUILD_DIR}/cardio_insight_360.pid"
readonly LOG_FILE="${BUILD_DIR}/cardio_insight_360.log"

# Default build type
BUILD_TYPE="Release"

# Colors for pretty logging
declare -rC COLORS=(
  [RED]=$'\e[31m'
  [GRN]=$'\e[32m'
  [YEL]=$'\e[33m'
  [BLU]=$'\e[34m'
  [RST]=$'\e[0m'
)

# ──────────────────────────────────────────────────────────────────────────────
# Helper Functions
# ──────────────────────────────────────────────────────────────────────────────

log()    { echo -e "${COLORS[GRN]}[CI360][INFO]${COLORS[RST]} $*"; }
warn()   { echo -e "${COLORS[YEL]}[CI360][WARN]${COLORS[RST]} $*" >&2; }
error()  { echo -e "${COLORS[RED]}[CI360][ERR ]${COLORS[RST]} $*" >&2; }
die()    { error "$*"; exit 1; }

# Ensure required executables are available on PATH
require_tools() {
  local missing=()
  for tool in "$@"; do
    command -v "$tool" &>/dev/null || missing+=("$tool")
  done
  (( ${#missing[@]} )) && die "Missing dependencies: ${missing[*]}"
}

# ──────────────────────────────────────────────────────────────────────────────
# Build Pipeline
# ──────────────────────────────────────────────────────────────────────────────

configure() {
  require_tools cmake ninja g++

  log "Configuring project ($BUILD_TYPE)…"
  cmake -S "$PROJECT_ROOT" -B "$BUILD_DIR"         \
        -G Ninja                                   \
        -DCMAKE_BUILD_TYPE="$BUILD_TYPE"           \
        -DCMAKE_EXPORT_COMPILE_COMMANDS=ON         \
        -DCI360_ENABLE_LTO=ON                      \
        -DCI360_ENABLE_SSL=ON                      \
        -DCI360_ENABLE_KAFKA=ON
}

compile() {
  log "Compiling sources…"
  cmake --build "$BUILD_DIR" --target cardio_insight_360
  log "Build finished: ${ENGINE_BIN}"
}

build() {
  mkdir -p "$BUILD_DIR"
  configure
  compile
}

clean() {
  log "Purging build artifacts…"
  rm -rf "$BUILD_DIR"
}

# ──────────────────────────────────────────────────────────────────────────────
# Runtime Management
# ──────────────────────────────────────────────────────────────────────────────

export_runtime_env() {
  export CI360_HOME="$PROJECT_ROOT"
  export LD_LIBRARY_PATH="${BIN_DIR}:${LD_LIBRARY_PATH:-}"
  export CI360_SSL_CERTS="${CI360_HOME}/certs"
  export CI360_CONFIG_DIR="${CI360_HOME}/config"
}

is_running() {
  [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" &>/dev/null
}

start() {
  [[ -x "$ENGINE_BIN" ]] || die "Executable not found. Run '${0##*/} build' first."
  is_running && die "Engine already running with PID $(cat "$PID_FILE")"

  export_runtime_env

  local mode=foreground
  if [[ "${1:-}" == "-d" ]]; then
    mode=daemon
    shift
  fi

  log "Launching CardioInsight360 (${mode})…"
  if [[ "$mode" == "daemon" ]]; then
    nohup "$ENGINE_BIN" "$@" >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    disown
    log "Daemon started (PID $(cat "$PID_FILE")). Logs: $LOG_FILE"
  else
    "$ENGINE_BIN" "$@"
  fi
}

stop() {
  is_running || die "No running instance."
  local pid
  pid="$(cat "$PID_FILE")"

  log "Stopping engine (PID $pid)…"
  kill "$pid"
  # Wait for graceful shutdown (max 15s)
  for ((i=0; i<15; ++i)); do
    is_running || { rm -f "$PID_FILE"; log "Stopped."; return; }
    sleep 1
  done

  warn "Process did not exit gracefully, forcing termination…"
  kill -9 "$pid"
  rm -f "$PID_FILE"
}

status() {
  if is_running; then
    log "Engine is running (PID $(cat "$PID_FILE"))."
  else
    log "Engine is not running."
  fi
}

tail_logs() {
  [[ -f "$LOG_FILE" ]] || die "Log file not found: $LOG_FILE"
  tail -f "$LOG_FILE"
}

# ──────────────────────────────────────────────────────────────────────────────
# Testing
# ──────────────────────────────────────────────────────────────────────────────

test_suite() {
  require_tools ctest
  [[ -d "$BUILD_DIR" ]] || die "Build directory missing. Run build first."

  log "Running test suite…"
  pushd "$BUILD_DIR" >/dev/null
  ctest --output-on-failure
  popd >/dev/null
}

# ──────────────────────────────────────────────────────────────────────────────
# Utility
# ──────────────────────────────────────────────────────────────────────────────

dev_shell() {
  export_runtime_env
  log "Spawning interactive developer shell…"
  exec "${SHELL:-/bin/bash}" -l
}

usage() {
  cat <<EOF
Usage: ${0##*/} <command> [options]

Commands:
  build [--debug]       Configure and build the project
  start [-d] [args…]    Start engine (-d daemonises)
  stop                  Stop running engine
  status                Get running status
  test                  Run CTest suite
  clean                 Remove build artifacts
  shell                 Launch dev shell with env variables set
  logs                  Tail runtime logs (daemon mode)

Options:
  --debug               Build in Debug mode instead of Release
EOF
}

# ──────────────────────────────────────────────────────────────────────────────
# Argument Parsing & Dispatch
# ──────────────────────────────────────────────────────────────────────────────

main() {
  local cmd="${1:-}"
  shift || true

  case "$cmd" in
    build)
      if [[ "${1:-}" == "--debug" ]]; then
        BUILD_TYPE="Debug"; shift
      fi
      build "$@"
      ;;
    start) start "$@" ;;
    stop)  stop ;;
    status) status ;;
    test)  test_suite ;;
    clean) clean ;;
    shell) dev_shell ;;
    logs)  tail_logs ;;
    ""|-h|--help) usage ;;
    *)
      usage
      die "Unknown command: $cmd"
      ;;
  esac
}

main "$@"
```