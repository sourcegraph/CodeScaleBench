```bash
#!/usr/bin/env bash
#
#  LexiLearn MVC Orchestrator – Test Runner
#
#  File:    scripts/run_tests.sh
#  Author:  LexiLearn Engineering Team
#  License: MIT
#
#  Description:
#    Comprehensive test-orchestration script for the C-based LexiLearn codebase.
#    Handles build configuration, unit/integration test execution, code-coverage
#    generation, static analysis, and memory-leak detection in a single, easily
#    consumable interface.
#
#  Usage:
#    ./scripts/run_tests.sh [options]
#
#  Options:
#    -c, --clean          Clean previous build artifacts before running
#    -v, --verbose        Verbose test output
#    -f, --filter <re>    Run only tests whose names match <re>
#    -g, --coverage       Generate gcov-/lcov-based HTML coverage report
#    -m, --memcheck       Run tests under Valgrind to check for leaks
#    -s, --static         Perform static-analysis via cppcheck + clang-tidy
#    -h, --help           Show this help message and exit
#
#  Requirements:
#    • CMake ≥ 3.15
#    • GCC/Clang with gcov/llvm-cov
#    • lcov & genhtml (for coverage)
#    • Valgrind           (if using --memcheck)
#    • cppcheck & clang-tidy (if using --static)
#
#  Notes:
#    The script is designed to be CI-friendly—non-interactive, deterministic,
#    and with non-zero exit codes on failure.
#

set -euo pipefail

#----------------------------------------------------
# Globals & Defaults
#----------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR%/scripts}"
BUILD_DIR="${PROJECT_ROOT}/build/tests"
COVERAGE_DIR="${BUILD_DIR}/coverage"
VERBOSE=false
CLEAN=false
FILTER=".*"
GENERATE_COVERAGE=false
DO_MEMCHECK=false
DO_STATIC_CHECK=false
NUM_JOBS="$(nproc || sysctl -n hw.ncpu)"
CTEST_OUTPUT_ON_FAILURE=1

#----------------------------------------------------
# Helper Functions
#----------------------------------------------------
print_usage() {
  grep '^#' "$0" | sed -e 's/^#\{1,2\}//' | sed -n '3,35p'
}

err()  { printf "❌  %s\n" "$*" >&2; }
info() { printf "ℹ️   %s\n" "$*" >&2; }
ok()   { printf "✅  %s\n" "$*" >&2; }

command_exists() {
  command -v "$1" &>/dev/null
}

trap_cleanup() {
  st=$?
  [ $st -eq 0 ] && ok "All tasks completed successfully." || err "Exited with code $st"
}
trap trap_cleanup EXIT

#----------------------------------------------------
# Argument Parsing
#----------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--clean)   CLEAN=true ;;
    -v|--verbose) VERBOSE=true ;;
    -f|--filter)
      shift
      FILTER="${1:-.*}"
      ;;
    -g|--coverage)  GENERATE_COVERAGE=true ;;
    -m|--memcheck)  DO_MEMCHECK=true ;;
    -s|--static)    DO_STATIC_CHECK=true ;;
    -h|--help)      print_usage; exit 0 ;;
    *)
      err "Unknown argument: $1"
      print_usage; exit 1
      ;;
  esac
  shift
done

export CTEST_OUTPUT_ON_FAILURE
[ "$VERBOSE" = true ] && CTEST_VERBOSE_OPTS="--verbose" || CTEST_VERBOSE_OPTS=""

#----------------------------------------------------
# Pre-flight Checks
#----------------------------------------------------
req_binaries=(cmake ctest make gcc gcov)
[ "$GENERATE_COVERAGE" = true ] && req_binaries+=(lcov genhtml)
[ "$DO_MEMCHECK" = true ] && req_binaries+=(valgrind)
[ "$DO_STATIC_CHECK" = true ] && req_binaries+=(cppcheck clang-tidy)

missing=()
for bin in "${req_binaries[@]}"; do
  command_exists "$bin" || missing+=("$bin")
done
if [ "${#missing[@]}" -ne 0 ]; then
  err "Missing required tools: ${missing[*]}"
  exit 2
fi

#----------------------------------------------------
# Clean Previous Build
#----------------------------------------------------
if [ "$CLEAN" = true ] && [ -d "$BUILD_DIR" ]; then
  info "Cleaning build directory: $BUILD_DIR"
  rm -rf "$BUILD_DIR"
fi

mkdir -p "$BUILD_DIR"
cd "$BUILD_DIR"

#----------------------------------------------------
# Configure Build (with optional coverage flags)
#----------------------------------------------------
CMAKE_OPTS="-DCMAKE_BUILD_TYPE=Debug"
if [ "$GENERATE_COVERAGE" = true ]; then
  CMAKE_OPTS+=" -DENABLE_COVERAGE=ON"
fi
info "Configuring project with CMake…"
cmake $CMAKE_OPTS -GNinja "$PROJECT_ROOT"

#----------------------------------------------------
# Build Tests
#----------------------------------------------------
info "Building tests…"
cmake --build . --target all -j"$NUM_JOBS"

#----------------------------------------------------
# Static Analysis (optional)
#----------------------------------------------------
if [ "$DO_STATIC_CHECK" = true ]; then
  info "Running static-analysis tools…"
  cppcheck --enable=all --inconclusive --quiet \
           --suppress=missingIncludeSystem \
           --project=compile_commands.json
  clang-tidy $(grep -r --include="*.c" --include="*.h" -l "" "$PROJECT_ROOT"/src) \
             -p .
  ok "Static analysis passed."
fi

#----------------------------------------------------
# Execute Tests
#----------------------------------------------------
info "Running CTest suite…"
CTEST_ARGS="--output-on-failure -j$NUM_JOBS -R $FILTER $CTEST_VERBOSE_OPTS"

if [ "$DO_MEMCHECK" = true ]; then
  CTEST_ARGS+=" -T memcheck"
  export MEMORYCHECK_COMMAND=valgrind
fi

ctest $CTEST_ARGS

#----------------------------------------------------
# Coverage Generation (optional)
#----------------------------------------------------
if [ "$GENERATE_COVERAGE" = true ]; then
  info "Generating coverage report…"
  lcov --directory . --base-directory "$PROJECT_ROOT" --capture --output-file coverage.info
  lcov --remove coverage.info '/usr/*' --output-file coverage.info
  mkdir -p "$COVERAGE_DIR"
  genhtml coverage.info --output-directory "$COVERAGE_DIR"
  ok "Coverage report generated at: $COVERAGE_DIR/index.html"
fi
```