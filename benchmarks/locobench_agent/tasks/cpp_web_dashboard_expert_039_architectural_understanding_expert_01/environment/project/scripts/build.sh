```bash
#!/usr/bin/env bash
# ==============================================================================
# MosaicBoard Studio – Top-Level Build Orchestrator
#
# scripts/build.sh
#
# A production-grade build script that bootstraps, configures, compiles, tests
# and packages the MosaicBoard Studio C++ project (core runtime + plugins).
# It intentionally stays dependency-light (POSIX shell + CMake + Conan) and is
# suitable for CI as well as local development.
#
# ──────────────────────────────────────────────────────────────────────────────
# FEATURES
#   • Strict error handling and verbose, colorized logging
#   • Incremental or clean builds
#   • Build type selection (Debug / Release / RelWithDebInfo / MinSizeRel)
#   • Automatic parallelism (#cores detection)
#   • Per-plugin shared library compilation
#   • Optional unit / integration test execution
#   • Version stamping & deterministic packaging
#
# USAGE
#   ./scripts/build.sh [options]
#
# OPTIONS
#   -c, --clean            Wipe previous build artefacts before building
#   -t, --type <type>      Build type (Debug, Release, RelWithDebInfo, MinSizeRel)
#   -p, --plugin <name>    Build only a specific plugin (may be specified multiple times)
#   --tests                Run unit / integration tests after build
#   --package              Create distributable package after successful build
#   -h, --help             Show this help
#
# ==============================================================================

set -euo pipefail

# ------------------------------------------------------------------------------
# Logging helpers
# ------------------------------------------------------------------------------

if [ -t 1 ]; then
    RED=$(printf '\033[31m')
    GRN=$(printf '\033[32m')
    YLW=$(printf '\033[33m')
    BLU=$(printf '\033[34m')
    MAG=$(printf '\033[35m')
    CYN=$(printf '\033[36m')
    RESET=$(printf '\033[0m')
else
    RED='' GRN='' YLW='' BLU='' MAG='' CYN='' RESET=''
fi

log()   { printf "${GRN}[INFO]${RESET} %s\n" "$*" ; }
warn()  { printf "${YLW}[WARN]${RESET} %s\n" "$*" ; }
error() { printf "${RED}[ERR] ${RESET}%s\n" "$*" ; }
die()   { error "$*" ; exit 1 ; }

# Trap unhandled errors
trap 'error "Build failed at line $LINENO"; exit 1' ERR

# ------------------------------------------------------------------------------
# Defaults & global variables
# ------------------------------------------------------------------------------

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/build"
CORE_BUILD_DIR="${BUILD_DIR}/core"
PLUGINS_DIR="${ROOT_DIR}/plugins"
BUILD_TYPE="RelWithDebInfo"
CLEAN=false
RUN_TESTS=false
PACKAGE=false
declare -a SELECTED_PLUGINS=()

# Determine parallel build jobs
if command -v nproc &>/dev/null; then
    JOBS=$(nproc)
elif [ "$(uname)" = "Darwin" ]; then
    JOBS=$(sysctl -n hw.ncpu)
else
    JOBS=4
fi

# ------------------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------------------

usage() {
    grep -E '^#   ' "${BASH_SOURCE[0]}" | sed -E 's/^#   //'
}

parse_args() {
    while (( "$#" )); do
        case "$1" in
            -c|--clean) CLEAN=true ;;
            -t|--type)
                [[ -n "${2:-}" ]] || die "Missing argument for $1"
                BUILD_TYPE="$2"; shift ;;
            -p|--plugin)
                [[ -n "${2:-}" ]] || die "Missing argument for $1"
                SELECTED_PLUGINS+=("$2"); shift ;;
            --tests)    RUN_TESTS=true ;;
            --package)  PACKAGE=true ;;
            -h|--help)  usage; exit 0 ;;
            *)          die "Unknown option: $1" ;;
        esac
        shift
    done
}

require_tools() {
    for tool in cmake conan git; do
        command -v "$tool" &>/dev/null || \
            die "Required tool '$tool' is not installed or not on PATH."
    done
}

clean_build() {
    if $CLEAN; then
        log "Cleaning previous build artefacts..."
        rm -rf "${BUILD_DIR}"
    fi
}

configure_core() {
    log "Configuring core (${BUILD_TYPE})..."
    mkdir -p "${CORE_BUILD_DIR}"
    pushd "${CORE_BUILD_DIR}" >/dev/null

    # Install / update third-party dependencies via Conan
    conan install "${ROOT_DIR}" \
        --output-folder=. \
        --build=missing \
        -s build_type="${BUILD_TYPE}" \
        -pr:h default -pr:b default

    # CMake configure
    cmake "${ROOT_DIR}" \
        -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
        -DCMAKE_TOOLCHAIN_FILE=conan_toolchain.cmake \
        -DMOSAIC_STUDIO_BUILD_PLUGINS=OFF

    popd >/dev/null
}

build_core() {
    log "Building core with ${JOBS} threads..."
    cmake --build "${CORE_BUILD_DIR}" --config "${BUILD_TYPE}" -j "${JOBS}"
}

discover_plugins() {
    local plugin_list=()
    if [ "${#SELECTED_PLUGINS[@]}" -eq 0 ]; then
        # All directories in /plugins that contain a CMakeLists.txt
        while IFS= read -r -d '' cmakelists; do
            plugin_list+=("$(dirname "$cmakelists")")
        done < <(find "${PLUGINS_DIR}" -mindepth 2 -maxdepth 2 \
                   -name CMakeLists.txt -print0)
    else
        for p in "${SELECTED_PLUGINS[@]}"; do
            local path="${PLUGINS_DIR}/${p}"
            [ -d "${path}" ] || die "Plugin not found: ${p}"
            plugin_list+=("${path}")
        done
    fi
    echo "${plugin_list[@]}"
}

configure_plugin() {
    local plugin_path="$1"
    local plugin_name
    plugin_name="$(basename "${plugin_path}")"
    local build_path="${BUILD_DIR}/plugins/${plugin_name}"

    log "Configuring plugin '${plugin_name}'..."
    mkdir -p "${build_path}"
    pushd "${build_path}" >/dev/null

    conan install "${plugin_path}" \
        --output-folder=. \
        --build=missing \
        -s build_type="${BUILD_TYPE}" \
        -pr:h default -pr:b default

    cmake "${plugin_path}" \
        -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
        -DCMAKE_TOOLCHAIN_FILE=conan_toolchain.cmake \
        -DMOSAIC_STUDIO_PLUGIN=ON

    popd >/dev/null
}

build_plugin() {
    local plugin_path="$1"
    local plugin_name
    plugin_name="$(basename "${plugin_path}")"
    local build_path="${BUILD_DIR}/plugins/${plugin_name}"

    log "Building plugin '${plugin_name}'..."
    cmake --build "${build_path}" --config "${BUILD_TYPE}" -j "${JOBS}"
}

run_tests() {
    log "Running unit / integration tests..."
    ctest --test-dir "${CORE_BUILD_DIR}" --output-on-failure --parallel "${JOBS}"
}

package_artifacts() {
    local stamp
    stamp="$(git -C "${ROOT_DIR}" rev-parse --short HEAD)"
    local archive_name="MosaicBoardStudio-${stamp}-${BUILD_TYPE}.tar.gz"

    log "Packaging build artefacts into ${archive_name}..."
    mkdir -p "${BUILD_DIR}/package"
    tar -czf "${BUILD_DIR}/package/${archive_name}" -C "${BUILD_DIR}" .

    log "Package created: ${BUILD_DIR}/package/${archive_name}"
}

# ------------------------------------------------------------------------------
# Main workflow
# ------------------------------------------------------------------------------

main() {
    parse_args "$@"
    require_tools
    clean_build

    configure_core
    build_core

    local plugins
    read -r -a plugins <<< "$(discover_plugins)"
    for plugin in "${plugins[@]}"; do
        configure_plugin "${plugin}"
        build_plugin "${plugin}"
    done

    $RUN_TESTS && run_tests
    $PACKAGE   && package_artifacts

    log "Build ✓ Completed successfully."
}

main "$@"
```