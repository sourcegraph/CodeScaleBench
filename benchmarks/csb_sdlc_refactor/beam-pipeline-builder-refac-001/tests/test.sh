#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Validator file exists
if [ -f "$WORKSPACE/sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Validator file exists"
else
    echo "FAIL: Validator file exists"
fi

# Check 2: Validator class defined
if grep -q 'class PipelineOptionsValidator' "$WORKSPACE/sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Validator class defined"
else
    echo "FAIL: Validator class defined"
fi

# Check 3: Uses Builder pattern
if grep -q 'Builder\|builder' "$WORKSPACE/sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Uses Builder pattern"
else
    echo "FAIL: Uses Builder pattern"
fi

# Check 4: Has validation methods
if grep -q 'validateRequired\|validateType\|validate' "$WORKSPACE/sdks/java/core/src/main/java/org/apache/beam/sdk/options/PipelineOptionsValidator.java" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Has validation methods"
else
    echo "FAIL: Has validation methods"
fi

# Check 5: ValidationResult class referenced
if grep -rq 'ValidationResult' "$WORKSPACE/sdks/java/core/src/main/java/org/apache/beam/sdk/options/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: ValidationResult class referenced"
else
    echo "FAIL: ValidationResult class referenced"
fi

# Check 6: Test file references validator
if grep -rq 'PipelineOptionsValidator\|pipeline_options_validator' "$WORKSPACE/sdks/java/core/src/test/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Test file references validator"
else
    echo "FAIL: Test file references validator"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
