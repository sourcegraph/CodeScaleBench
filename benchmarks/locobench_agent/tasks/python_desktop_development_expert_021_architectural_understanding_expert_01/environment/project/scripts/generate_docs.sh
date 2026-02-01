#!/usr/bin/env bash
###############################################################################
# FlockDesk – Documentation Build Script
#
# This script bootstraps an isolated Python environment (unless one is already
# active), lints docstrings, auto-generates API stubs, and finally renders the
# full documentation suite (HTML, and optionally PDF).  It is designed to be
# idempotent, CI-friendly, and safe to run locally without polluting the
# workstation’s global packages.
#
# Usage:
#   ./scripts/generate_docs.sh [options]
#
# Options:
#   --watch           Re-build docs on every file change            (requires entr)
#   --pdf             Build PDF output in addition to HTML         (requires latexmk)
#   --force-clean     Remove previous build artifacts before build
#   --only-lint       Lint docstrings only, skip build steps
#   -h, --help        Show this message
#
# Environment variables:
#   DOCS_VENV_DIR     Override path to the virtualenv (default: .venv-docs)
#   CI                If set, warnings are treated as errors.
###############################################################################

set -euo pipefail

#------------------------------------------------------------------------------
# Constants & globals
#------------------------------------------------------------------------------
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCS_DIR="${PROJECT_ROOT}/docs"
BUILD_DIR="${DOCS_DIR}/_build"
API_DIR="${DOCS_DIR}/api"
PACKAGE_ROOT="${PROJECT_ROOT}/flockdesk"
DEFAULT_PYTHON_VERSION="3.11"

VENV_DIR="${DOCS_VENV_DIR:-${PROJECT_ROOT}/.venv-docs}"
PYTHON_BIN="${VENV_DIR}/bin/python"
PIP_BIN="${VENV_DIR}/bin/pip"

#------------------------------------------------------------------------------
# Helper functions
#------------------------------------------------------------------------------
msg()   { printf "\033[1;34m[docs] %s\033[0m\n" "$*"; }
warn()  { printf "\033[1;33m[docs] %s\033[0m\n" "$*"; }
error() { printf "\033[1;31m[docs] %s\033[0m\n" "$*"; exit 1; }

print_help() { grep -E '^#( Usage:|   --|-h, )' "$0" | sed 's/^#//'; }

command_exists() { command -v "$1" >/dev/null 2>&1; }

#------------------------------------------------------------------------------
# Argument parsing
#------------------------------------------------------------------------------
WATCH_MODE=false
BUILD_PDF=false
FORCE_CLEAN=false
ONLY_LINT=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --watch)       WATCH_MODE=true        ; shift ;;
        --pdf)         BUILD_PDF=true         ; shift ;;
        --force-clean) FORCE_CLEAN=true       ; shift ;;
        --only-lint)   ONLY_LINT=true         ; shift ;;
        -h|--help)     print_help             ; exit 0 ;;
        *)             error "Unknown option: $1" ;;
    esac
done

#------------------------------------------------------------------------------
# Bootstrap virtualenv
#------------------------------------------------------------------------------
ensure_venv() {
    if [[ -n "${VIRTUAL_ENV:-}" ]]; then
        # Running inside an existing virtualenv – use it directly.
        msg "Using active virtual environment: ${VIRTUAL_ENV}"
        PYTHON_BIN="python"
        PIP_BIN="pip"
        return
    fi

    if [[ ! -d "${VENV_DIR}" ]]; then
        msg "Creating documentation virtualenv at ${VENV_DIR}"
        if ! command_exists python${DEFAULT_PYTHON_VERSION}; then
            error "Python ${DEFAULT_PYTHON_VERSION} is required but not found."
        fi
        python${DEFAULT_PYTHON_VERSION} -m venv "${VENV_DIR}"
    fi

    # shellcheck disable=SC1090
    source "${VENV_DIR}/bin/activate"
}

install_requirements() {
    local req_file="${DOCS_DIR}/requirements.txt"

    if [[ ! -f "${req_file}" ]]; then
        error "Missing docs/requirements.txt. Cannot proceed."
    fi

    msg "Installing/upgrading documentation requirements…"
    "${PIP_BIN}" install --upgrade -r "${req_file}" >/dev/null
}

#------------------------------------------------------------------------------
# Lint docstrings
#------------------------------------------------------------------------------
lint_docs() {
    msg "Running docstring linting (pydocstyle & interrogate)…"

    local fail_args=()
    [[ -n "${CI:-}" ]] && fail_args+=(--fail-under=100)

    "${PYTHON_BIN}" -m pydocstyle "${PACKAGE_ROOT}"
    "${PYTHON_BIN}" -m interrogate "${PACKAGE_ROOT}" \
        -v -q \
        "${fail_args[@]}"
}

#------------------------------------------------------------------------------
# Generate Sphinx API stubs
#------------------------------------------------------------------------------
generate_api_stubs() {
    msg "Generating API reference stubs via sphinx-apidoc…"

    # Clean previous API stubs to avoid stale entries
    rm -rf "${API_DIR}"
    mkdir -p "${API_DIR}"

    "${PYTHON_BIN}" -m sphinx.apidoc \
        --module-first \
        --separate \
        --no-toc \
        --implicit-namespaces \
        -o "${API_DIR}" "${PACKAGE_ROOT}" \
        "${PACKAGE_ROOT}/tests"
}

#------------------------------------------------------------------------------
# Build documentation
#------------------------------------------------------------------------------
build_docs() {
    local sphinx_opts=( -T -b html "${DOCS_DIR}" "${BUILD_DIR}/html" )
    [[ -n "${CI:-}" ]] && sphinx_opts+=( -W --keep-going )
    [[ "${FORCE_CLEAN}" == true ]] && rm -rf "${BUILD_DIR}"

    msg "Building HTML documentation…"
    "${PYTHON_BIN}" -m sphinx "${sphinx_opts[@]}"

    if [[ "${BUILD_PDF}" == true ]]; then
        msg "Building PDF (LaTeX) documentation…"
        "${PYTHON_BIN}" -m sphinx -b latex "${DOCS_DIR}" "${BUILD_DIR}/latex"
        ( cd "${BUILD_DIR}/latex" && make LATEXMKOPTS="-interaction=nonstopmode" all-pdf )
        msg "PDF generated at ${BUILD_DIR}/latex/*.pdf"
    fi
}

#------------------------------------------------------------------------------
# Watch mode (continuous build)
#------------------------------------------------------------------------------
watch_docs() {
    if ! command_exists entr; then
        error "'entr' is required for --watch mode. Install it first."
    fi

    msg "Watching for changes – press Ctrl+C to stop."
    # Find relevant source & docs files, pipe them to entr
    find "${PACKAGE_ROOT}" "${DOCS_DIR}" \
        -type f \( -name "*.py" -o -name "*.rst" -o -name "*.md" \) \
        | entr -c "${BASH_SOURCE[0]}" --force-clean
}

#------------------------------------------------------------------------------
# Main execution
#------------------------------------------------------------------------------
main() {
    ensure_venv
    install_requirements

    lint_docs
    [[ "${ONLY_LINT}" == true ]] && exit 0

    generate_api_stubs
    build_docs
}

if [[ "${WATCH_MODE}" == true ]]; then
    watch_docs
else
    main
fi

msg "Documentation build complete."
