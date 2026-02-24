#!/bin/bash
# test.sh — Dual-mode verifier dispatcher
# Artifact mode (.artifact_only_mode exists): run eval.sh (oracle scoring)
# Direct mode  (default / .sg_only_mode):    run direct_verifier.sh

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

if [ -f /tmp/.artifact_only_mode ]; then
    echo "[test.sh] Artifact mode detected -> running eval.sh (oracle verifier)"
    exec bash "$(dirname "$0")/eval.sh" "$@"
else
    echo "[test.sh] Direct mode -> running direct_verifier.sh"
    exec bash "$(dirname "$0")/direct_verifier.sh" "$@"
fi
