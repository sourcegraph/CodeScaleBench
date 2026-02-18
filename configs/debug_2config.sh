#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDLC_SUITE="ccb_debug" SDLC_SUITE_LABEL="Debug (Investigation & Root Cause)" \
    exec "$SCRIPT_DIR/sdlc_suite_2config.sh" "$@"
