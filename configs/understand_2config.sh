#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDLC_SUITE="ccb_understand" SDLC_SUITE_LABEL="Understand (Requirements & Discovery)" \
    exec "$SCRIPT_DIR/sdlc_suite_2config.sh" "$@"
