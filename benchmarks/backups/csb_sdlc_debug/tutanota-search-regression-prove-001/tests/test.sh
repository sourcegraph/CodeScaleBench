#!/usr/bin/env bash
# Verifier for navprove-tutanota-search-001
# Sources the shared find_and_prove_verifier to run 2-phase majority-of-3 verification.


# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

export AGENT_TEST_PATH="/workspace/regression_test.test.ts"
export TEST_COMMAND="npx jest --timeout=60000"
export REFERENCE_PATCH="/tests/reference_fix.patch"
export PATCH_APPLY_DIR="/workspace"

source /tests/find_and_prove_verifier.sh
