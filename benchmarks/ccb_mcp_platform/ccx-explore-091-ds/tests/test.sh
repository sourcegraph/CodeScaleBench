#!/bin/bash
# test.sh — Harbor compatibility wrapper
# Harbor requires tests/test.sh for task discovery (TaskPaths.is_valid() check).
# The actual evaluation logic lives in eval.sh (SWE-Factory exit-code-first pattern).

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

exec bash "$(dirname "$0")/eval.sh" "$@"
