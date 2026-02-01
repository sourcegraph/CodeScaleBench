#!/usr/bin/env bash
# =============================================================================
# generate_docs.sh
# -----------------------------------------------------------------------------
# LexiLearn MVC Orchestrator – Documentation Generator
#
# Generates developer documentation (HTML + optional PDF) from the C source
# codebase using Doxygen, Graphviz, and LaTeX.  Designed to be CI-friendly and
# idempotent.  Run with --help for usage details.
#
# Author : LexiLearn DevOps Team
# License: MIT
# =============================================================================

set -euo pipefail

# ------------
#  Constants
# ------------
readonly SCRIPT_VERSION="1.3.0"
readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DEFAULT_BUILD_DIR="${PROJECT_ROOT}/docs/build"
readonly DEFAULT_DOXYFILE="${PROJECT_ROOT}/docs/Doxyfile"
readonly DEFAULT_LOG_FILE="${PROJECT_ROOT}/docs/build/generate_docs.log"

# ------------
#  Globals
# ------------
BUILD_DIR="${DEFAULT_BUILD_DIR}"
DOXYFILE="${DEFAULT_DOXYFILE}"
LOG_FILE="${DEFAULT_LOG_FILE}"
OPEN_AFTER=false
CLEAN=false
INIT=false
FORMAT_HTML=true
FORMAT_PDF=false

# ------------
#  Helpers
# ------------
log_info()  { echo -e "[INFO]  $*" | tee -a "${LOG_FILE}"; }
log_warn()  { echo -e "[WARN]  $*" | tee -a "${LOG_FILE}" >&2; }
log_error() { echo -e "[ERROR] $*" | tee -a "${LOG_FILE}" >&2; exit 1; }

usage() {
    cat <<EOF
LexiLearn Documentation Generator v${SCRIPT_VERSION}

Usage:
  $(basename "$0") [options]

Options:
  --html            Generate HTML docs (default: enabled)
  --pdf             Generate PDF docs (requires LaTeX) 
  --no-html         Disable HTML generation
  --no-pdf          Disable PDF generation
  --clean           Remove previous documentation build
  --open            Open generated HTML docs in default browser
  --build-dir <dir> Custom output directory (default: ${DEFAULT_BUILD_DIR})
  --doxyfile <file> Custom Doxyfile path (default: ${DEFAULT_DOXYFILE})
  --init            Generate skeleton Doxyfile then exit
  -h, --help        Show this help text and exit

Examples:
  # Generate HTML & PDF docs
  $(basename "$0") --pdf

  # Clean then regenerate docs, open in browser
  $(basename "$0") --clean --open

EOF
}

# -----------------------------------------------------------------------------
#  Dependency Checks
# -----------------------------------------------------------------------------
require_command() {
    command -v "$1" &>/dev/null || log_error "Required command '$1' not found. Aborting."
}

check_dependencies() {
    require_command "doxygen"
    if ${FORMAT_PDF}; then
        require_command "pdflatex"
        require_command "make"
    fi
    # Optional but recommended
    if ! command -v dot &>/dev/null; then
        log_warn "Graphviz 'dot' not found. Class diagrams will be skipped."
    fi
}

# -----------------------------------------------------------------------------
#  Option Parsing
# -----------------------------------------------------------------------------
while [[ $# -gt 0 ]]; do
    case "$1" in
        --html)        FORMAT_HTML=true ;;
        --pdf)         FORMAT_PDF=true ;;
        --no-html)     FORMAT_HTML=false ;;
        --no-pdf)      FORMAT_PDF=false ;;
        --clean)       CLEAN=true ;;
        --open)        OPEN_AFTER=true ;;
        --build-dir)   BUILD_DIR="$2"; shift ;;
        --doxyfile)    DOXYFILE="$2"; shift ;;
        --init)        INIT=true ;;
        -h|--help)     usage; exit 0 ;;
        *)             log_error "Unknown option: $1" ;;
    esac
    shift
done

# -----------------------------------------------------------------------------
#  Bootstrap Doxyfile
# -----------------------------------------------------------------------------
init_doxyfile() {
    if [[ -f "${DOXYFILE}" ]]; then
        log_error "Doxyfile already exists at ${DOXYFILE}. Aborting init."
    fi

    mkdir -p "$(dirname "${DOXYFILE}")"
    cat > "${DOXYFILE}" <<'DOXYCFG'
# ---------------------------------------------------------------------------
#  LexiLearn MVC Orchestrator – Doxygen Configuration
# ---------------------------------------------------------------------------
PROJECT_NAME           = "LexiLearn MVC Orchestrator"
OPTIMIZE_OUTPUT_FOR_C  = YES
EXTRACT_ALL            = YES
RECURSIVE              = YES
INPUT                  = ../src
OUTPUT_DIRECTORY       = ../docs/build
GENERATE_HTML          = YES
GENERATE_LATEX         = YES
GENERATE_TREEVIEW      = YES
HAVE_DOT               = YES
CALL_GRAPH             = YES
CALLER_GRAPH           = YES
DOT_IMAGE_FORMAT       = svg
# ---------------------------------------------------------------------------
DOXYCFG
    log_info "Skeleton Doxyfile created at ${DOXYFILE}"
    exit 0
}

# -----------------------------------------------------------------------------
#  Clean previous build
# -----------------------------------------------------------------------------
clean() {
    if [[ -d "${BUILD_DIR}" ]]; then
        log_info "Cleaning previous documentation in ${BUILD_DIR}"
        rm -rf "${BUILD_DIR}"
    else
        log_warn "No build directory found at ${BUILD_DIR} to clean."
    fi
}

# -----------------------------------------------------------------------------
#  Generate documentation
# -----------------------------------------------------------------------------
generate_docs() {
    log_info "Starting documentation generation"
    log_info "Using Doxyfile : ${DOXYFILE}"
    log_info "Output dir     : ${BUILD_DIR}"
    mkdir -p "${BUILD_DIR}"
    : > "${LOG_FILE}"   # truncate log

    # Override Doxygen options based on CLI flags
    local doxygen_flags=()
    ${FORMAT_HTML} || doxygen_flags+=( "GENERATE_HTML=NO" )
    ${FORMAT_PDF}  || doxygen_flags+=( "GENERATE_LATEX=NO" )

    if [[ "${#doxygen_flags[@]}" -gt 0 ]]; then
        log_info "Overriding Doxygen options: ${doxygen_flags[*]}"
    fi

    if ! doxygen "${DOXYFILE}" "${doxygen_flags[@]}" >> "${LOG_FILE}" 2>&1; then
        log_error "Doxygen generation failed. Check log: ${LOG_FILE}"
    fi
    log_info "Doxygen completed successfully"

    # Compile PDF if requested
    if ${FORMAT_PDF}; then
        local latex_dir="${BUILD_DIR}/latex"
        if [[ ! -d "${latex_dir}" ]]; then
            log_error "LaTeX output directory not found at ${latex_dir}"
        fi
        log_info "Building PDF (may take a while)..."
        (cd "${latex_dir}" && make -s >> "${LOG_FILE}" 2>&1)
        log_info "PDF build completed: ${latex_dir}/refman.pdf"
    fi

    # Post-generation sanity checks
    if ${FORMAT_HTML} && [[ ! -f "${BUILD_DIR}/html/index.html" ]]; then
        log_error "HTML docs missing after generation."
    fi
    log_info "Documentation successfully generated."
}

# -----------------------------------------------------------------------------
#  Open docs in default browser
# -----------------------------------------------------------------------------
open_docs() {
    local index_file="${BUILD_DIR}/html/index.html"
    if [[ ! -f "${index_file}" ]]; then
        log_error "Cannot open docs. File not found: ${index_file}"
    fi
    log_info "Opening documentation in default browser..."
    if command -v xdg-open &>/dev/null; then
        xdg-open "${index_file}" >/dev/null 2>&1 &
    elif command -v open &>/dev/null; then   # macOS
        open "${index_file}" &
    else
        log_warn "No known browser opener found; please open ${index_file} manually."
    fi
}

# -----------------------------------------------------------------------------
#  Main
# -----------------------------------------------------------------------------
main() {
    [[ "${INIT}" == true ]] && init_doxyfile
    check_dependencies
    ${CLEAN} && clean
    generate_docs
    ${OPEN_AFTER} && open_docs
    log_info "Done."
}

main "$@"

# =============================================================================
# End of file
# =============================================================================