#!/bin/bash
set -euo pipefail

[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
SCORE=0
TOTAL=6
WORKSPACE="${VERIFY_REPO:-/workspace}"
git config --global --add safe.directory "$WORKSPACE" 2>/dev/null || true

# Check 1: Old symbol removed from primary definition
OLD_DEF_COUNT=$( (grep -r 'class MemoryStorage\|type MemoryStorage struct\|def MemoryStorage\|function MemoryStorage' "$WORKSPACE/raft/" "$WORKSPACE/server/" 2>/dev/null | grep -v 'alias\|compat\|deprecated\|backward\|#.*MemoryStorage\|//.*MemoryStorage' || true) | wc -l)
if [ "$OLD_DEF_COUNT" -eq 0 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Old symbol definition removed"
else
    echo "FAIL: Old symbol \"MemoryStorage\" still defined ($OLD_DEF_COUNT definitions found)"
fi

# Check 2: New symbol exists in definition
NEW_DEF_COUNT=$( (grep -r 'class InMemoryRaftLog\|type InMemoryRaftLog struct\|def InMemoryRaftLog\|function InMemoryRaftLog\|InMemoryRaftLog' "$WORKSPACE/raft/" "$WORKSPACE/server/" 2>/dev/null || true) | wc -l)
if [ "$NEW_DEF_COUNT" -gt 0 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: New symbol \"InMemoryRaftLog\" found ($NEW_DEF_COUNT occurrences)"
else
    echo "FAIL: New symbol \"InMemoryRaftLog\" not found"
fi

# Check 3: Old symbol reference count reduced (allowing aliases/deprecation)
OLD_REF_COUNT=$( (grep -r 'MemoryStorage' "$WORKSPACE/raft/" "$WORKSPACE/server/" 2>/dev/null | grep -v 'test\|_test\|spec\|alias\|compat\|deprecated\|backward\|#.*MemoryStorage\|//.*MemoryStorage\|\.pyc' || true) | wc -l)
if [ "$OLD_REF_COUNT" -le 3 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Old symbol references minimized ($OLD_REF_COUNT remaining, max 3)"
else
    echo "FAIL: Too many old symbol references remain ($OLD_REF_COUNT, max 3)"
fi

# Check 4: New symbol used across multiple files
NEW_FILE_COUNT=$( (grep -rl 'InMemoryRaftLog' "$WORKSPACE/raft/" "$WORKSPACE/server/" 2>/dev/null || true) | wc -l)
if [ "$NEW_FILE_COUNT" -ge 2 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: New symbol used across $NEW_FILE_COUNT files"
else
    echo "FAIL: New symbol only in $NEW_FILE_COUNT files (need >= 2)"
fi

# Check 5: New symbol call sites meet threshold
NEW_REF_COUNT=$( (grep -r 'InMemoryRaftLog' "$WORKSPACE/raft/" "$WORKSPACE/server/" 2>/dev/null || true) | wc -l)
if [ "$NEW_REF_COUNT" -ge 10 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: New symbol has $NEW_REF_COUNT references (>= 10)"
else
    echo "FAIL: New symbol only has $NEW_REF_COUNT references (need >= 10)"
fi

# Check 6: Code changes were actually made (git diff check)
cd "$WORKSPACE"
CHANGED_FILES=$(git diff --name-only 2>/dev/null | wc -l)
STAGED_FILES=$(git diff --cached --name-only 2>/dev/null | wc -l)
# Only count committed files beyond the initial clone commit
TOTAL_COMMITS=$(git rev-list --count HEAD 2>/dev/null || echo 0)
COMMITTED_FILES=0
if [ "$TOTAL_COMMITS" -gt 1 ]; then
    FIRST_COMMIT=$(git rev-list --max-parents=0 HEAD 2>/dev/null | head -1)
    if [ -n "$FIRST_COMMIT" ]; then
        COMMITTED_FILES=$(git diff --name-only "$FIRST_COMMIT..HEAD" 2>/dev/null | wc -l)
    fi
fi
TOTAL_CHANGES=$((CHANGED_FILES + STAGED_FILES + COMMITTED_FILES))
if [ "$TOTAL_CHANGES" -ge 2 ]; then
    SCORE=$((SCORE + 1))
    echo "PASS: Multiple files changed ($TOTAL_CHANGES)"
else
    echo "FAIL: Not enough files changed ($TOTAL_CHANGES, need >= 2)"
fi

echo ""
echo "Score: $SCORE / $TOTAL"

mkdir -p /logs/verifier
python3 -c "print($SCORE / $TOTAL)" > /logs/verifier/reward.txt
