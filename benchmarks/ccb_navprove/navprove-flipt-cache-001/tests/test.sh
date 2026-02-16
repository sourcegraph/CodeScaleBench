#!/usr/bin/env bash
# Verifier for navprove-flipt-cache-001
# Sources the shared find_and_prove_verifier to run 2-phase majority-of-3 verification.

export AGENT_TEST_PATH="/workspace/regression_test.go"
export TEST_COMMAND="go test -run TestRegression -v -timeout 60s"
export REFERENCE_PATCH="/tests/reference_fix.patch"
export PATCH_APPLY_DIR="/workspace"

source /tests/find_and_prove_verifier.sh
