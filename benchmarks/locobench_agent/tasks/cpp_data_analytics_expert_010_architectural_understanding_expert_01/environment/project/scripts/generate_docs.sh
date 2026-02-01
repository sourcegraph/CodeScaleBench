```bash
#!/usr/bin/env bash
################################################################################
# CardioInsight360 – Unified Healthcare Analytics Engine
# ------------------------------------------------------------------------------
# File:        scripts/generate_docs.sh
# Description: Opinionated one-stop documentation generator for the
#              CardioInsight360 C++17 monolith. The script orchestrates Doxygen
#              (API docs), Graphviz (call graphs, class diagrams), and Pandoc
#              (Markdown => HTML/PDF) into a single versioned documentation
#              bundle ready for offline distribution or CI artifacts.
#
# Usage:       ./generate_docs.sh [--clean] [--open] [--quiet]
#
# Dependencies:
#   - doxygen   (>= 1.9.2)
#   - dot       (Graphviz, >= 2.44)
#   - pandoc    (>= 2.11, optional for PDF/HTML guides)
#
# Exit codes:
#   0  Success
#   1  Missing dependency
#   2  Doxygen failed
#   3  Pandoc failed
#   4  Unknown error
################################################################################
set -euo pipefail

# ------------------------------------------------------------------------------
# Constants
# ------------------------------------------------------------------------------
readonly PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
readonly DOCS_OUT_DIR="${PROJECT_ROOT}/.build/docs"
readonly DOXYFILE="${PROJECT_ROOT}/Doxyfile"
readonly GUIDES_DIR="${PROJECT_ROOT}/docs/guides"
readonly COLOR_RESET='\033[0m'
readonly COLOR_RED='\033[0;31m'
readonly COLOR_GREEN='\033[0;32m'
readonly COLOR_YELLOW='\033[0;33m'
readonly COLOR_CYAN='\033[0;36m'

# ------------------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------------------
log()   { printf "${COLOR_CYAN}[+] %s${COLOR_RESET}\n" "$*"; }
warn()  { printf "${COLOR_YELLOW}[!] %s${COLOR_RESET}\n" "$*" >&2; }
error() { printf "${COLOR_RED}[✖] %s${COLOR_RESET}\n" "$*" >&2; }

# Ensure we return to original directory no matter what.
trap 'cd "${PROJECT_ROOT}"' EXIT INT TERM

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Options:
  --clean        Remove previously generated docs before building
  --open         Open the generated HTML root page in \$BROWSER when done
  --quiet        Suppress non-error output (script will still exit on failure)
  -h, --help     Display this help and exit
EOF
}

# ------------------------------------------------------------------------------
# Dependency validation
# ------------------------------------------------------------------------------
require_bin() {
    local _bin="$1" _pkg="${2:-$1}"
    if ! command -v "${_bin}" >/dev/null 2>&1; then
        error "Missing dependency: ${_pkg}. Please install and retry."
        exit 1
    fi
}

validate_dependencies() {
    require_bin doxygen
    require_bin dot graphviz
    if compgen -G "${GUIDES_DIR}/*.md" > /dev/null; then
        require_bin pandoc
    fi
}

# ------------------------------------------------------------------------------
# CLI parsing
# ------------------------------------------------------------------------------
CLEAN=0 OPEN_AFTER=0 QUIET=0
while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean) CLEAN=1 ;;
        --open)  OPEN_AFTER=1 ;;
        --quiet) QUIET=1 ;;
        -h|--help) usage; exit 0 ;;
        *) error "Unknown option: $1"; usage; exit 4 ;;
    esac
    shift
done

# Quiet mode
if [[ $QUIET -eq 1 ]]; then
    exec 3>&1 4>&2   # Save fds
    exec 1>/dev/null 2>&1
fi

# ------------------------------------------------------------------------------
# Run Doxygen
# ------------------------------------------------------------------------------
run_doxygen() {
    if [[ ! -f "${DOXYFILE}" ]]; then
        warn "Doxyfile not found; generating default configuration."
        doxygen -g "${DOXYFILE}"
        sed -i.bak -e "s|OUTPUT_DIRECTORY.*|OUTPUT_DIRECTORY = ${DOCS_OUT_DIR}|g" \
                   -e "s|RECURSIVE.*|RECURSIVE = YES|g" "${DOXYFILE}"
    fi

    log "Running Doxygen..."
    if ! doxygen "${DOXYFILE}"; then
        error "Doxygen generation failed."
        exit 2
    fi
    log "Doxygen finished. Output: ${DOCS_OUT_DIR}/html/index.html"
}

# ------------------------------------------------------------------------------
# Build supplementary guides (Markdown => HTML/PDF via Pandoc)
# ------------------------------------------------------------------------------
process_guides() {
    shopt -s nullglob
    local _md_files=("${GUIDES_DIR}"/*.md)
    if [[ ${#_md_files[@]} -eq 0 ]]; then
        return 0
    fi

    log "Generating user guides via Pandoc..."
    mkdir -p "${DOCS_OUT_DIR}/guides"
    for md in "${_md_files[@]}"; do
        local base
        base="$(basename "${md}" .md)"
        if ! pandoc "${md}" -s -o "${DOCS_OUT_DIR}/guides/${base}.html"; then
            error "Pandoc failed for ${md}"
            exit 3
        fi
    done
    log "Guides generated at ${DOCS_OUT_DIR}/guides/"
}

# ------------------------------------------------------------------------------
# Clean docs directory if required
# ------------------------------------------------------------------------------
if [[ $CLEAN -eq 1 ]]; then
    log "Cleaning previously generated docs ..."
    rm -rf "${DOCS_OUT_DIR}"
fi

# ------------------------------------------------------------------------------
# Main
# ------------------------------------------------------------------------------
log "📚 CardioInsight360 Documentation Generator"
validate_dependencies
run_doxygen
process_guides

log "✅ Documentation build completed successfully."

# Restore output if quiet mode was on
if [[ $QUIET -eq 1 ]]; then
    exec 1>&3 2>&4
fi

# ------------------------------------------------------------------------------
# Open browser if requested and available
# ------------------------------------------------------------------------------
if [[ $OPEN_AFTER -eq 1 ]]; then
    local index_html="${DOCS_OUT_DIR}/html/index.html"
    if [[ -f "${index_html}" ]]; then
        log "Opening documentation in default browser ..."
        if command -v xdg-open >/dev/null 2>&1; then
            xdg-open "${index_html}" &
        elif command -v open >/dev/null 2>&1; then  # macOS
            open "${index_html}" &
        else
            warn "Could not detect a suitable 'open' command."
        fi
    else
        warn "Index file not found at ${index_html}"
    fi
fi

exit 0
```