#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: API doc file exists
if [ -f "$WORKSPACE/docs/api_channel_creation.md" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: API doc file exists"
else
    echo "FAIL: API doc file exists"
fi

# Check 2: Documents CreateChannel
if grep -q 'CreateChannel' "$WORKSPACE/docs/api_channel_creation.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Documents CreateChannel"
else
    echo "FAIL: Documents CreateChannel"
fi

# Check 3: Documents CreateCustomChannel
if grep -q 'CreateCustomChannel\|CustomChannel' "$WORKSPACE/docs/api_channel_creation.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Documents CreateCustomChannel"
else
    echo "FAIL: Documents CreateCustomChannel"
fi

# Check 4: Covers credentials
if grep -q 'ChannelCredentials\|credentials' "$WORKSPACE/docs/api_channel_creation.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers credentials"
else
    echo "FAIL: Covers credentials"
fi

# Check 5: Covers credential types
if grep -q 'InsecureChannelCredentials\|SslCredentials\|insecure\|ssl\|SSL' "$WORKSPACE/docs/api_channel_creation.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers credential types"
else
    echo "FAIL: Covers credential types"
fi

# Check 6: Covers channel arguments
if grep -q 'ChannelArguments\|channel_arguments\|arguments' "$WORKSPACE/docs/api_channel_creation.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers channel arguments"
else
    echo "FAIL: Covers channel arguments"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
