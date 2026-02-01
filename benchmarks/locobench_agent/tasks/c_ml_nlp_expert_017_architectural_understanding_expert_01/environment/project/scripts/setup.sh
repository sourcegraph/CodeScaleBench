```bash
#!/usr/bin/env bash
###############################################################################
#  LexiLearn MVC Orchestrator - Environment Setup
#
#  File:    scripts/setup.sh
#  Project: LexiLearn MVC Orchestrator (ml_nlp)
#  Author:  LexiLearn Engineering <eng@lexilearn.ai>
#  License: Apache-2.0
#
#  Description:
#    This script bootstraps the development / CI / production environment for
#    the C-based LexiLearn Orchestrator.  It installs required system packages,
#    verifies compiler toolchains, configures optional acceleration back-ends
#    (OpenMP, CUDA), and performs an out-of-tree build of the C source tree.
#
#  Usage:
#    ./scripts/setup.sh [OPTIONS]
#
#  Options:
#    -p, --prefix <path>       Installation prefix           (default: /usr/local)
#    -b, --build-type <type>   Build type {Debug|Release}    (default: Release)
#    -j, --jobs <n>            Parallel build jobs           (default: nproc)
#    --with-cuda               Enable CUDA acceleration      (default: OFF)
#    --with-openblas           Use OpenBLAS instead of BLAS  (default: OFF)
#    -h, --help                Show this help message and exit
#
###############################################################################

set -Eeuo pipefail

#------------------------------------------------------------------------------
# Colorized log helpers
#------------------------------------------------------------------------------
_color() { [[ -t 1 ]] && printf "\e[%sm%s\e[0m\n" "$1" "$2" || printf "%s\n" "$2"; }
info()    { _color "32" "ℹ︎  $*"; }
warn()    { _color "33" "⚠  $*"; }
error()   { _color "31" "✖  $*" >&2; }
die()     { error "$*"; exit 1; }

#------------------------------------------------------------------------------
# Global defaults
#------------------------------------------------------------------------------
PREFIX="/usr/local"
BUILD_TYPE="Release"
JOBS="$(nproc || sysctl -n hw.ncpu || echo 4)"
ENABLE_CUDA="OFF"
ENABLE_OPENBLAS="OFF"

#------------------------------------------------------------------------------
# Usage
#------------------------------------------------------------------------------
usage() {
  grep -E '^#  ' "${BASH_SOURCE[0]}" | cut -c4-
  exit 0
}

#------------------------------------------------------------------------------
# Parse CLI arguments
#------------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--prefix)       PREFIX="$2"; shift 2 ;;
    -b|--build-type)   BUILD_TYPE="$2"; shift 2 ;;
    -j|--jobs)         JOBS="$2"; shift 2 ;;
    --with-cuda)       ENABLE_CUDA="ON"; shift ;;
    --with-openblas)   ENABLE_OPENBLAS="ON"; shift ;;
    -h|--help)         usage ;;
    *) die "Unknown argument: $1. Use --help for usage."; ;;
  esac
done

#------------------------------------------------------------------------------
# Detect OS distribution
#------------------------------------------------------------------------------
detect_distro() {
  if [[ -f /etc/os-release ]]; then
    source /etc/os-release
    echo "${ID}"
  elif command -v sw_vers >/dev/null 2>&1; then
    echo "macos"
  else
    echo "unknown"
  fi
}

DISTRO="$(detect_distro)"
info "Detected distribution: ${DISTRO}"

#------------------------------------------------------------------------------
# Check for required tools
#------------------------------------------------------------------------------
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Required command '$1' not found."
}

require_cmd cmake
require_cmd git

#------------------------------------------------------------------------------
# Verify GCC/Clang version
#------------------------------------------------------------------------------
check_compiler() {
  local cc cver major
  cc=$(command -v gcc || command -v clang || true)
  [[ -z "${cc}" ]] && die "No C compiler found. Please install GCC or Clang."

  cver="$("${cc}" -dumpversion 2>/dev/null || "${cc}" --version | head -n1)"
  major="${cver%%.*}"
  if [[ "${cc}" =~ gcc && "${major}" -lt 9 ]]; then
    die "GCC ≥ 9 required. Found: ${cver}"
  fi
  info "Using compiler: ${cc} (${cver})"
}
check_compiler

#------------------------------------------------------------------------------
# Install system packages (root privileges may be required)
#------------------------------------------------------------------------------
install_packages() {
  case "${DISTRO}" in
    ubuntu|debian)
      sudo apt-get update -y
      sudo apt-get install -y build-essential cmake pkg-config \
        libssl-dev libcurl4-openssl-dev zlib1g-dev uuid-dev \
        ${ENABLE_OPENBLAS:+libopenblas-dev}
      ;;
    fedora|centos|rhel)
      sudo dnf install -y gcc gcc-c++ make cmake openssl-devel \
        libcurl-devel zlib-devel libuuid-devel \
        ${ENABLE_OPENBLAS:+openblas-devel}
      ;;
    arch)
      sudo pacman -Sy --noconfirm base-devel cmake openssl \
        curl zlib libuuid \
        ${ENABLE_OPENBLAS:+openblas}
      ;;
    macos)
      if ! command -v brew >/dev/null 2>&1; then
        die "Homebrew not found. Install from https://brew.sh/"
      fi
      brew update
      brew install cmake openssl curl zlib libuuid \
        ${ENABLE_OPENBLAS:+openblas}
      ;;
    *)
      warn "Automatic dependency installation not supported for '${DISTRO}'."
      ;;
  esac
}
info "Installing system packages..."
install_packages

#------------------------------------------------------------------------------
# CUDA detection / validation
#------------------------------------------------------------------------------
validate_cuda() {
  if [[ "${ENABLE_CUDA}" == "ON" ]]; then
    if command -v nvcc >/dev/null 2>&1; then
      local cuda_ver
      cuda_ver="$(nvcc --version | grep -o "release [0-9]\+\.[0-9]\+" | awk '{print $2}')"
      info "CUDA detected (nvcc ${cuda_ver})"
    else
      die "--with-cuda specified but 'nvcc' not found in PATH."
    fi
  fi
}
validate_cuda

#------------------------------------------------------------------------------
# Prepare build directory
#------------------------------------------------------------------------------
BUILD_DIR="build/${BUILD_TYPE,,}"
info "Configuring out-of-source build in '${BUILD_DIR}' ..."
mkdir -p "${BUILD_DIR}"
pushd "${BUILD_DIR}" >/dev/null

#------------------------------------------------------------------------------
# Run CMake configuration
#------------------------------------------------------------------------------
cmake_opts=(
  -DCMAKE_BUILD_TYPE="${BUILD_TYPE}"
  -DCMAKE_INSTALL_PREFIX="${PREFIX}"
  -DENABLE_CUDA="${ENABLE_CUDA}"
  -DENABLE_OPENBLAS="${ENABLE_OPENBLAS}"
)

info "Running CMake ..."
cmake "${cmake_opts[@]}" ../.. || die "CMake configuration failed."

#------------------------------------------------------------------------------
# Build & install
#------------------------------------------------------------------------------
info "Building (jobs=${JOBS}) ..."
cmake --build . -- -j"${JOBS}" || die "Build failed."

info "Installing to '${PREFIX}' ..."
sudo cmake --install . || die "Installation failed."

popd >/dev/null
info "LexiLearn Orchestrator setup complete 🎉"
```