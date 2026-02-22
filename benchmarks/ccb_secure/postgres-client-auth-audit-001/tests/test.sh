#!/bin/bash
# Reward: ir_checklist (0.0-1.0) — IR metrics + security analysis quality
# Composite: 0.4 * task_quality + 0.3 * file_recall + 0.2 * file_precision + 0.1 * dep_accuracy

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

# ── Source shared verifier library ────────────────────────────────────────
source /tests/verifier_lib.sh

# ── Output check ─────────────────────────────────────────────────────────
SOLUTION_FILE="/logs/agent/solution.md"
# In artifact mode, populate expected output from answer.json analysis
if [ "${ARTIFACT_ONLY:-false}" = "true" ] && [ -f "${ANALYSIS_TEXT_FILE:-}" ]; then
    mkdir -p "/logs/agent"
    cp "$ANALYSIS_TEXT_FILE" "/logs/agent/solution.md"
    echo "[answer_json] Copied analysis text to /logs/agent/solution.md"
fi
if [ ! -f "$SOLUTION_FILE" ] || [ "$(wc -c < "$SOLUTION_FILE" 2>/dev/null || echo 0)" -lt 200 ]; then
    echo "No sufficient solution.md — agent did not produce analysis"
    echo "0.0" > /logs/verifier/reward.txt
    echo "[ ] Tests completed - Score: 0.0 (no output)"
    exit 0
fi

SOLUTION_SIZE=$(wc -c < "$SOLUTION_FILE")
echo "Solution file found ($SOLUTION_SIZE bytes)"

# ── IR metrics pipeline ──────────────────────────────────────────────────
run_ir_pipeline "$SOLUTION_FILE" "/tests/ground_truth.json" "/logs/verifier/ir_metrics.json"

# ── Task quality scoring ─────────────────────────────────────────────────
QUALITY_SCORE=0
QUALITY_MAX=10

# Required sections
if grep -qiE '^##\s+(Files Examined|Files Analyzed)' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[x] Has 'Files Examined' section"
fi

if grep -qiE '^##\s+Entry Points' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Has 'Entry Points' section"
else
    echo "[ ] Missing 'Entry Points' section"
fi

if grep -qiE '^##\s+Data Flow' "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Has 'Data Flow' section"
else
    echo "[ ] Missing 'Data Flow' section"
fi

# Vulnerability class identification
VULN_KEYWORDS="injection|XSS|SSRF|deserialization|auth.bypass|CSRF|path.traversal|buffer.overflow|race.condition|privilege.escalation|timing.attack|username.enumeration|brute.force"
if grep -qiE "$VULN_KEYWORDS" "$SOLUTION_FILE"; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Vulnerability class identified"
else
    echo "[ ] No vulnerability class identified"
fi

# Entry point verification
if [ ${#GT_ENTRY_POINTS[@]} -gt 0 ]; then
    ENTRY_FOUND=0
    for ep in "${GT_ENTRY_POINTS[@]}"; do
        ep_base=$(basename "$ep")
        if grep -qi "$ep_base" "$SOLUTION_FILE" 2>/dev/null; then
            ENTRY_FOUND=$((ENTRY_FOUND + 1))
        fi
    done
    if [ "$ENTRY_FOUND" -ge 1 ]; then
        QUALITY_SCORE=$((QUALITY_SCORE + 1))
        echo "[x] Entry point files referenced ($ENTRY_FOUND/${#GT_ENTRY_POINTS[@]})"
    fi
fi

# Security-specific keywords for PostgreSQL auth
SEC_KEYWORDS=(
    "ClientAuthentication"
    "hba_getauthmethod"
    "SCRAM"
    "get_role_password"
    "CheckPasswordAuth|CheckPWChallengeAuth"
    "pg_authid|rolcanlogin"
    "auth-scram|scram_exchange"
    "sendAuthRequest"
    "PerformAuthentication"
    "HbaLine|pg_hba"
)
SEC_FOUND=0
for kw in "${SEC_KEYWORDS[@]}"; do
    if grep -qiE "$kw" "$SOLUTION_FILE" 2>/dev/null; then
        SEC_FOUND=$((SEC_FOUND + 1))
    fi
done
if [ "$SEC_FOUND" -ge 4 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 2))
    echo "[x] Strong security keyword coverage ($SEC_FOUND/${#SEC_KEYWORDS[@]})"
elif [ "$SEC_FOUND" -ge 2 ]; then
    QUALITY_SCORE=$((QUALITY_SCORE + 1))
    echo "[~] Moderate security keyword coverage ($SEC_FOUND/${#SEC_KEYWORDS[@]})"
else
    echo "[ ] Weak security keyword coverage ($SEC_FOUND/${#SEC_KEYWORDS[@]})"
fi

# Clamp to max (keywords replace the generic word count + analysis depth checks)
if [ "$QUALITY_SCORE" -gt "$QUALITY_MAX" ]; then
    QUALITY_SCORE=$QUALITY_MAX
fi

TASK_QUALITY=$(awk "BEGIN {printf \"%.2f\", $QUALITY_SCORE / $QUALITY_MAX}")
echo "Task quality: $TASK_QUALITY ($QUALITY_SCORE / $QUALITY_MAX)"

# ── Composite score ──────────────────────────────────────────────────────
SCORE=$(composite_score "$TASK_QUALITY" "$IR_RECALL" "$IR_PRECISION" "$DEP_ACCURACY")

echo "$SCORE" > /logs/verifier/reward.txt
echo ""
echo "[x] Tests completed - Score: $SCORE (quality=$TASK_QUALITY recall=$IR_RECALL precision=$IR_PRECISION dep=$DEP_ACCURACY)"
