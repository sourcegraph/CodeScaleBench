#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Security audit report exists
if [ -f "$WORKSPACE/security_audit.md" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Security audit report exists"
else
    echo "FAIL: Security audit report exists"
fi

# Check 2: Report references RGW source
if grep -q 'src/rgw' "$WORKSPACE/security_audit.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report references RGW source"
else
    echo "FAIL: Report references RGW source"
fi

# Check 3: Report covers authentication
if grep -q 'auth\|Auth\|authentication\|Authentication' "$WORKSPACE/security_audit.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report covers authentication"
else
    echo "FAIL: Report covers authentication"
fi

# Check 4: Report lists findings
if grep -q 'finding\|Finding\|vulnerability\|Vulnerability\|FINDING' "$WORKSPACE/security_audit.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report lists findings"
else
    echo "FAIL: Report lists findings"
fi

# Check 5: Report includes remediations
if grep -q 'remediation\|Remediation\|recommendation\|Recommendation\|mitigation\|Mitigation' "$WORKSPACE/security_audit.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report includes remediations"
else
    echo "FAIL: Report includes remediations"
fi

# Check 6: Report covers signature verification
if grep -q 'signature\|Signature\|signing\|Signing\|V4\|v4' "$WORKSPACE/security_audit.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Report covers signature verification"
else
    echo "FAIL: Report covers signature verification"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
