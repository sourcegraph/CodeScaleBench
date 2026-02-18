#!/usr/bin/env bash
# Verifier for navprove-qb-url-001
# Sources the shared find_and_prove_verifier to run 2-phase majority-of-3 verification.

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

export AGENT_TEST_PATH="/workspace/regression_test.py"
export TEST_COMMAND="python3 -m pytest -c /dev/null --timeout=60"
export REFERENCE_PATCH="/tests/reference_fix.patch"
export PATCH_APPLY_DIR="/workspace"

source /tests/find_and_prove_verifier.sh
