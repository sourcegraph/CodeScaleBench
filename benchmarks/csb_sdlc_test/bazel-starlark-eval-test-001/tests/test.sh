#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Test file exists in packages test dir
if grep -rq 'StarlarkRuleEval\|starlarkRuleEval\|RuleEvalTest' "$WORKSPACE/src/test/java/com/google/devtools/build/lib/packages/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Test file exists in packages test dir"
else
    echo "FAIL: Test file exists in packages test dir"
fi

# Check 2: Test class defined
if grep -rq 'class.*StarlarkRuleEval\|class.*RuleEvalTest' "$WORKSPACE/src/test/java/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Test class defined"
else
    echo "FAIL: Test class defined"
fi

# Check 3: Has @Test methods for rules
if grep -rq '@Test.*\|void test.*Rule\|void.*ruleInstantiation\|void.*ruleEval' "$WORKSPACE/src/test/java/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Has @Test methods for rules"
else
    echo "FAIL: Has @Test methods for rules"
fi

# Check 4: Tests reference RuleClass or RuleFactory
if grep -rq 'RuleClass\|RuleFactory\|ruleClass' "$WORKSPACE/src/test/java/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Tests reference RuleClass or RuleFactory"
else
    echo "FAIL: Tests reference RuleClass or RuleFactory"
fi

# Check 5: Tests cover attribute validation
if grep -rq 'attribute\|Attribute\|required\|mandatory' "$WORKSPACE/src/test/java/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Tests cover attribute validation"
else
    echo "FAIL: Tests cover attribute validation"
fi

# Check 6: Tests cover error cases
if grep -rq 'error\|Error\|exception\|Exception\|assertThrows\|fail' "$WORKSPACE/src/test/java/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Tests cover error cases"
else
    echo "FAIL: Tests cover error cases"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
