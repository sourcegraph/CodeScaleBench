#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: VM reference doc exists
if [ -f "$WORKSPACE/docs/gdscript_vm_reference.md" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: VM reference doc exists"
else
    echo "FAIL: VM reference doc exists"
fi

# Check 2: Documents opcodes
if grep -q 'opcode\|Opcode\|OPCODE' "$WORKSPACE/docs/gdscript_vm_reference.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Documents opcodes"
else
    echo "FAIL: Documents opcodes"
fi

# Check 3: Describes VM architecture
if grep -q 'stack\|Stack\|register\|Register' "$WORKSPACE/docs/gdscript_vm_reference.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Describes VM architecture"
else
    echo "FAIL: Describes VM architecture"
fi

# Check 4: Covers function calls
if grep -q 'call\|Call\|function.*call\|CALL' "$WORKSPACE/docs/gdscript_vm_reference.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers function calls"
else
    echo "FAIL: Covers function calls"
fi

# Check 5: References source files
if grep -q 'modules/gdscript' "$WORKSPACE/docs/gdscript_vm_reference.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: References source files"
else
    echo "FAIL: References source files"
fi

# Check 6: Covers type system
if grep -q 'Variant\|variant\|type' "$WORKSPACE/docs/gdscript_vm_reference.md" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Covers type system"
else
    echo "FAIL: Covers type system"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
