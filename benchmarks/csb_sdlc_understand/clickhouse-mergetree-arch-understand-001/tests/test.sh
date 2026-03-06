#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=8
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Architecture analysis exists
if [ -f "$WORKSPACE/architecture_analysis.md" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Architecture analysis exists"
else
    echo "FAIL: Architecture analysis exists"
fi

# Check 2: Covers MergeTree
if grep -q 'MergeTree\|mergetree' "$WORKSPACE/architecture_analysis.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers MergeTree"
else
    echo "FAIL: Covers MergeTree"
fi

# Check 3: Covers write path
if grep -q 'INSERT\|insert\|write path\|Write Path' "$WORKSPACE/architecture_analysis.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers write path"
else
    echo "FAIL: Covers write path"
fi

# Check 4: Covers merge path
if grep -q 'merge\|Merge\|background' "$WORKSPACE/architecture_analysis.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers merge path"
else
    echo "FAIL: Covers merge path"
fi

# Check 5: Covers read path
if grep -q 'SELECT\|select\|read path\|Read Path\|query' "$WORKSPACE/architecture_analysis.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers read path"
else
    echo "FAIL: Covers read path"
fi

# Check 6: References key classes
if grep -q 'MergeTreeData\|MergeTreeDataWriter\|MergeTreeDataMerger\|MergeTreeDataSelect' "$WORKSPACE/architecture_analysis.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: References key classes"
else
    echo "FAIL: References key classes"
fi

# Check 7: Describes data parts
if grep -q 'part\|Part\|data part\|DataPart' "$WORKSPACE/architecture_analysis.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Describes data parts"
else
    echo "FAIL: Describes data parts"
fi

# Check 8: References source directory
if grep -q 'src/Storages/MergeTree' "$WORKSPACE/architecture_analysis.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: References source directory"
else
    echo "FAIL: References source directory"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
