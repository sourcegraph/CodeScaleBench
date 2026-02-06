#!/bin/bash
# Test script for cr-aspnetcore-001: Review an ASP.NET Core PR for injected functional bugs and compliance violations

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
reported = []
if os.path.isfile(review_path):
    try:
        with open(review_path) as f:
            reported = json.load(f)
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

# Defect 1: DisplayAttribute checked before DisplayNameAttribute (correct precedence)
accessor_file = "src/Components/Web/src/Forms/ExpressionMemberAccessor.cs"
if os.path.isfile(accessor_file):
    with open(accessor_file) as f:
        accessor = f.read()
    # Check that DisplayAttribute appears before DisplayNameAttribute in the method
    display_idx = accessor.find("GetCustomAttribute<DisplayAttribute>")
    displayname_idx = accessor.find("GetCustomAttribute<DisplayNameAttribute>")
    if display_idx >= 0 and displayname_idx >= 0 and display_idx < displayname_idx:
        fix_hits += 1
        print("Fix defect-1: PASS (DisplayAttribute checked before DisplayNameAttribute)", file=sys.stderr)
    else:
        print("Fix defect-1: FAIL (attribute precedence not restored)", file=sys.stderr)
else:
    print(f"Fix defect-1: FAIL ({accessor_file} not found)", file=sys.stderr)

# Defect 2: Null check for For parameter restored in DisplayName.cs
dn_file = "src/Components/Web/src/Forms/DisplayName.cs"
if os.path.isfile(dn_file):
    with open(dn_file) as f:
        dn = f.read()
    if "For is null" in dn and "InvalidOperationException" in dn:
        fix_hits += 1
        print("Fix defect-2: PASS (For null check restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (For null check not found)", file=sys.stderr)
else:
    print(f"Fix defect-2: FAIL ({dn_file} not found)", file=sys.stderr)

# Defect 3: _displayNameCache.Clear() restored in ClearCache method
if os.path.isfile(accessor_file):
    if "_displayNameCache.Clear()" in accessor:
        fix_hits += 1
        print("Fix defect-3: PASS (_displayNameCache.Clear() restored)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (_displayNameCache.Clear() not found)", file=sys.stderr)
else:
    print(f"Fix defect-3: FAIL ({accessor_file} not found)", file=sys.stderr)

# Defect 4: Expression equality check restored (render optimization)
if os.path.isfile(dn_file):
    if "_previousFieldAccessor" in dn and "!=" in dn:
        fix_hits += 1
        print("Fix defect-4: PASS (expression equality optimization restored)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (expression equality check not found)", file=sys.stderr)
else:
    print(f"Fix defect-4: FAIL ({dn_file} not found)", file=sys.stderr)

fix_score = fix_hits / num_expected if num_expected > 0 else 0.0
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
