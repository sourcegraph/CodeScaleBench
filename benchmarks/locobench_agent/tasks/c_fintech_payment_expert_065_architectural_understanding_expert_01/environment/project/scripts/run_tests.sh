```bash
#!/usr/bin/env bash
###############################################################################
# EduPay Ledger Academy – Test Runner
#
# File:    scripts/run_tests.sh
# Purpose: One-stop utility that compiles, executes, and reports on the C test
#          suite for the EduPay Ledger Academy codebase.  It is designed to run
#          identically on macOS, Linux, and CI containers (GitHub Actions,
#          GitLab CI, Jenkins, etc.).  In addition to mere execution, the
#          script can:
#
#            • produce code-coverage artifacts (HTML + Cobertura XML);
#            • run the tests under Valgrind to catch memory issues;
#            • perform static analysis with clang-tidy or cppcheck;
#            • export a JUnit XML report for CI dashboards.
#
# Usage:
#          ./scripts/run_tests.sh [options]
#
# Options:
#          -b, --build         Compile the entire project (default action)
#          -t, --tests FILE    Run a single test executable or pattern
#          -C, --coverage      Generate code-coverage report (requires gcov/lcov)
#          -v, --valgrind      Execute tests under Valgrind memcheck
#          -s, --static        Run static analysis (clang-tidy/cppcheck)
#          -o, --out DIR       Directory where build + reports are generated
#          -h, --help          Show help and exit
#
# Exit codes:
#          0  – all tests passed
#          1  – usage / parameter error
#          2  – compilation failure
#          3  – test failure
#          4  – coverage or analysis failure
#
# Author:  EduPay Ledger Academy Core Team
# License: Apache-2.0
###############################################################################

set -euo pipefail

###############################################################################
# Globals
###############################################################################
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${PROJECT_ROOT}/build"
REPORT_DIR="${BUILD_DIR}/reports"
COVERAGE_DIR="${REPORT_DIR}/coverage"
JUNIT_FILE="${REPORT_DIR}/junit.xml"
CTEST_ARGS=()
VALGRIND_ENABLED=0
COVERAGE_ENABLED=0
STATIC_ANALYSIS=0
TEST_PATTERN=""

###############################################################################
# Logging helpers
###############################################################################
log()    { printf '[\033[0;32mINFO\033[0m]  %s\n' "$*"; }
warn()   { printf '[\033[0;33mWARN\033[0m]  %s\n' "$*" >&2; }
error()  { printf '[\033[0;31mERROR\033[0m] %s\n' "$*" >&2; exit 1; }

###############################################################################
# Usage
###############################################################################
usage() {
    grep -E '^#( |$)' "$0" | cut -c 4-
    exit "${1:-0}"
}

###############################################################################
# Dependency checks
###############################################################################
require_tool() {
    if ! command -v "$1" >/dev/null 2>&1 ; then
        error "Required tool '$1' not found in PATH."
    fi
}

check_dependencies() {
    require_tool "cmake"
    require_tool "ctest"
    if (( VALGRIND_ENABLED )); then
        require_tool "valgrind"
    fi
    if (( COVERAGE_ENABLED )); then
        require_tool "lcov"
        require_tool "genhtml"
    fi
    if (( STATIC_ANALYSIS )); then
        if command -v clang-tidy >/dev/null 2>&1 ; then
            ANALYZER="clang-tidy"
        elif command -v cppcheck >/dev/null 2>&1 ; then
            ANALYZER="cppcheck"
        else
            error "Static analysis requested but neither 'clang-tidy' nor 'cppcheck' is available."
        fi
    fi
}

###############################################################################
# CLI argument parsing
###############################################################################
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--build)           ;; # default action
        -t|--tests)           TEST_PATTERN="$2"; shift ;;
        -C|--coverage)        COVERAGE_ENABLED=1 ;;
        -v|--valgrind)        VALGRIND_ENABLED=1 ;;
        -s|--static)          STATIC_ANALYSIS=1 ;;
        -o|--out)             BUILD_DIR="$(realpath "$2")"; shift ;;
        -h|--help)            usage 0 ;;
        *)                    warn "Unknown argument: $1"; usage 1 ;;
    esac
    shift
done

###############################################################################
# Build step
###############################################################################
configure_and_build() {
    log "Creating build directory at ${BUILD_DIR}"
    mkdir -p "${BUILD_DIR}" "${REPORT_DIR}"

    cmake_flags=(
        -DCMAKE_BUILD_TYPE=Debug
        "-DEDUPAY_COVERAGE=${COVERAGE_ENABLED}"
        "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON"
    )

    log "Configuring project with CMake"
    cmake -S "${PROJECT_ROOT}" -B "${BUILD_DIR}" "${cmake_flags[@]}"

    log "Building all targets"
    cmake --build "${BUILD_DIR}" -- -j"$(nproc)"
}

###############################################################################
# Static analysis
###############################################################################
run_static_analysis() {
    [[ -f "${BUILD_DIR}/compile_commands.json" ]] || error "compile_commands.json not found; ensure CMAKE_EXPORT_COMPILE_COMMANDS is ON."
    log "Executing static analysis via ${ANALYZER}"

    case "${ANALYZER}" in
        clang-tidy)
            clang-tidy -p "${BUILD_DIR}" $(jq -r '.[].file' "${BUILD_DIR}/compile_commands.json") || warn "clang-tidy found issues."
            ;;
        cppcheck)
            cppcheck --enable=all --project="${BUILD_DIR}/compile_commands.json" --inconclusive --xml 2>"${REPORT_DIR}/cppcheck.xml" || true
            ;;
    esac
}

###############################################################################
# Test execution
###############################################################################
run_tests() {
    log "Running unit/integration tests"
    local ctest_flags=(-T test --output-on-failure --no-compress-output)

    if [[ -n ${TEST_PATTERN} ]]; then
        ctest_flags+=( -R "${TEST_PATTERN}" )
    fi
    if (( VALGRIND_ENABLED )); then
        export CTEST_MEMORYCHECK_COMMAND=valgrind
        export CTEST_MEMORYCHECK_COMMAND_OPTIONS="--leak-check=full --error-exitcode=1"
        ctest_flags=( -T memcheck "${ctest_flags[@]}" )
    fi
    ctest_flags+=( --output-junit "${JUNIT_FILE}" )

    pushd "${BUILD_DIR}" >/dev/null
    set +e
    ctest "${ctest_flags[@]}"
    local test_rc=$?
    set -e
    popd >/dev/null

    if (( test_rc != 0 )); then
        error "Test suite failed (exit code ${test_rc})"
    fi
    log "All tests passed"
}

###############################################################################
# Coverage report
###############################################################################
generate_coverage() {
    log "Collecting code coverage data"
    lcov --directory "${BUILD_DIR}" --capture --output-file "${COVERAGE_DIR}/coverage.info"
    lcov --remove "${COVERAGE_DIR}/coverage.info" '/usr/*' '*/third_party/*' --output-file "${COVERAGE_DIR}/coverage.info"
    genhtml "${COVERAGE_DIR}/coverage.info" --output-directory "${COVERAGE_DIR}/html"
    log "Coverage report generated at ${COVERAGE_DIR}/html/index.html"
}

###############################################################################
# Main
###############################################################################
main() {
    check_dependencies
    configure_and_build

    if (( STATIC_ANALYSIS )); then
        run_static_analysis
    fi

    run_tests

    if (( COVERAGE_ENABLED )); then
        generate_coverage
    fi

    log "Test run completed successfully."
}

main "$@"
```