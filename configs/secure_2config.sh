#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SDLC_SUITE="ccb_secure" SDLC_SUITE_LABEL="Secure (Security & Compliance)" \
    exec "$SCRIPT_DIR/sdlc_suite_2config.sh" "$@"
