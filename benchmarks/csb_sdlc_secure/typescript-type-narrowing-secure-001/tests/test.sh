#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Security review exists
if [ -f "$WORKSPACE/security_review.md" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Security review exists"
else
    echo "FAIL: Security review exists"
fi

# Check 2: Discusses type narrowing
if grep -q 'narrowType\|narrowing\|Narrowing\|narrow' "$WORKSPACE/security_review.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Discusses type narrowing"
else
    echo "FAIL: Discusses type narrowing"
fi

# Check 3: References compiler source
if grep -q 'checker.ts\|src/compiler' "$WORKSPACE/security_review.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: References compiler source"
else
    echo "FAIL: References compiler source"
fi

# Check 4: Identifies unsoundness
if grep -q 'unsound\|Unsound\|unsafe\|bypass\|soundness' "$WORKSPACE/security_review.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Identifies unsoundness"
else
    echo "FAIL: Identifies unsoundness"
fi

# Check 5: Covers specific narrowing patterns
if grep -q 'typeof\|discriminated\|type guard\|TypeGuard' "$WORKSPACE/security_review.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers specific narrowing patterns"
else
    echo "FAIL: Covers specific narrowing patterns"
fi

# Check 6: Includes code examples
if grep -q 'example\|Example\|```' "$WORKSPACE/security_review.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Includes code examples"
else
    echo "FAIL: Includes code examples"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
