#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Test functions defined
if grep -rq 'func Test.*Conflict\|func Test.*Transaction\|func Test.*Lock\|func Test.*Deadlock' "$WORKSPACE/pkg/kv/kvserver/concurrency/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Test functions defined"
else
    echo "FAIL: Test functions defined"
fi

# Check 2: Uses Go testing framework
if grep -rq 'testing.T\|*testing.T' "$WORKSPACE/pkg/kv/kvserver/concurrency/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Uses Go testing framework"
else
    echo "FAIL: Uses Go testing framework"
fi

# Check 3: Tests write-write conflicts
if grep -rq 'write.*conflict\|Write.*Conflict\|WriteWrite\|write-write' "$WORKSPACE/pkg/kv/kvserver/concurrency/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Tests write-write conflicts"
else
    echo "FAIL: Tests write-write conflicts"
fi

# Check 4: Tests deadlock detection
if grep -rq 'deadlock\|Deadlock\|dead_lock' "$WORKSPACE/pkg/kv/kvserver/concurrency/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Tests deadlock detection"
else
    echo "FAIL: Tests deadlock detection"
fi

# Check 5: References core types
if grep -rq 'LockTable\|ConcurrencyManager\|lockTable\|concurrencyManager' "$WORKSPACE/pkg/kv/kvserver/concurrency/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: References core types"
else
    echo "FAIL: References core types"
fi

# Check 6: Tests priority or isolation
if grep -rq 'priority\|Priority\|isolation\|Isolation' "$WORKSPACE/pkg/kv/kvserver/concurrency/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Tests priority or isolation"
else
    echo "FAIL: Tests priority or isolation"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
