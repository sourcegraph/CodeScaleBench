```bash
#!/usr/bin/env bash
###############################################################################
# SynestheticCanvas/scripts/run_tests.sh
#
# Orchestrates the entire C test-suite for the SynestheticCanvas microservice
# constellation.  The script can:
#   • Build the test binaries (CMake)
#   • Run unit / integration tests (CTest)
#   • Generate coverage reports (lcov + genhtml)
#   • Execute memory checks (Valgrind)
#   • Watch the source tree and re-run tests automatically (entr / inotifywait)
#
# Usage:
#   ./run_tests.sh [options]
#
# Options:
#   -u | --unit            Only run tests labeled 'unit' (default: all)
#   -i | --integration     Only run tests labeled 'integration'
#   -c | --coverage        Produce an HTML coverage report
#   -m | --memcheck        Run tests under Valgrind
#   -j | --jobs <N>        Parallel build/test jobs             (default: nproc)
#   -w | --watch           Re-run tests on source change
#   -h | --help            This help message
#
# Dependencies:
#   • bash 4.x
#   • cmake >= 3.16
#   • make
#   • gcc/clang
#   • ctest (ships with CMake)
#   • lcov & genhtml      (for coverage, optional)
#   • valgrind            (for memcheck,  optional)
#   • entr or inotifywait (for watch,     optional)
###############################################################################

set -euo pipefail

################################################################################
# Utility functions                                                             #
################################################################################
die() { printf "Error: %s\n" "$*" >&2; exit 1; }

command_exists() { command -v "$1" &>/dev/null; }

usage() { grep -E "^#( |$)" "$0" | sed -E 's/^# ?//'; exit 0; }

################################################################################
# Option parsing                                                                #
################################################################################
UNIT_ONLY=0
INT_ONLY=0
COVERAGE=0
MEMCHECK=0
WATCH=0
JOBS="$(nproc 2>/dev/null || sysctl -n hw.ncpu)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -u|--unit)        UNIT_ONLY=1 ;;
        -i|--integration) INT_ONLY=1 ;;
        -c|--coverage)    COVERAGE=1 ;;
        -m|--memcheck)    MEMCHECK=1 ;;
        -w|--watch)       WATCH=1 ;;
        -j|--jobs)        shift; JOBS="$1" ;;
        -h|--help)        usage ;;
        *)                die "Unknown option: $1" ;;
    esac
    shift
done

if [[ $UNIT_ONLY -eq 1 && $INT_ONLY -eq 1 ]]; then
    die "Cannot specify both --unit and --integration"
fi

################################################################################
# Environment detection                                                         #
################################################################################
REPO_ROOT="$( cd "$( dirname "${BASH_SOURCE[0]}" )/.." && pwd )"
BUILD_DIR="${REPO_ROOT}/build-tests"
COVERAGE_DIR="${BUILD_DIR}/coverage-html"

# Required tools
for tool in cmake ctest make gcc; do
    command_exists "$tool" || die "'$tool' is required but not installed"
done

if (( COVERAGE )); then
    for tool in lcov genhtml; do
        command_exists "$tool" || die "'$tool' is required for coverage"
    done
fi

if (( MEMCHECK )); then
    command_exists valgrind || die "'valgrind' is required for memcheck"
fi

################################################################################
# Build configuration                                                           #
################################################################################
build_project() {
    local cmake_flags=(-DCMAKE_BUILD_TYPE=Debug)

    if (( COVERAGE )); then
        cmake_flags+=(
            -DCMAKE_C_FLAGS="--coverage -O0 -g"
            -DCMAKE_EXE_LINKER_FLAGS="--coverage"
        )
    fi

    mkdir -p "$BUILD_DIR"
    pushd "$BUILD_DIR" >/dev/null

    cmake "${cmake_flags[@]}" "$REPO_ROOT"
    make -j"$JOBS"

    popd >/dev/null
}

################################################################################
# Test execution                                                                #
################################################################################
run_tests() {
    local ctest_flags=(-j "$JOBS" --output-on-failure)

    if (( UNIT_ONLY )); then
        ctest_flags+=( -L "^unit$" )
    elif (( INT_ONLY )); then
        ctest_flags+=( -L "^integration$" )
    fi

    if (( MEMCHECK )); then
        ctest_flags+=( --schedule-random -T memcheck )
    fi

    pushd "$BUILD_DIR" >/dev/null
    ctest "${ctest_flags[@]}"
    popd >/dev/null
}

################################################################################
# Coverage generation                                                           #
################################################################################
generate_coverage() {
    printf "\nGenerating coverage report…\n"

    # Clean previous data
    rm -rf "$COVERAGE_DIR"
    lcov --directory "$BUILD_DIR" --zerocounters

    # Capture counters
    lcov --directory "$BUILD_DIR" --capture --output-file coverage.info
    # Remove external libraries
    lcov --remove coverage.info '/usr/*' --output-file coverage.info

    genhtml coverage.info --output-directory "$COVERAGE_DIR"
    printf "Coverage report created at %s/index.html\n\n" "$COVERAGE_DIR"
}

################################################################################
# Watcher                                                                       #
################################################################################
watch_sources_and_rerun() {
    local watcher_bin=""
    if command_exists entr; then
        watcher_bin="entr"
    elif command_exists inotifywait; then
        watcher_bin="inotifywait"
    else
        die "Neither 'entr' nor 'inotifywait' found for watch mode"
    fi

    printf "Watching source tree for changes. Press Ctrl+C to exit.\n"

    while true; do
        if [[ $watcher_bin == "entr" ]]; then
            # Rebuild file list every loop in case new source files appear
            find "$REPO_ROOT/src" "$REPO_ROOT/tests" -type f -name '*.[ch]' | \
                entr -d sh -c "build_project && run_tests"
        else
            inotifywait -e modify,create,delete -r "$REPO_ROOT"/{src,tests} \
                >/dev/null 2>&1
            build_project && run_tests
        fi
    done
}

################################################################################
# Main                                                                          #
################################################################################
main() {
    build_project
    run_tests

    (( COVERAGE )) && generate_coverage
    (( WATCH    )) && watch_sources_and_rerun
}

main
```