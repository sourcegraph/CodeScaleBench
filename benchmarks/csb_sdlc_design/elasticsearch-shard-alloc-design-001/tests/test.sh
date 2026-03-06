#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Design document exists
if [ -f "$WORKSPACE/design_doc.md" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Design document exists"
else
    echo "FAIL: Design document exists"
fi

# Check 2: Design names the new allocator
if grep -q 'PriorityShardsAllocator\|priority.*alloc' "$WORKSPACE/design_doc.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Design names the new allocator"
else
    echo "FAIL: Design names the new allocator"
fi

# Check 3: References existing allocator
if grep -q 'BalancedShardsAllocator\|ShardsAllocator' "$WORKSPACE/design_doc.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: References existing allocator"
else
    echo "FAIL: References existing allocator"
fi

# Check 4: Covers allocation deciders
if grep -q 'AllocationDecider\|decider\|Decider' "$WORKSPACE/design_doc.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers allocation deciders"
else
    echo "FAIL: Covers allocation deciders"
fi

# Check 5: Defines priority setting
if grep -q 'index.routing\|priority' "$WORKSPACE/design_doc.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Defines priority setting"
else
    echo "FAIL: Defines priority setting"
fi

# Check 6: Skeleton Java class exists
if grep -rq 'class PriorityShardsAllocator\|class.*PriorityAlloc' "$WORKSPACE/." 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Skeleton Java class exists"
else
    echo "FAIL: Skeleton Java class exists"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
