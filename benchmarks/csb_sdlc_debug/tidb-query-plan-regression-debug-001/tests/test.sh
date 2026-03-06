#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Debug report exists
if [ -f "$WORKSPACE/debug_report.md" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Debug report exists"
else
    echo "FAIL: Debug report exists"
fi

# Check 2: Report mentions IndexScan
if grep -q 'IndexScan\|indexScan\|IndexLookUp' "$WORKSPACE/debug_report.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report mentions IndexScan"
else
    echo "FAIL: Report mentions IndexScan"
fi

# Check 3: Report mentions TableFullScan
if grep -q 'TableFullScan\|tableScan\|TableScan' "$WORKSPACE/debug_report.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report mentions TableFullScan"
else
    echo "FAIL: Report mentions TableFullScan"
fi

# Check 4: Report discusses cost model
if grep -q 'cost\|Cost' "$WORKSPACE/debug_report.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report discusses cost model"
else
    echo "FAIL: Report discusses cost model"
fi

# Check 5: Report references planner package
if grep -q 'pkg/planner' "$WORKSPACE/debug_report.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report references planner package"
else
    echo "FAIL: Report references planner package"
fi

# Check 6: Report includes hypothesis
if grep -q 'hypothesis\|Hypothesis\|cause\|Cause\|regression\|Regression' "$WORKSPACE/debug_report.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report includes hypothesis"
else
    echo "FAIL: Report includes hypothesis"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
