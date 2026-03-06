#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"

# Check 1: Resolver file exists
if [ -f "$WORKSPACE/src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs" ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Resolver file exists"
else
    echo "FAIL: Resolver file exists"
fi

# Check 2: Resolver class defined
if grep -q 'class UnifiedSymbolResolver\|UnifiedSymbolResolver' "$WORKSPACE/src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Resolver class defined"
else
    echo "FAIL: Resolver class defined"
fi

# Check 3: Strategy interface defined
if grep -q 'ISymbolResolutionStrategy\|interface.*Strategy' "$WORKSPACE/src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Strategy interface defined"
else
    echo "FAIL: Strategy interface defined"
fi

# Check 4: Has Resolve method
if grep -q 'Resolve\|resolve' "$WORKSPACE/src/Compilers/CSharp/Portable/Binder/UnifiedSymbolResolver.cs" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Has Resolve method"
else
    echo "FAIL: Has Resolve method"
fi

# Check 5: Has concrete strategies
if grep -rq 'TypeResolution\|MemberAccess\|NamespaceResolution' "$WORKSPACE/src/Compilers/CSharp/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Has concrete strategies"
else
    echo "FAIL: Has concrete strategies"
fi

# Check 6: Test file references resolver
if grep -rq 'UnifiedSymbolResolver\|SymbolResolver' "$WORKSPACE/src/Compilers/CSharp/Test/" 2>/dev/null; then
    SCORE=$((SCORE + 1))
    echo "PASS: Test file references resolver"
else
    echo "FAIL: Test file references resolver"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
