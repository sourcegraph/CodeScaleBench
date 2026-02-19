#!/bin/bash
# Reward: checklist (0.0-1.0) — F1 defect detection plus fix quality score
# Test script for cr-security-001: Review curl for injected security-adjacent defects
# Security defects (critical/high) are weighted 2x in fix scoring

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh


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
# 50% fix score (proportion of defects with correct code fixes, security 2x weight)

EXPECTED_DEFECTS="/tests/expected_defects.json"
REVIEW_JSON="/workspace/review.json"

FINAL_SCORE=$(python3 - "$EXPECTED_DEFECTS" "$REVIEW_JSON" <<'PYEOF'
import json, sys, os

expected_path = sys.argv[1]
review_path = sys.argv[2]

with open(expected_path) as f:
    expected = json.load(f)

num_expected = len(expected)

# Security weight: critical/high severity defects count 2x
SECURITY_WEIGHT = 2.0
def get_weight(defect):
    sev = defect.get("severity", "medium")
    return SECURITY_WEIGHT if sev in ("critical", "high") else 1.0

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
    except (json.JSONDecodeError, ValueError, FileNotFoundError, OSError):
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

# ── Fix scoring (security-weighted) ──────────────────────
# Check if agent's code changes contain the expected fix patterns
# Security-critical defects (critical/high) are weighted 2x
fix_results = {}  # defect_id -> (passed, weight)

# Defect 1 (critical, 2x): Embedded NUL byte check restored in SAN verification
openssl_file = "lib/vtls/openssl.c"
if os.path.isfile(openssl_file):
    with open(openssl_file) as f:
        openssl_code = f.read()
    defect1_pass = False
    # Pattern A: altlen == strlen(altptr) check present before subj_alt_hostcheck
    if re.search(r'altlen\s*==\s*strlen\s*\(\s*altptr\s*\)', openssl_code):
        defect1_pass = True
    # Pattern B: strlen(altptr) == altlen (reversed order)
    if not defect1_pass and re.search(r'strlen\s*\(\s*altptr\s*\)\s*==\s*altlen', openssl_code):
        defect1_pass = True
    # Pattern C: Any NUL byte / embedded zero check near subj_alt_hostcheck
    if not defect1_pass:
        san_idx = openssl_code.find("subj_alt_hostcheck")
        if san_idx >= 0:
            context = openssl_code[max(0, san_idx-300):san_idx]
            if re.search(r'strlen.*alt|alt.*strlen|embedded.*zero|NUL', context, re.IGNORECASE):
                defect1_pass = True
    fix_results["defect-1"] = (defect1_pass, SECURITY_WEIGHT)
    if defect1_pass:
        print("Fix defect-1: PASS (NUL byte check restored in SAN verification)", file=sys.stderr)
    else:
        print("Fix defect-1: FAIL (NUL byte check not found)", file=sys.stderr)
else:
    fix_results["defect-1"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-1: FAIL ({openssl_file} not found)", file=sys.stderr)

# Defect 2 (high, 2x): Off-by-one in cookie domain tail match restored
cookie_file = "lib/cookie.c"
if os.path.isfile(cookie_file):
    with open(cookie_file) as f:
        cookie_code = f.read()
    defect2_pass = False
    # Pattern A: Original pattern with "- 1)" at the end
    if re.search(r'hostname\s*\+\s*hostname_len\s*-\s*cookie_domain_len\s*-\s*1\s*\)', cookie_code):
        defect2_pass = True
    # Pattern B: Equivalent using separate variable
    if not defect2_pass and re.search(r'hostname_len\s*-\s*cookie_domain_len\s*-\s*1', cookie_code):
        defect2_pass = True
    # Verify the defect pattern is NOT present (no "- 1" means still broken)
    if defect2_pass:
        # Find the tailmatch function context
        tm_idx = cookie_code.find("cookie_tailmatch")
        if tm_idx >= 0:
            tm_func = cookie_code[tm_idx:tm_idx+500]
            # Check for the buggy pattern (without - 1)
            if re.search(r'hostname_len\s*-\s*cookie_domain_len\s*\)', tm_func):
                # Both patterns present? Check which comes last in the tailmatch function
                has_correct = bool(re.search(r'hostname_len\s*-\s*cookie_domain_len\s*-\s*1\s*\)', tm_func))
                if not has_correct:
                    defect2_pass = False
    fix_results["defect-2"] = (defect2_pass, SECURITY_WEIGHT)
    if defect2_pass:
        print("Fix defect-2: PASS (cookie domain boundary check restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (off-by-one still present)", file=sys.stderr)
else:
    fix_results["defect-2"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-2: FAIL ({cookie_file} not found)", file=sys.stderr)

# Defect 3 (high, 2x): Buffer bounds check restored in passwd_callback
if os.path.isfile(openssl_file):
    defect3_pass = False
    # Find the passwd_callback function
    pc_idx = openssl_code.find("passwd_callback")
    if pc_idx >= 0:
        pc_func = openssl_code[pc_idx:pc_idx+500]
        # Pattern A: num > klen check before memcpy
        if re.search(r'num\s*>\s*klen', pc_func):
            defect3_pass = True
        # Pattern B: klen < num (reversed)
        if not defect3_pass and re.search(r'klen\s*<\s*num', pc_func):
            defect3_pass = True
        # Pattern C: num >= klen + 1 or similar
        if not defect3_pass and re.search(r'num\s*>=\s*klen', pc_func):
            defect3_pass = True
        # Pattern D: length check with (size_t)num
        if not defect3_pass and re.search(r'\(.*num.*\)\s*>\s*klen', pc_func):
            defect3_pass = True
    fix_results["defect-3"] = (defect3_pass, SECURITY_WEIGHT)
    if defect3_pass:
        print("Fix defect-3: PASS (buffer bounds check restored in passwd_callback)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (bounds check not found in passwd_callback)", file=sys.stderr)
else:
    fix_results["defect-3"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-3: FAIL ({openssl_file} not found)", file=sys.stderr)

# Defect 4 (medium, 1x): NULL guard restored in xfer_recv_shutdown
transfer_file = "lib/transfer.c"
if os.path.isfile(transfer_file):
    with open(transfer_file) as f:
        transfer_code = f.read()
    defect4_pass = False
    # Find xfer_recv_shutdown function (not xfer_recv_shutdown_started)
    xrs_idx = transfer_code.find("xfer_recv_shutdown(")
    if xrs_idx >= 0:
        xrs_func = transfer_code[xrs_idx:xrs_idx+400]
        # Pattern A: !data || !data->conn (original)
        if re.search(r'!data\s*\|\|\s*!data->conn', xrs_func):
            defect4_pass = True
        # Pattern B: data == NULL || data->conn == NULL
        if not defect4_pass and re.search(r'data\s*==\s*NULL', xrs_func):
            defect4_pass = True
        # Pattern C: !data (at minimum, check data is not NULL)
        if not defect4_pass and re.search(r'if\s*\(\s*!data\s*\)', xrs_func):
            defect4_pass = True
    fix_results["defect-4"] = (defect4_pass, 1.0)
    if defect4_pass:
        print("Fix defect-4: PASS (NULL guard restored in xfer_recv_shutdown)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (NULL guard not found)", file=sys.stderr)
else:
    fix_results["defect-4"] = (False, 1.0)
    print(f"Fix defect-4: FAIL ({transfer_file} not found)", file=sys.stderr)

# Defect 5 (high, 2x): Integer overflow guard restored in base64 encode
base64_file = "lib/base64.c"
if os.path.isfile(base64_file):
    with open(base64_file) as f:
        base64_code = f.read()
    defect5_pass = False
    # Pattern A: Original SIZEOF_SIZE_T == 4 + UINT_MAX/4 guard
    if re.search(r'SIZEOF_SIZE_T\s*==\s*4', base64_code) and re.search(r'UINT_MAX\s*/\s*4', base64_code):
        defect5_pass = True
    # Pattern B: Any overflow check on insize before the malloc
    if not defect5_pass:
        malloc_idx = base64_code.find("base64data = output = malloc")
        if malloc_idx >= 0:
            before_malloc = base64_code[max(0, malloc_idx-300):malloc_idx]
            # Check for any overflow guard (SIZE_MAX, UINT_MAX, or explicit comparison)
            if re.search(r'insize\s*>\s*(UINT_MAX|SIZE_MAX|SIZE_T_MAX)', before_malloc):
                defect5_pass = True
            # Pattern C: Overflow check using division
            if not defect5_pass and re.search(r'insize.*overflow|overflow.*insize', before_malloc, re.IGNORECASE):
                defect5_pass = True
    fix_results["defect-5"] = (defect5_pass, SECURITY_WEIGHT)
    if defect5_pass:
        print("Fix defect-5: PASS (integer overflow guard restored in base64)", file=sys.stderr)
    else:
        print("Fix defect-5: FAIL (overflow guard not found)", file=sys.stderr)
else:
    fix_results["defect-5"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-5: FAIL ({base64_file} not found)", file=sys.stderr)

# Calculate weighted fix score
total_weight = sum(w for _, w in fix_results.values())
weighted_hits = sum(w for passed, w in fix_results.values() if passed)
fix_score = weighted_hits / total_weight if total_weight > 0 else 0.0

# Gate: review must have at least 1 reported defect with a 'file' field to earn fix points
reported_with_file = [r for r in reported if r.get("file", "").strip()]
if not reported_with_file:
    fix_score = 0.0
    print("Fix gate: FAIL (no defects with 'file' field in review.json — fix score zeroed)", file=sys.stderr)

print(f"Fix score: weighted {weighted_hits:.1f}/{total_weight:.1f} = {fix_score:.3f}", file=sys.stderr)

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
