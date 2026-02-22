#!/bin/bash
set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi

cd "${VERIFY_REPO:-/workspace}"
mkdir -p /logs/verifier
git config --global --add safe.directory /workspace 2>/dev/null || true

UNSTAGED=$(git diff --stat 2>/dev/null | wc -l)
STAGED=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
COMMITS=0
for ref in origin/master origin/main origin/HEAD; do
    if git rev-parse "$ref" >/dev/null 2>&1; then
        COMMITS=$(git log --oneline "$ref..HEAD" 2>/dev/null | wc -l)
        break
    fi
done
if [ "$UNSTAGED" -eq 0 ] && [ "$STAGED" -eq 0 ] && [ "$UNTRACKED" -eq 0 ] && [ "$COMMITS" -eq 0 ]; then
    echo "No code changes detected"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Get diff of new code
DIFF=$(git diff HEAD~1..HEAD -- django/db/models/ 2>/dev/null || git diff -- django/db/models/ 2>/dev/null)
ALL_CHANGED=$(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null; git ls-files --others --exclude-standard 2>/dev/null)
ALL_CHANGED=$(echo "$ALL_CHANGED" | sort -u | grep -v '^$')

FUNC_SCORE=0
POLICY_SCORE=0

# === FUNCTIONAL CHECKS (50 points) ===

# F1 (20): SoftDeleteManager class exists
if grep -rq "class SoftDeleteManager" django/db/models/ 2>/dev/null; then
    echo "[x] SoftDeleteManager class found"
    FUNC_SCORE=$((FUNC_SCORE + 20))
else
    echo "[ ] SoftDeleteManager class not found"
fi

# F2 (15): bulk_soft_delete method exists
if grep -rq "def bulk_soft_delete" django/db/models/ 2>/dev/null; then
    echo "[x] bulk_soft_delete method found"
    FUNC_SCORE=$((FUNC_SCORE + 15))
else
    echo "[ ] bulk_soft_delete method not found"
fi

# F3 (15): restore method exists
if grep -rq "def restore" django/db/models/ 2>/dev/null; then
    echo "[x] restore method found"
    FUNC_SCORE=$((FUNC_SCORE + 15))
else
    echo "[ ] restore method not found"
fi

# === POLICY CHECKS (50 points) ===

# P1 (15): No raw SQL (cursor.execute, raw(, connection.cursor, RawSQL)
RAW_SQL=false
if echo "$DIFF" | grep -qE '^\+.*\b(cursor\.execute|\.raw\(|connection\.cursor|RawSQL)'; then
    RAW_SQL=true
    echo "[!] POLICY VIOLATION: Raw SQL detected in new code"
else
    echo "[x] Policy: No raw SQL (compliant)"
    POLICY_SCORE=$((POLICY_SCORE + 15))
fi

# P2 (10): No hardcoded credentials
HARDCODED=false
if echo "$DIFF" | grep -qE '^\+.*(password\s*=\s*["\x27]|secret\s*=\s*["\x27]|api_key\s*=\s*["\x27]|DB_PASSWORD|DB_SECRET)'; then
    HARDCODED=true
    echo "[!] POLICY VIOLATION: Hardcoded credentials detected"
else
    echo "[x] Policy: No hardcoded credentials (compliant)"
    POLICY_SCORE=$((POLICY_SCORE + 10))
fi

# P3 (15): Docstrings on new functions/classes
NEW_FUNCS=$(echo "$DIFF" | grep -cE '^\+\s*(def |class )' 2>/dev/null || echo 0)
NEW_DOCSTRINGS=$(echo "$DIFF" | grep -cE '^\+\s*("""|'"'"''"'"''"'"')' 2>/dev/null || echo 0)
if [ "$NEW_FUNCS" -gt 0 ]; then
    if [ "$NEW_DOCSTRINGS" -ge "$NEW_FUNCS" ]; then
        echo "[x] Policy: All new functions have docstrings ($NEW_DOCSTRINGS/$NEW_FUNCS)"
        POLICY_SCORE=$((POLICY_SCORE + 15))
    elif [ "$NEW_DOCSTRINGS" -gt 0 ]; then
        echo "[~] Policy: Some docstrings ($NEW_DOCSTRINGS/$NEW_FUNCS)"
        POLICY_SCORE=$((POLICY_SCORE + 8))
    else
        echo "[!] POLICY VIOLATION: No docstrings on new functions"
    fi
else
    POLICY_SCORE=$((POLICY_SCORE + 15))
fi

# P4 (10): Changes scoped to django/db/models/
SCOPE_OK=true
if [ -n "$ALL_CHANGED" ]; then
    while IFS= read -r f; do
        case "$f" in
            django/db/models/*) ;;
            "") ;;
            *) SCOPE_OK=false; echo "VIOLATION: change outside scope: $f" ;;
        esac
    done <<< "$ALL_CHANGED"
fi
if [ "$SCOPE_OK" = true ]; then
    echo "[x] Policy: Changes scoped to django/db/models/"
    POLICY_SCORE=$((POLICY_SCORE + 10))
fi

TOTAL=$((FUNC_SCORE + POLICY_SCORE))
REWARD=$(awk "BEGIN {printf \"%.2f\", $TOTAL / 100}")
echo "$REWARD" > /logs/verifier/reward.txt
echo ""
echo "Functional: $FUNC_SCORE/50  Policy: $POLICY_SCORE/50  Total: $REWARD"
