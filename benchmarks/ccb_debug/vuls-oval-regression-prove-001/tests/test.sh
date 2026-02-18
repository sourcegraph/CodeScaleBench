#!/usr/bin/env bash
# Verifier for navprove-vuls-oval-001
# Sources the shared find_and_prove_verifier to run 2-phase majority-of-3 verification.


# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

export AGENT_TEST_PATH="/workspace/regression_test.go"
export TEST_COMMAND="go test -run TestRegression -v -timeout 60s"
export REFERENCE_PATCH="/tests/reference_fix.patch"
export PATCH_APPLY_DIR="/workspace"

source /tests/find_and_prove_verifier.sh
