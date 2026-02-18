#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDLC_SUITE="ccb_design" SDLC_SUITE_LABEL="Design (Architecture & Planning)" \
    exec "$SCRIPT_DIR/sdlc_suite_2config.sh" "$@"
