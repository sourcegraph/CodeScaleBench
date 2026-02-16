#!/bin/bash
# Reward: checklist (0.0-1.0) — F1 defect detection plus fix quality score
# Test script for cr-envoy-001: Review Envoy proxy HTTP filter chain for injected defects

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

# Defect 1: StopIteration restored for delay case in fault_filter
fault_file = "source/extensions/filters/http/fault/fault_filter.cc"
if os.path.isfile(fault_file):
    with open(fault_file) as f:
        fault = f.read()
    # Check that maybeSetupDelay returns StopIteration (not Continue)
    # Look for the pattern: maybeSetupDelay followed by StopIteration within ~5 lines
    defect1_pass = False
    # Pattern A: Original pattern — if (maybeSetupDelay...) return StopIteration
    if re.search(r'maybeSetupDelay.*\{[^}]*StopIteration', fault, re.DOTALL):
        defect1_pass = True
    # Pattern B: StopIteration appears right after maybeSetupDelay in source order
    delay_idx = fault.find("maybeSetupDelay")
    if not defect1_pass and delay_idx >= 0:
        after_delay = fault[delay_idx:delay_idx+200]
        if "StopIteration" in after_delay and "Continue" not in after_delay:
            defect1_pass = True
    # Pattern C: The entire delay branch returns StopAll variants
    if not defect1_pass and delay_idx >= 0:
        after_delay = fault[delay_idx:delay_idx+200]
        if "StopAll" in after_delay:
            defect1_pass = True
    if defect1_pass:
        fix_hits += 1
        print("Fix defect-1: PASS (StopIteration restored for delay)", file=sys.stderr)
    else:
        print("Fix defect-1: FAIL (maybeSetupDelay still returns Continue)", file=sys.stderr)
else:
    print(f"Fix defect-1: FAIL ({fault_file} not found)", file=sys.stderr)

# Defect 2: Header matching negation restored in header_utility
header_file = "source/common/http/header_utility.cc"
if os.path.isfile(header_file):
    with open(header_file) as f:
        header = f.read()
    defect2_pass = False
    # Pattern A: Original negation — !cfg_header_data->matchesHeaders
    if re.search(r'!\s*cfg_header_data->matchesHeaders', header):
        defect2_pass = True
    # Pattern B: Uses != or negation in another form
    if not defect2_pass and re.search(r'cfg_header_data->matchesHeaders.*==\s*false', header):
        defect2_pass = True
    # Pattern C: matchesHeaders result stored and negated
    if not defect2_pass and re.search(r'!\s*\w+.*matchesHeaders', header):
        defect2_pass = True
    if defect2_pass:
        fix_hits += 1
        print("Fix defect-2: PASS (header matching negation restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (matchHeaders logic still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-2: FAIL ({header_file} not found)", file=sys.stderr)

# Defect 3: Route cache clearing restored in ext_authz
authz_file = "source/extensions/filters/http/ext_authz/ext_authz.cc"
if os.path.isfile(authz_file):
    with open(authz_file) as f:
        authz = f.read()
    defect3_pass = False
    # Pattern A: clearRouteCache() call present with condition
    if re.search(r'clearRouteCache\s*\(\)', authz):
        defect3_pass = True
    # Pattern B: Route cache invalidation via any method
    if not defect3_pass and re.search(r'route.*[Cc]ache.*[Cc]lear|[Cc]lear.*[Rr]oute.*[Cc]ache', authz):
        defect3_pass = True
    if defect3_pass:
        fix_hits += 1
        print("Fix defect-3: PASS (route cache clearing restored)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (route cache clearing not found)", file=sys.stderr)
else:
    print(f"Fix defect-3: FAIL ({authz_file} not found)", file=sys.stderr)

# Defect 4: Response header check negation restored in filter_manager
fm_file = "source/common/http/filter_manager.cc"
if os.path.isfile(fm_file):
    with open(fm_file) as f:
        fm = f.read()
    defect4_pass = False
    # Find the checkRequiredResponseHeaders call and verify the condition is negated
    check_idx = fm.find("checkRequiredResponseHeaders")
    if check_idx >= 0:
        # Look at the ~200 chars after the check for the condition
        after_check = fm[check_idx:check_idx+300]
        # Pattern A: !status.ok() — original negation
        if re.search(r'!\s*status\.ok\(\)', after_check):
            defect4_pass = True
        # Pattern B: status != or !status
        if not defect4_pass and re.search(r'status\s*!=|!\s*status', after_check):
            defect4_pass = True
        # Pattern C: status.ok() is NOT followed directly by sendLocalReply (inverted logic fixed differently)
        if not defect4_pass:
            # Check that status.ok() is NOT the condition for sendLocalReply
            if_match = re.search(r'if\s*\(\s*status\.ok\(\)\s*\)\s*\{', after_check)
            local_reply = re.search(r'if\s*\(\s*!?\s*status\.ok\(\)\s*\)', after_check)
            if local_reply and '!' in local_reply.group():
                defect4_pass = True
    if defect4_pass:
        fix_hits += 1
        print("Fix defect-4: PASS (response header check negation restored)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (response header check still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-4: FAIL ({fm_file} not found)", file=sys.stderr)

# Defect 5: Rate limit check negation restored in fault_filter
if os.path.isfile(fault_file):
    defect5_pass = False
    # Find the postDelayInjection function and check the rate limit condition
    post_idx = fault.find("postDelayInjection")
    if post_idx >= 0:
        post_func = fault[post_idx:post_idx+500]
        # Pattern A: !isResponseRateLimitConfigured() — original negation
        if re.search(r'!\s*isResponseRateLimitConfigured\(\)', post_func):
            defect5_pass = True
        # Pattern B: isResponseRateLimitConfigured() == false
        if not defect5_pass and re.search(r'isResponseRateLimitConfigured\(\)\s*==\s*false', post_func):
            defect5_pass = True
        # Pattern C: negation stored in variable
        if not defect5_pass and re.search(r'!\s*\w+.*RateLimit', post_func):
            defect5_pass = True
    if defect5_pass:
        fix_hits += 1
        print("Fix defect-5: PASS (rate limit check negation restored)", file=sys.stderr)
    else:
        print("Fix defect-5: FAIL (rate limit check still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-5: FAIL ({fault_file} not found)", file=sys.stderr)

# Defect 6: isRemovableHeader guard restored in ext_authz
if os.path.isfile(authz_file):
    defect6_pass = False
    # Pattern A: isRemovableHeader call present
    if re.search(r'isRemovableHeader', authz):
        defect6_pass = True
    # Pattern B: Check for :-prefix or Host header guard (equivalent manual check)
    if not defect6_pass and re.search(r"header\[0\]\s*!=\s*':'|header\.empty\(\)\s*\|\|\s*header\[0\]\s*!=\s*':'", authz):
        defect6_pass = True
    # Pattern C: Explicit pseudo-header check
    if not defect6_pass and re.search(r':.*prefix|pseudo.?header.*check|host.*check', authz, re.IGNORECASE):
        defect6_pass = True
    if defect6_pass:
        fix_hits += 1
        print("Fix defect-6: PASS (isRemovableHeader guard restored)", file=sys.stderr)
    else:
        print("Fix defect-6: FAIL (isRemovableHeader guard not found)", file=sys.stderr)
else:
    print(f"Fix defect-6: FAIL ({authz_file} not found)", file=sys.stderr)

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
