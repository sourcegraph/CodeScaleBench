#!/usr/bin/env bash
#===============================================================================
# EduPay Ledger Academy – Unified Build Script
#
# File:        scripts/build.sh
# Language:    POSIX shell (bash v4+)
# Synopsis:    One-stop shop for configuring, building, testing, and packaging
#              the EduPay Ledger Academy (fintech_payment) code-base.
#
# Rationale:
#   • Keeps newcomers from fighting C/C++ tool-chains on day 1 of coursework.
#   • Encapsulates best-practice flags for security-hardened fintech binaries.
#   • Easily extended by professors to demonstrate CI/CD pipelines in class.
#
# Supported targets:
#   all        – Default; same as ‘configure’ + ‘compile’.
#   configure  – Generate build system with CMake.
#   compile    – Build sources with Ninja/Make.
#   test       – Run fast unit tests (ctest).
#   coverage   – Compile with gcov/llvm-cov and emit HTML reports.
#   tidy       – Run clang-tidy static analysis.
#   clean      – Remove build artifacts.
#   dist       – Produce installable tarball (.tar.gz).
#   help       – Print usage.
#
# Exit codes comply with sysexits(3) where applicable.
#===============================================================================

set -euo pipefail
IFS=$'\n\t'

#---------------------------------- Globals -----------------------------------
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${PROJECT_ROOT}/_build"
INSTALL_DIR="${PROJECT_ROOT}/_install"
LOG_FILE="${BUILD_DIR}/build.log"
CMAKE_TOOLCHAIN_FILE="${PROJECT_ROOT}/cmake/toolchains/strict.cmake"
C_COMPILER_DEFAULT="gcc"
C_COMPILER_CLANG="clang"

#---------------------------------- Logging -----------------------------------
TIMESTAMP() { date +"%Y-%m-%dT%H:%M:%S%z"; }

log() {
  local level="$1"; shift
  local msg="$*"
  local color_reset="\033[0m"
  local color_red="\033[31m"
  local color_green="\033[32m"
  local color_yellow="\033[33m"
  local prefix

  case "${level}" in
    INFO)    prefix="${color_green}[INFO]${color_reset}";;
    WARN)    prefix="${color_yellow}[WARN]${color_reset}";;
    ERROR)   prefix="${color_red}[ERR ]${color_reset}";;
    *)       prefix="[???]";;
  esac

  echo -e "$(TIMESTAMP) ${prefix} ${msg}" | tee -a "${LOG_FILE}"
}

die() {
  log ERROR "$*"
  exit 70             # EX_SOFTWARE
}

#------------------------------- Requirements ----------------------------------
require_program() {
  command -v "$1" >/dev/null 2>&1 || die "Missing dependency: '$1' not found in \$PATH"
}

check_requirements() {
  log INFO "Checking host build requirements…"
  require_program cmake
  require_program make
  require_program pkg-config
  require_program "${C_COMPILER_DEFAULT}"
  # Optional tools
  if command -v ninja >/dev/null 2>&1; then
    export CMAKE_GENERATOR="Ninja"
  else
    export CMAKE_GENERATOR="Unix Makefiles"
  fi
  log INFO "All critical build tools detected."
}

#---------------------------- Argument Parsing ---------------------------------
ACTION="all"
BUILD_TYPE="RelWithDebInfo"
RUN_TESTS=false
RUN_TIDY=false
GENERATE_COVERAGE=false
DIST_PACKAGE=false

usage() {
  sed -rn 's/^# ?//p' "$0" | grep -E "Supported targets:" -A1000
  echo ""
  echo "Examples:"
  echo "  $0 compile                 # Basic compile"
  echo "  $0 coverage                # Build with coverage instrumentation"
  echo "  $0 tidy compile            # Static analysis + compile"
  echo ""
}

parse_args() {
  if [[ $# -eq 0 ]]; then
    return
  fi

  while [[ $# -gt 0 ]]; do
    case "$1" in
      configure|compile|clean|test|coverage|tidy|dist|all)
        ACTION="$1"
        ;;
      --debug)
        BUILD_TYPE="Debug"
        ;;
      --release)
        BUILD_TYPE="Release"
        ;;
      --compiler=*)
        export CC="${1#*=}"
        ;;
      -h|--help|help)
        usage
        exit 64           # EX_USAGE
        ;;
      *)
        die "Unknown option/target: $1"
        ;;
    esac
    shift
  done

  if [[ "${ACTION}" == "coverage" ]]; then
    GENERATE_COVERAGE=true
  fi

  if [[ "${ACTION}" == "tidy" ]]; then
    RUN_TIDY=true
    ACTION="compile"
  fi

  if [[ "${ACTION}" == "test" ]]; then
    RUN_TESTS=true
    ACTION="compile"
  fi

  if [[ "${ACTION}" == "dist" ]]; then
    DIST_PACKAGE=true
    ACTION="compile"
  fi
}

#----------------------------- Core Operations ---------------------------------
configure() {
  log INFO "Configuring build system (${BUILD_TYPE})…"
  mkdir -p "${BUILD_DIR}"
  cmake -S "${PROJECT_ROOT}" \
        -B "${BUILD_DIR}"     \
        -G "${CMAKE_GENERATOR}" \
        -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
        -DCMAKE_INSTALL_PREFIX="${INSTALL_DIR}" \
        -DCMAKE_TOOLCHAIN_FILE="${CMAKE_TOOLCHAIN_FILE}" \
        -DENABLE_COVERAGE="${GENERATE_COVERAGE}" \
        2>&1 | tee -a "${LOG_FILE}"
}

compile() {
  log INFO "Compiling sources…"
  cmake --build "${BUILD_DIR}" --parallel "$(nproc)" 2>&1 | tee -a "${LOG_FILE}"
}

run_tests() {
  log INFO "Running unit tests…"
  ctest --test-dir "${BUILD_DIR}" --output-on-failure 2>&1 | tee -a "${LOG_FILE}"
}

coverage() {
  log INFO "Generating coverage reports…"
  lcov --directory "${BUILD_DIR}" --capture --output-file "${BUILD_DIR}/coverage.info"
  lcov --remove "${BUILD_DIR}/coverage.info" '/usr/*' --output-file "${BUILD_DIR}/coverage.info"
  genhtml "${BUILD_DIR}/coverage.info" --output-directory "${BUILD_DIR}/coverage"
  log INFO "Coverage report available at ${BUILD_DIR}/coverage/index.html"
}

tidy() {
  log INFO "Running clang-tidy static analysis…"
  require_program clang-tidy
  (cd "${BUILD_DIR}" && \
   cmake --build . --target tidy 2>&1 | tee -a "${LOG_FILE}")
}

package_dist() {
  log INFO "Creating distribution tarball…"
  cmake --install "${BUILD_DIR}"
  tar -czf "${PROJECT_ROOT}/EduPayLedgerAcademy-$(date +%Y%m%d).tar.gz" -C "${INSTALL_DIR}" .
  log INFO "Distribution package created."
}

clean() {
  log INFO "Cleaning build artifacts…"
  rm -rf "${BUILD_DIR}" "${INSTALL_DIR}"
  log INFO "Clean complete."
}

#---------------------------------- Driver -------------------------------------
main() {
  parse_args "$@"
  mkdir -p "$(dirname "${LOG_FILE}")"
  echo "" > "${LOG_FILE}"   # truncate previous log

  check_requirements

  case "${ACTION}" in
    clean)
      clean
      ;;
    configure)
      configure
      ;;
    compile|all)
      configure
      compile
      ;;
    *)
      die "Unsupported action '${ACTION}' – internal error."
      ;;
  esac

  [[ "${RUN_TIDY}" == true        ]] && tidy
  [[ "${RUN_TESTS}" == true       ]] && run_tests
  [[ "${GENERATE_COVERAGE}" == true ]] && coverage
  [[ "${DIST_PACKAGE}" == true    ]] && package_dist

  log INFO "Build script completed successfully."
}

main "$@"

#--------------------------------- Epilogue ------------------------------------
# End of file – keep learning, keep shipping 🚀
