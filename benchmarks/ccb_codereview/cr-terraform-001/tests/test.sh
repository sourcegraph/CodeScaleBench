#!/bin/bash
# Reward: checklist (0.0-1.0) — F1 defect detection plus fix quality score
# Test script for cr-terraform-001: Review Terraform plan/apply evaluation pipeline for injected defects

set -e

cd /workspace

# Create log directories
mkdir -p /logs/verifier

# Fix git safe.directory
git config --global --add safe.directory /workspace 2>/dev/null || true

# Guard: if no code changes were made, the agent didn't execute successfully
UNSTAGED_COUNT=$(git diff --stat 2>/dev/null | wc -l)
STAGED_COUNT=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED_COUNT=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
COMMIT_COUNT=0
ORIGIN_REF=""
for ref in origin/master origin/main origin/HEAD; do
    if git rev-parse "$ref" >/dev/null 2>&1; then
        ORIGIN_REF="$ref"
        break
    fi
done
if [ -n "$ORIGIN_REF" ]; then
    COMMIT_COUNT=$(git log --oneline "$ORIGIN_REF..HEAD" 2>/dev/null | wc -l)
elif git rev-parse FETCH_HEAD >/dev/null 2>&1; then
    COMMIT_COUNT=$(git log --oneline FETCH_HEAD..HEAD 2>/dev/null | wc -l)
else
    TOTAL_COMMITS=$(git log --oneline 2>/dev/null | wc -l)
    if [ "$TOTAL_COMMITS" -gt 1 ]; then
        COMMIT_COUNT=$((TOTAL_COMMITS - 1))
    fi
fi
echo "Change detection: unstaged=$UNSTAGED_COUNT staged=$STAGED_COUNT untracked=$UNTRACKED_COUNT commits=$COMMIT_COUNT"
if [ "$UNSTAGED_COUNT" -eq 0 ] && [ "$STAGED_COUNT" -eq 0 ] && [ "$UNTRACKED_COUNT" -eq 0 ] && [ "$COMMIT_COUNT" -eq 0 ]; then
    echo "No code changes detected - agent did not execute successfully"
    echo "0.0" > /logs/verifier/reward.txt
    echo ""
    echo "Tests completed - Score: 0.0 (no changes)"
    exit 0
fi

# ── Hybrid Scoring ───────────────────────────────────────
# 50% detection F1 (precision × recall of reported defects)
# 50% fix score (proportion of defects with correct code fixes)

EXPECTED_DEFECTS="/tests/expected_defects.json"
REVIEW_JSON="/workspace/review.json"

FINAL_SCORE=$(python3 - "$EXPECTED_DEFECTS" "$REVIEW_JSON" <<'PYEOF'
import json, sys, os

expected_path = sys.argv[1]
review_path = sys.argv[2]

with open(expected_path) as f:
    expected = json.load(f)

num_expected = len(expected)

# ── Detection scoring ────────────────────────────────────
# Parse agent's review.json — match by file path
# Strip markdown code fences if the agent wrapped JSON in ```json blocks
import re
def strip_code_fences(text):
    m = re.search(r'```(?:json)?\s*\n(.*?)```', text, re.DOTALL)
    return m.group(1).strip() if m else text.strip()

reported = []
if os.path.isfile(review_path):
    try:
        with open(review_path) as f:
            raw = f.read()
        raw = strip_code_fences(raw)
        reported = json.loads(raw)
        if not isinstance(reported, list):
            reported = []
    except (json.JSONDecodeError, ValueError):
        reported = []

# Build set of expected file paths for matching
expected_files = {}
for d in expected:
    fp = d["file"]
    if fp not in expected_files:
        expected_files[fp] = []
    expected_files[fp].append(d)

# Match: a reported defect counts as a true positive if its file
# matches an expected defect file (one match per expected defect)
matched_expected = set()
true_positives = 0
for r in reported:
    r_file = r.get("file", "")
    for d in expected:
        if d["id"] in matched_expected:
            continue
        if d["file"] == r_file or r_file.endswith(d["file"]) or d["file"].endswith(r_file):
            # For files with multiple defects, try to match by line proximity
            r_line = r.get("line", 0)
            d_line_start = d.get("line_start", 0)
            d_line_end = d.get("line_end", 9999)
            # If line info available, prefer matching within ±50 lines
            if r_line > 0 and d_line_start > 0:
                if abs(r_line - d_line_start) <= 50 or (d_line_start <= r_line <= d_line_end):
                    matched_expected.add(d["id"])
                    true_positives += 1
                    break
            else:
                matched_expected.add(d["id"])
                true_positives += 1
                break
    else:
        # If no line-based match found, try file-only match for remaining unmatched defects
        for d in expected:
            if d["id"] in matched_expected:
                continue
            if d["file"] == r_file or r_file.endswith(d["file"]) or d["file"].endswith(r_file):
                matched_expected.add(d["id"])
                true_positives += 1
                break

precision = true_positives / len(reported) if reported else 0.0
recall = true_positives / num_expected if num_expected > 0 else 0.0
if precision + recall > 0:
    f1 = 2 * precision * recall / (precision + recall)
else:
    f1 = 0.0

print(f"Detection: TP={true_positives} reported={len(reported)} expected={num_expected}", file=sys.stderr)
print(f"Detection: precision={precision:.3f} recall={recall:.3f} F1={f1:.3f}", file=sys.stderr)

# ── Fix scoring ──────────────────────────────────────────
# Check if agent's code changes contain the expected fix patterns
fix_hits = 0

# Defect 1: walkValidate check restored in GetInputVariable
eval_file = "internal/terraform/evaluate.go"
if os.path.isfile(eval_file):
    with open(eval_file) as f:
        eval_code = f.read()
    defect1_pass = False
    # Pattern A: Original pattern — d.Operation == walkValidate
    if re.search(r'd\.Operation\s*==\s*walkValidate', eval_code):
        defect1_pass = True
    # Pattern B: Explicit equality check with variable
    if not defect1_pass and re.search(r'Operation\s*==\s*walkValidate', eval_code):
        defect1_pass = True
    # Also verify the != is NOT there (the defect)
    if defect1_pass:
        # Find the GetInputVariable function context
        giv_idx = eval_code.find("GetInputVariable")
        if giv_idx >= 0:
            giv_func = eval_code[giv_idx:giv_idx+2000]
            if "!= walkValidate" in giv_func:
                defect1_pass = False  # Still has the defect
    if defect1_pass:
        fix_hits += 1
        print("Fix defect-1: PASS (walkValidate check restored)", file=sys.stderr)
    else:
        print("Fix defect-1: FAIL (walkValidate check still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-1: FAIL ({eval_file} not found)", file=sys.stderr)

# Defect 2: config nil check restored in GetInputVariable
if os.path.isfile(eval_file):
    defect2_pass = False
    # Find the Variables[addr.Name] + nil check pattern
    giv_idx = eval_code.find("GetInputVariable")
    if giv_idx >= 0:
        giv_func = eval_code[giv_idx:giv_idx+1500]
        # Pattern A: config == nil (original)
        if re.search(r'config\s*==\s*nil', giv_func):
            defect2_pass = True
        # Pattern B: config != nil should NOT be followed by the error block
        if not defect2_pass and 'config != nil' not in giv_func:
            # If someone restructured: check that undeclared variables produce errors
            if re.search(r'Variables\[.*\].*\n.*nil.*\n.*suggestions', giv_func, re.DOTALL):
                defect2_pass = True
    if defect2_pass:
        fix_hits += 1
        print("Fix defect-2: PASS (config nil check restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (config nil check still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-2: FAIL ({eval_file} not found)", file=sys.stderr)

# Defect 3: hasUnknownKeys check restored in GetResource
if os.path.isfile(eval_file):
    defect3_pass = False
    # Find the ResourceInstanceKeys call context
    rik_idx = eval_code.find("ResourceInstanceKeys")
    if rik_idx >= 0:
        rik_context = eval_code[rik_idx:rik_idx+500]
        # Pattern A: hasUnknownKeys { (without negation)
        if re.search(r'hasUnknownKeys\s*\{', rik_context):
            # Make sure it's NOT negated
            line_with_key = ""
            for line in rik_context.split('\n'):
                if 'hasUnknownKeys' in line and '{' in line:
                    line_with_key = line
                    break
            if line_with_key and '!hasUnknownKeys' not in line_with_key:
                defect3_pass = True
        # Pattern B: Direct boolean check without negation in different form
        if not defect3_pass and re.search(r';\s*hasUnknownKeys\s*[{]', rik_context):
            if '!hasUnknownKeys' not in rik_context[:200]:
                defect3_pass = True
    if defect3_pass:
        fix_hits += 1
        print("Fix defect-3: PASS (hasUnknownKeys check restored)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (hasUnknownKeys check still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-3: FAIL ({eval_file} not found)", file=sys.stderr)

# Defect 4: Ephemeral check restored in prepareFinalInputVariableValue
var_file = "internal/terraform/eval_variable.go"
if os.path.isfile(var_file):
    with open(var_file) as f:
        var_code = f.read()
    defect4_pass = False
    # Find the ephemeral mark section
    eph_idx = var_code.find("ephemeral input variable always has an ephemeral value")
    if eph_idx >= 0:
        # Look at the ~200 chars BEFORE this comment for the if condition
        before_comment = var_code[max(0,eph_idx-200):eph_idx]
        # Pattern A: if cfg.Ephemeral { (without negation)
        if re.search(r'if\s+cfg\.Ephemeral\s*\{', before_comment):
            defect4_pass = True
        # Pattern B: Check there's no negation
        if not defect4_pass and re.search(r'if\s+cfg\.Ephemeral', before_comment):
            if '!cfg.Ephemeral' not in before_comment:
                defect4_pass = True
    else:
        # Fallback: look for cfg.Ephemeral pattern near marks.Ephemeral
        mark_idx = var_code.find("val.Mark(marks.Ephemeral)")
        if mark_idx >= 0:
            before_mark = var_code[max(0,mark_idx-300):mark_idx]
            if re.search(r'if\s+cfg\.Ephemeral\s*\{', before_mark):
                defect4_pass = True
    if defect4_pass:
        fix_hits += 1
        print("Fix defect-4: PASS (Ephemeral check restored)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (Ephemeral check still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-4: FAIL ({var_file} not found)", file=sys.stderr)

# Defect 5: checkApplyTimeVariables call restored in context_apply.go
apply_file = "internal/terraform/context_apply.go"
if os.path.isfile(apply_file):
    with open(apply_file) as f:
        apply_code = f.read()
    defect5_pass = False
    # Pattern A: checkApplyTimeVariables call present
    if re.search(r'checkApplyTimeVariables\s*\(', apply_code):
        defect5_pass = True
    # Pattern B: ApplyTimeVariables validation in some form
    if not defect5_pass and re.search(r'ApplyTimeVariables.*SetVariables|SetVariables.*ApplyTimeVariables', apply_code):
        defect5_pass = True
    # Pattern C: Variable validation call with error check
    if not defect5_pass and re.search(r'check.*[Vv]ariable.*diags.*HasErrors', apply_code, re.DOTALL):
        defect5_pass = True
    if defect5_pass:
        fix_hits += 1
        print("Fix defect-5: PASS (apply-time variable validation restored)", file=sys.stderr)
    else:
        print("Fix defect-5: FAIL (apply-time variable validation not found)", file=sys.stderr)
else:
    print(f"Fix defect-5: FAIL ({apply_file} not found)", file=sys.stderr)

# Defect 6: NilHook.PreApply returns HookActionContinue restored
hook_file = "internal/terraform/hook.go"
if os.path.isfile(hook_file):
    with open(hook_file) as f:
        hook_code = f.read()
    defect6_pass = False
    # Find the NilHook PreApply method
    preapply_idx = hook_code.find("NilHook) PreApply")
    if preapply_idx >= 0:
        preapply_func = hook_code[preapply_idx:preapply_idx+300]
        # Pattern A: returns HookActionContinue
        if re.search(r'return\s+HookActionContinue', preapply_func):
            defect6_pass = True
        # Pattern B: returns Continue constant (different name)
        if not defect6_pass and re.search(r'return\s+.*Continue', preapply_func):
            defect6_pass = True
        # Verify it does NOT return Halt
        if defect6_pass and re.search(r'return\s+HookActionHalt', preapply_func):
            defect6_pass = False  # Still has the defect
    if defect6_pass:
        fix_hits += 1
        print("Fix defect-6: PASS (NilHook.PreApply returns Continue)", file=sys.stderr)
    else:
        print("Fix defect-6: FAIL (NilHook.PreApply still returns Halt)", file=sys.stderr)
else:
    print(f"Fix defect-6: FAIL ({hook_file} not found)", file=sys.stderr)

fix_score = fix_hits / num_expected if num_expected > 0 else 0.0

# Gate: review must have at least 1 reported defect with a 'file' field to earn fix points
reported_with_file = [r for r in reported if r.get("file", "").strip()]
if not reported_with_file:
    fix_score = 0.0
    print("Fix gate: FAIL (no defects with 'file' field in review.json — fix score zeroed)", file=sys.stderr)

print(f"Fix score: {fix_hits}/{num_expected} = {fix_score:.3f}", file=sys.stderr)

# ── Final score ──────────────────────────────────────────
final = 0.5 * f1 + 0.5 * fix_score
print(f"Final score: 0.5*{f1:.3f} + 0.5*{fix_score:.3f} = {final:.3f}", file=sys.stderr)

# Print final score to stdout for capture
print(f"{final:.2f}")
PYEOF
)

echo "$FINAL_SCORE" > /logs/verifier/reward.txt
echo ""
echo "Tests completed - Score: $FINAL_SCORE"
