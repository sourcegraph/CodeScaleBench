#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDLC_SUITE="ccb_build" SDLC_SUITE_LABEL="Build (Implementation & Refactoring)" \
    exec "$SCRIPT_DIR/sdlc_suite_2config.sh" "$@"
