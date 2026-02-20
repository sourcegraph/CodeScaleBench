#!/bin/bash
# Reward: checklist (0.0-1.0) — F1 defect detection plus fix quality score
# Test script for cr-aspnetcore-001: Review an ASP.NET Core PR for injected functional bugs and compliance violations

set -e

# Legacy sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

# Artifact-only mode: sets VERIFY_REPO, provides apply_patches_from_review_json()
# Defaults VERIFY_REPO=/workspace when not in artifact mode
[ -f /tests/artifact_verifier_lib.sh ] && source /tests/artifact_verifier_lib.sh
VERIFY_REPO="${VERIFY_REPO:-/workspace}"

cd /workspace

# Create log directories
mkdir -p /logs/verifier

# Fix git safe.directory
git config --global --add safe.directory /workspace 2>/dev/null || true
git config --global --add safe.directory "${VERIFY_REPO}" 2>/dev/null || true

# Guard: check agent produced output
if [ "${ARTIFACT_ONLY:-false}" = "true" ]; then
    # Artifact mode: check for review.json
    if [ ! -f /workspace/review.json ]; then
        echo "No review.json found — agent did not produce artifact"
        echo "0.0" > /logs/verifier/reward.txt
        echo ""
        echo "Tests completed - Score: 0.0 (no artifact)"
        exit 0
    fi
    echo "Artifact mode: review.json found, applying patches to ${VERIFY_REPO}"
    apply_patches_from_review_json /workspace/review.json || echo "[verifier] Patch application returned non-zero (non-fatal, scoring continues)"
else
    # Legacy mode: check git changes in workspace
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
fi

# ── Hybrid Scoring ───────────────────────────────────────
# 50% detection F1 (precision × recall of reported defects)
# 50% fix score (proportion of defects with correct code fixes)

EXPECTED_DEFECTS="/tests/expected_defects.json"
REVIEW_JSON="/workspace/review.json"

FINAL_SCORE=$(python3 - "$EXPECTED_DEFECTS" "$REVIEW_JSON" "$VERIFY_REPO" <<'PYEOF'
import json, sys, os

expected_path = sys.argv[1]
review_path = sys.argv[2]
verify_repo = sys.argv[3] if len(sys.argv) > 3 else "/workspace"

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
            # Fallback: agent may wrap defects in a nested object
            if isinstance(reported, dict):
                for key in ("defects", "findings", "issues", "review"):
                    val = reported.get(key, None)
                    if isinstance(val, list):
                        reported = val
                        break
                    elif isinstance(val, dict):
                        for k2 in ("defects", "findings", "issues"):
                            v2 = val.get(k2, None)
                            if isinstance(v2, list):
                                reported = v2
                                break
                        if isinstance(reported, list):
                            break
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
# In artifact-only mode, patches were already applied to verify_repo
os.chdir(verify_repo)
print(f"Fix scoring: checking files in {verify_repo}", file=sys.stderr)
fix_hits = 0

# Defect 1: DisplayAttribute checked before DisplayNameAttribute (correct precedence)
accessor_file = "src/Components/Web/src/Forms/ExpressionMemberAccessor.cs"
if os.path.isfile(accessor_file):
    with open(accessor_file) as f:
        accessor = f.read()
    # Check that DisplayAttribute appears before DisplayNameAttribute in the method
    # Accept: (a) index-based ordering, (b) separate if-block for DisplayAttribute before DisplayNameAttribute,
    #         (c) DisplayAttribute checked in a conditional that short-circuits before DisplayNameAttribute
    display_idx = accessor.find("GetCustomAttribute<DisplayAttribute>")
    displayname_idx = accessor.find("GetCustomAttribute<DisplayNameAttribute>")
    defect1_pass = False
    # Pattern A: DisplayAttribute appears before DisplayNameAttribute in source order
    if display_idx >= 0 and displayname_idx >= 0 and display_idx < displayname_idx:
        defect1_pass = True
    # Pattern B: DisplayAttribute checked in a separate if-block (e.g., early return/assignment)
    if not defect1_pass and re.search(r'if\s*\(.*DisplayAttribute.*\).*\{', accessor) and display_idx >= 0:
        # If there's a dedicated if-block for DisplayAttribute and it appears before DisplayNameAttribute
        if displayname_idx < 0 or display_idx < displayname_idx:
            defect1_pass = True
    # Pattern C: Uses typeof(DisplayAttribute) check before typeof(DisplayNameAttribute)
    if not defect1_pass:
        typeof_da = accessor.find("typeof(DisplayAttribute)")
        typeof_dna = accessor.find("typeof(DisplayNameAttribute)")
        if typeof_da >= 0 and typeof_dna >= 0 and typeof_da < typeof_dna:
            defect1_pass = True
    if defect1_pass:
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
    # Accept multiple null-check patterns:
    # (a) "For is null" or "For == null" with InvalidOperationException (original)
    # (b) "For is not null" (inverted guard pattern — early return if NOT null, or guard clause)
    # (c) ArgumentNullException instead of InvalidOperationException
    # (d) "For != null" with guard clause
    # (e) Any null check on For with a throw statement
    has_null_check = bool(
        re.search(r'For\s+(is\s+null|is\s+not\s+null|==\s*null|!=\s*null)', dn)
    )
    has_exception = bool(
        re.search(r'(InvalidOperationException|ArgumentNullException|throw\s+new)', dn)
    )
    if has_null_check and has_exception:
        fix_hits += 1
        print("Fix defect-2: PASS (For null check restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (For null check not found)", file=sys.stderr)
else:
    print(f"Fix defect-2: FAIL ({dn_file} not found)", file=sys.stderr)

# Defect 3: _displayNameCache.Clear() restored in ClearCache method
if os.path.isfile(accessor_file):
    # Accept multiple cache-clearing patterns:
    # (a) _displayNameCache.Clear() — original exact match
    # (b) displayNameCache.Clear() — without underscore prefix
    # (c) Any variable ending in [Cc]ache followed by .Clear()
    # (d) Cache dictionary re-initialization (new Dictionary / new ConcurrentDictionary)
    defect3_pass = bool(
        re.search(r'[_]?[Dd]isplay[Nn]ame[Cc]ache\.Clear\(\)', accessor) or
        re.search(r'[Cc]ache\s*\.Clear\(\)', accessor) or
        re.search(r'[_]?[Dd]isplay[Nn]ame[Cc]ache\s*=\s*new\s+(Dictionary|ConcurrentDictionary)', accessor)
    )
    if defect3_pass:
        fix_hits += 1
        print("Fix defect-3: PASS (cache clearing restored)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (cache clearing not found)", file=sys.stderr)
else:
    print(f"Fix defect-3: FAIL ({accessor_file} not found)", file=sys.stderr)

# Defect 4: Expression equality check restored (render optimization)
if os.path.isfile(dn_file):
    # Accept multiple equality-check patterns for _previousFieldAccessor:
    # (a) _previousFieldAccessor with != (original)
    # (b) _previousFieldAccessor with Equals()
    # (c) _previousFieldAccessor with ReferenceEquals()
    # (d) previousFieldAccessor (without underscore) with any comparison
    # (e) _previousFieldAccessor with == (equality check present, even if inverted logic)
    has_field_accessor = bool(
        re.search(r'[_]?[Pp]revious[Ff]ield[Aa]ccessor', dn)
    )
    has_comparison = bool(
        re.search(r'[_]?[Pp]revious[Ff]ield[Aa]ccessor\s*(!= |== )', dn) or
        re.search(r'(Equals|ReferenceEquals)\s*\(.*[_]?[Pp]revious[Ff]ield[Aa]ccessor', dn) or
        re.search(r'[_]?[Pp]revious[Ff]ield[Aa]ccessor.*\.(Equals|ReferenceEquals)', dn) or
        re.search(r'!=\s*[_]?[Pp]revious[Ff]ield[Aa]ccessor', dn)
    )
    if has_field_accessor and has_comparison:
        fix_hits += 1
        print("Fix defect-4: PASS (expression equality optimization restored)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (expression equality check not found)", file=sys.stderr)
else:
    print(f"Fix defect-4: FAIL ({dn_file} not found)", file=sys.stderr)

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
