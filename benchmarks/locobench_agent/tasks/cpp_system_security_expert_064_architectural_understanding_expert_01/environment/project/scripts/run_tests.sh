#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────────────
#  FortiLedger360 Enterprise Security Suite – Test Runner
# -----------------------------------------------------------------------------
#  File:        scripts/run_tests.sh
#  Purpose:     Build and execute all C++ unit/integration tests.  The script
#               supports several quality-gate extensions such as:
#                 • Parallel builds (make -j)
#                 • GoogleTest filter forwarding
#                 • Valgrind leak/UB sanitisation
#                 • Coverage reports (lcov + genhtml)
#
#  Usage:       ./run_tests.sh [options]
#
#  Options:
#    -h|--help            Show this help and exit
#    -c|--clean           Remove the existing build directory before building
#    -b|--build-type <t>  Build type: Debug (default) | Release | RelWithDebInfo
#    -f|--filter <expr>   GoogleTest filter expression (e.g. "Scanner*")
#    -v|--valgrind        Run the tests under Valgrind
#    --coverage           Build with coverage flags and generate an HTML report
#    --no-color           Disable ANSI color output
#
#  Environment:
#    BUILD_DIR            Override default build directory (./build)
#    MAKE_JOBS            Override job count for parallel builds
#
#  Dependencies:
#    • cmake ≥ 3.15
#    • make
#    • GoogleTest (pulled via CMake FetchContent or system-installed)
#    • Optional:
#        – Valgrind (if -v/--valgrind used)
#        – lcov & genhtml (if --coverage used)
# -----------------------------------------------------------------------------
#  Author:      FortiLedger360 Platform Team
#  License:     Proprietary – FortiLedger360
# ──────────────────────────────────────────────────────────────────────────────

set -o errexit   # Abort on non-zero exit status
set -o nounset   # Abort on unbound variable
set -o pipefail  # Abort on first error in pipeline


###############################################################################
#                               Configuration
###############################################################################

readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build}"
MAKE_JOBS_DEFAULT="$(command -v nproc &>/dev/null && nproc || sysctl -n hw.ncpu)"
MAKE_JOBS="${MAKE_JOBS:-${MAKE_JOBS_DEFAULT}}"
CMAKE_BUILD_TYPE="Debug"

GTEST_FILTER="*"
USE_VALGRIND=false
GENERATE_COVERAGE=false
COVERAGE_DIR="${BUILD_DIR}/coverage"
ENABLE_COLOR=true


###############################################################################
#                            Helper Functions
###############################################################################

function info()  { ${ENABLE_COLOR} && printf '\033[1;34m[INFO]\033[0m  %s\n'  "$*"; }
function warn()  { ${ENABLE_COLOR} && printf '\033[1;33m[WARN]\033[0m  %s\n'  "$*" || printf '[WARN]  %s\n'  "$*"; }
function error() { ${ENABLE_COLOR} && printf '\033[1;31m[ERROR]\033[0m %s\n' "$*" >&2 || printf '[ERROR] %s\n' "$*" >&2; }

function print_help() {
cat <<EOF
FortiLedger360 Test Runner

Usage:
  ./run_tests.sh [options]

Options:
  -h, --help              Show this help message and exit
  -c, --clean             Remove existing build directory before building
  -b, --build-type <t>    Build type: Debug (default) | Release | RelWithDebInfo
  -f, --filter <expr>     GoogleTest filter expression (e.g. "Scanner*")
  -v, --valgrind          Run tests under Valgrind (suppresses parallel exec)
      --coverage          Build with coverage flags & create HTML report
      --no-color          Disable colored output
EOF
}

function ensure_dependencies() {
    local missing=()
    for dep in cmake make; do
        command -v "${dep}" &>/dev/null || missing+=("${dep}")
    done

    if ${USE_VALGRIND}; then
        command -v valgrind &>/dev/null || missing+=("valgrind")
    fi

    if ${GENERATE_COVERAGE}; then
        for dep in lcov genhtml; do
            command -v "${dep}" &>/dev/null || missing+=("${dep}")
        done
    fi

    if (( ${#missing[@]} )); then
        error "Missing dependencies: ${missing[*]}"
        exit 1
    fi
}

function configure_cmake() {
    info "Configuring CMake (type=${CMAKE_BUILD_TYPE})..."
    local cmake_args=(
        -S "${ROOT_DIR}"
        -B "${BUILD_DIR}"
        -DCMAKE_BUILD_TYPE="${CMAKE_BUILD_TYPE}"
        -DENABLE_TESTING=ON
    )

    if ${GENERATE_COVERAGE}; then
        cmake_args+=(
            -DCMAKE_CXX_FLAGS="--coverage -O0"
            -DCMAKE_C_FLAGS="--coverage -O0"
        )
    fi

    cmake "${cmake_args[@]}"
}

function build_project() {
    info "Building project with ${MAKE_JOBS} parallel job(s)..."
    cmake --build "${BUILD_DIR}" --target tests -- -j "${MAKE_JOBS}"
}

function run_tests() {
    local test_binary="${BUILD_DIR}/tests/test_suite"
    if [[ ! -x "${test_binary}" ]]; then
        error "Test binary not found: ${test_binary}"
        exit 1
    fi

    info "Executing test suite (filter='${GTEST_FILTER}')..."

    local test_cmd=("${test_binary}" "--gtest_color=yes" "--gtest_filter=${GTEST_FILTER}")
    if ${USE_VALGRIND}; then
        # Use a strict valgrind setup with suppression file if present
        local supp_file="${ROOT_DIR}/scripts/valgrind.supp"
        test_cmd=(valgrind --leak-check=full --track-origins=yes --error-exitcode=1 \
                  --suppressions="${supp_file}" "${test_cmd[@]}")
    fi

    "${test_cmd[@]}"
}

function generate_coverage() {
    info "Generating coverage report..."
    mkdir -p "${COVERAGE_DIR}"

    lcov --capture \
         --directory "${BUILD_DIR}" \
         --output-file "${COVERAGE_DIR}/coverage.info" \
         --no-external

    # Remove third-party and system headers to keep numbers sane
    lcov --remove "${COVERAGE_DIR}/coverage.info" '/usr/*' '*/third_party/*' \
         --output-file "${COVERAGE_DIR}/coverage.info.cleaned"

    mv "${COVERAGE_DIR}/coverage.info.cleaned" "${COVERAGE_DIR}/coverage.info"

    genhtml "${COVERAGE_DIR}/coverage.info" \
            --output-directory "${COVERAGE_DIR}/html" \
            --title "FortiLedger360 – Coverage Report"

    info "Coverage HTML generated at ${COVERAGE_DIR}/html/index.html"
}

###############################################################################
#                               Main Routine
###############################################################################

function parse_args() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            -h|--help)        print_help; exit 0 ;;
            -c|--clean)       CLEAN_BUILD=true ;;
            -b|--build-type)  shift; CMAKE_BUILD_TYPE="${1:-Debug}" ;;
            -f|--filter)      shift; GTEST_FILTER="${1:-*}" ;;
            -v|--valgrind)    USE_VALGRIND=true; MAKE_JOBS=1 ;;  # Serialize build/tests
            --coverage)       GENERATE_COVERAGE=true ;;
            --no-color)       ENABLE_COLOR=false ;;
            *) error "Unknown argument: $1"; print_help; exit 1 ;;
        esac
        shift
    done
}

function main() {
    CLEAN_BUILD=false
    parse_args "$@"

    ensure_dependencies

    if ${CLEAN_BUILD} && [[ -d "${BUILD_DIR}" ]]; then
        info "Cleaning build directory ${BUILD_DIR}..."
        rm -rf "${BUILD_DIR}"
    fi

    configure_cmake
    build_project
    run_tests

    if ${GENERATE_COVERAGE}; then
        generate_coverage
    fi

    info "All tests completed successfully ✅"
}

main "$@"
