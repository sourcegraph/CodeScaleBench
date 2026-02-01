#!/bin/bash
# Shell wrapper for verify_grader.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/verify_grader.py" "$@"
