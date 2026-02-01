#!/bin/bash
# Shell wrapper for import_tac_tasks.py

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$SCRIPT_DIR/import_tac_tasks.py" "$@"
