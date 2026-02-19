#!/bin/bash
# Reward: checklist (0.0-1.0) — F1 defect detection plus fix quality score
# Test script for cr-calcom-001: Review a cal.com PR for injected functional bugs and compliance violations

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
fix_hits = 0

# Defect 1: Filter should use state.globalEnabled (not !state.globalEnabled)
service_file = "packages/features/feature-opt-in/services/FeatureOptInService.ts"
if os.path.isfile(service_file):
    with open(service_file) as f:
        service = f.read()
    # Check the filter uses state.globalEnabled without negation
    # Accept multiple filter patterns:
    # (a) .filter((state) => state.globalEnabled) — original with parens
    # (b) .filter(state => state.globalEnabled) — without parens
    # (c) .filter(s => s.globalEnabled) — abbreviated param name
    # (d) .filter(({ globalEnabled }) => globalEnabled) — destructured
    # (e) General: .filter with globalEnabled (without ! negation directly before it)
    defect1_pass = bool(
        re.search(r'\.filter\s*\(\s*\(?\s*\w+\s*\)?\s*=>\s*\w+\.globalEnabled\s*\)', service) or
        re.search(r'\.filter\s*\(\s*\(\s*\{\s*globalEnabled\s*\}\s*\)\s*=>\s*globalEnabled\s*\)', service) or
        re.search(r'\.filter\s*\(\s*function\s*\(\s*\w+\s*\)\s*\{\s*return\s+\w+\.globalEnabled', service)
    )
    # Ensure the negated version is NOT present (the bug was !state.globalEnabled)
    has_negated = bool(
        re.search(r'\.filter\s*\(.*!\s*\w+\.globalEnabled', service)
    )
    if defect1_pass and not has_negated:
        fix_hits += 1
        print("Fix defect-1: PASS (globalEnabled filter restored)", file=sys.stderr)
    elif defect1_pass and has_negated:
        # If both patterns exist, the fix may be partial — still count if positive form exists
        fix_hits += 1
        print("Fix defect-1: PASS (globalEnabled filter restored, negated form also present)", file=sys.stderr)
    else:
        print("Fix defect-1: FAIL (inverted filter not fixed)", file=sys.stderr)
else:
    print(f"Fix defect-1: FAIL ({service_file} not found)", file=sys.stderr)

# Defect 2: isFeatureAllowedForScope should have !config.scope fallback
config_file = "packages/features/feature-opt-in/config.ts"
if os.path.isfile(config_file):
    with open(config_file) as f:
        config = f.read()
    # Accept multiple scope-fallback patterns:
    # (a) !config.scope AND config.scope.includes(scope) — original
    # (b) config.scope == null / config.scope === undefined / !config.scope with .includes
    # (c) config.scope?.includes(scope) — optional chaining (implicitly handles null)
    # (d) config.scope == null || config.scope.includes(scope) — explicit null-or-includes
    # (e) !config.scope || config.scope.includes(scope) — falsy-or-includes
    has_scope_fallback = bool(
        ("!config.scope" in config and "config.scope.includes(scope)" in config) or
        re.search(r'config\.scope\?\.\s*includes\s*\(\s*scope\s*\)', config) or
        re.search(r'config\.scope\s*===?\s*(null|undefined)\s*\|\|', config) or
        re.search(r'!config\.scope\s*\|\|.*config\.scope\.includes', config) or
        re.search(r'config\.scope\s*==\s*null.*\|\|.*includes\s*\(\s*scope', config)
    )
    if has_scope_fallback:
        fix_hits += 1
        print("Fix defect-2: PASS (scope fallback restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (scope fallback not restored)", file=sys.stderr)
else:
    print(f"Fix defect-2: FAIL ({config_file} not found)", file=sys.stderr)

# Defect 3: setUserState should validate with isOptInFeature
router_file = "packages/trpc/server/routers/viewer/featureOptIn/_router.ts"
if os.path.isfile(router_file):
    with open(router_file) as f:
        router = f.read()
    # Find the setUserState mutation and check for feature validation
    # Accept multiple validation patterns:
    # (a) isOptInFeature in the setUserState section — original
    # (b) isValidOptInFeature, isValidFeature — alternative function names
    # (c) validateFeature, validateOptInFeature — alternative naming
    # (d) featureConfig / getOptInFeatureConfig validation before state update
    set_user_idx = router.find("setUserState")
    if set_user_idx >= 0:
        # Check if validation appears between setUserState and the next mutation
        set_team_idx = router.find("setTeamState", set_user_idx)
        section = router[set_user_idx:set_team_idx] if set_team_idx > set_user_idx else router[set_user_idx:]
        has_validation = bool(
            re.search(r'isOptInFeature|isValidOptInFeature|isValidFeature|validateFeature|validateOptInFeature', section) or
            re.search(r'getOptInFeatureConfig\s*\(', section) or
            re.search(r'featureConfig.*\bfeatureId\b', section)
        )
        if has_validation:
            fix_hits += 1
            print("Fix defect-3: PASS (feature validation restored in setUserState)", file=sys.stderr)
        else:
            print("Fix defect-3: FAIL (feature validation not found in setUserState)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (setUserState not found in router)", file=sys.stderr)
else:
    print(f"Fix defect-3: FAIL ({router_file} not found)", file=sys.stderr)

# Defect 4: Policy should come from config, not be hardcoded
if os.path.isfile(service_file):
    # Accept multiple patterns for reading policy from config:
    # (a) getOptInFeatureConfig(featureId) with featureConfig and policy — original
    # (b) getOptInFeatureConfig with any argument (not just featureId)
    # (c) featureConfig.policy or config.policy pattern (reading policy from config object)
    # (d) getFeatureConfig / getConfig function call that retrieves policy
    # Key check: policy should NOT be hardcoded as a string literal default
    has_config_lookup = bool(
        re.search(r'getOptInFeatureConfig\s*\(', service) or
        re.search(r'getFeatureConfig\s*\(', service) or
        re.search(r'(featureConfig|config)\s*\.\s*policy', service)
    )
    has_policy = "policy" in service
    # Check hardcoded policy is removed (the bug)
    has_hardcoded = bool(
        re.search(r'''policy\s*[:=]\s*(?:OptInFeaturePolicy\s*\.\s*)?["']permissive["']''', service)
    )
    if has_config_lookup and has_policy:
        fix_hits += 1
        print("Fix defect-4: PASS (policy read from config)", file=sys.stderr)
    elif has_policy and not has_hardcoded:
        # Policy exists but no config lookup — may use a different approach
        fix_hits += 1
        print("Fix defect-4: PASS (hardcoded policy removed)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (config-based policy lookup not found)", file=sys.stderr)
else:
    print(f"Fix defect-4: FAIL ({service_file} not found)", file=sys.stderr)

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
