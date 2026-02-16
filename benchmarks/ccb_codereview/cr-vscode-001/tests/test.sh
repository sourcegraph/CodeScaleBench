#!/bin/bash
# Reward: checklist (0.0-1.0) — F1 defect detection plus fix quality score
# Test script for cr-vscode-001: Review VS Code editor core for injected defects

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

# Defect 1: containsPosition uses > (not >=) for endColumn check
range_file = "src/vs/editor/common/core/range.ts"
if os.path.isfile(range_file):
    with open(range_file) as f:
        range_src = f.read()
    defect1_pass = False
    # Pattern A: Original pattern — endColumn check uses > not >=
    # Find the containsPosition static method and check the endColumn comparison
    cp_idx = range_src.find("static containsPosition")
    if cp_idx >= 0:
        cp_block = range_src[cp_idx:cp_idx+500]
        # Check that endColumn uses > (strict greater than, not >=)
        if re.search(r'position\.column\s*>\s*range\.endColumn', cp_block):
            # Make sure it's NOT >=
            if not re.search(r'position\.column\s*>=\s*range\.endColumn', cp_block):
                defect1_pass = True
    # Pattern B: Alternative — the entire condition rewritten but logically equivalent
    if not defect1_pass and cp_idx >= 0:
        cp_block = range_src[cp_idx:cp_idx+500]
        # Check for column <= endColumn (inclusive containment)
        if re.search(r'position\.column\s*<=\s*range\.endColumn', cp_block):
            defect1_pass = True
    if defect1_pass:
        fix_hits += 1
        print("Fix defect-1: PASS (containsPosition endColumn check restored to >)", file=sys.stderr)
    else:
        print("Fix defect-1: FAIL (containsPosition still uses >= for endColumn)", file=sys.stderr)
else:
    print(f"Fix defect-1: FAIL ({range_file} not found)", file=sys.stderr)

# Defect 2: createRegExp matchCase flag negation restored
strings_file = "src/vs/base/common/strings.ts"
if os.path.isfile(strings_file):
    with open(strings_file) as f:
        strings_src = f.read()
    defect2_pass = False
    # Pattern A: Original negation — !options.matchCase
    if re.search(r'!\s*options\.matchCase', strings_src):
        defect2_pass = True
    # Pattern B: options.matchCase === false or == false
    if not defect2_pass and re.search(r'options\.matchCase\s*===?\s*false', strings_src):
        defect2_pass = True
    # Pattern C: negation stored in variable
    if not defect2_pass and re.search(r'!\s*\w+.*matchCase', strings_src):
        defect2_pass = True
    if defect2_pass:
        fix_hits += 1
        print("Fix defect-2: PASS (matchCase flag negation restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (matchCase flag still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-2: FAIL ({strings_file} not found)", file=sys.stderr)

# Defect 3: CharCode.W restored in isMultilineRegexSource
search_file = "src/vs/editor/common/model/textModelSearch.ts"
if os.path.isfile(search_file):
    with open(search_file) as f:
        search_src = f.read()
    defect3_pass = False
    # Find the isMultilineRegexSource function and check for CharCode.W
    multi_idx = search_src.find("isMultilineRegexSource")
    if multi_idx >= 0:
        multi_func = search_src[multi_idx:multi_idx+500]
        # Pattern A: CharCode.W present in the condition
        if re.search(r'CharCode\.W', multi_func):
            defect3_pass = True
        # Pattern B: Character code 87 (W) or backslash-W string check
        if not defect3_pass and re.search(r'87|\\\\W|["\']W["\']', multi_func):
            defect3_pass = True
    if defect3_pass:
        fix_hits += 1
        print("Fix defect-3: PASS (CharCode.W check restored in isMultilineRegexSource)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (CharCode.W still missing from multiline check)", file=sys.stderr)
else:
    print(f"Fix defect-3: FAIL ({search_file} not found)", file=sys.stderr)

# Defect 4: Provider sort order restored in _compareByScoreAndTime
registry_file = "src/vs/editor/common/languageFeatureRegistry.ts"
if os.path.isfile(registry_file):
    with open(registry_file) as f:
        registry_src = f.read()
    defect4_pass = False
    # Find the _compareByScoreAndTime method
    cmp_idx = registry_src.find("_compareByScoreAndTime")
    if cmp_idx >= 0:
        cmp_block = registry_src[cmp_idx:cmp_idx+400]
        # Pattern A: a._score < b._score returns 1 (positive = b comes first = higher scores first)
        if re.search(r'a\._score\s*<\s*b\._score.*\n.*return\s+1', cmp_block):
            defect4_pass = True
        # Pattern B: b._score - a._score (numeric descending)
        if not defect4_pass and re.search(r'b\._score\s*-\s*a\._score', cmp_block):
            defect4_pass = True
        # Pattern C: a._score > b._score returns -1 (correct descending order)
        if not defect4_pass and re.search(r'a\._score\s*>\s*b\._score.*\n.*return\s+-1', cmp_block):
            defect4_pass = True
    if defect4_pass:
        fix_hits += 1
        print("Fix defect-4: PASS (score sort order restored — higher scores first)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (score sort order still inverted)", file=sys.stderr)
else:
    print(f"Fix defect-4: FAIL ({registry_file} not found)", file=sys.stderr)

# Defect 5: Position.isBefore uses < (not <=) for column comparison
position_file = "src/vs/editor/common/core/position.ts"
if os.path.isfile(position_file):
    with open(position_file) as f:
        position_src = f.read()
    defect5_pass = False
    # Find the static isBefore method
    ib_idx = position_src.find("static isBefore")
    if ib_idx >= 0:
        ib_block = position_src[ib_idx:ib_idx+300]
        # Pattern A: a.column < b.column (strict less than, NOT <=)
        if re.search(r'a\.column\s*<\s*b\.column', ib_block):
            # Make sure it's NOT <=
            if not re.search(r'a\.column\s*<=\s*b\.column', ib_block):
                defect5_pass = True
        # Pattern B: b.column > a.column (equivalent strict comparison)
        if not defect5_pass and re.search(r'b\.column\s*>\s*a\.column', ib_block):
            if not re.search(r'b\.column\s*>=\s*a\.column', ib_block):
                defect5_pass = True
    if defect5_pass:
        fix_hits += 1
        print("Fix defect-5: PASS (isBefore column check restored to <)", file=sys.stderr)
    else:
        print("Fix defect-5: FAIL (isBefore still uses <= for column)", file=sys.stderr)
else:
    print(f"Fix defect-5: FAIL ({position_file} not found)", file=sys.stderr)

# Defect 6: isValidMatch uses && (not ||) for word boundary checks
if os.path.isfile(search_file):
    defect6_pass = False
    # Find the isValidMatch function
    vm_idx = search_src.find("isValidMatch")
    if vm_idx >= 0:
        vm_block = search_src[vm_idx:vm_idx+300]
        # Pattern A: && between left and right boundary checks
        if re.search(r'leftIsWordBounday.*\n.*&&.*rightIsWordBounday', vm_block):
            defect6_pass = True
        # Pattern B: Both functions called and combined with AND
        if not defect6_pass and re.search(r'leftIsWordBounday.*&&.*rightIsWordBounday', vm_block, re.DOTALL):
            defect6_pass = True
        # Pattern C: Stored results combined with &&
        if not defect6_pass:
            if 'leftIsWordBounday' in vm_block and 'rightIsWordBounday' in vm_block and '&&' in vm_block:
                if '||' not in vm_block[vm_block.find('leftIsWordBounday'):vm_block.find('rightIsWordBounday')+30]:
                    defect6_pass = True
    if defect6_pass:
        fix_hits += 1
        print("Fix defect-6: PASS (&& restored in isValidMatch)", file=sys.stderr)
    else:
        print("Fix defect-6: FAIL (isValidMatch still uses || instead of &&)", file=sys.stderr)
else:
    print(f"Fix defect-6: FAIL ({search_file} not found)", file=sys.stderr)

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
