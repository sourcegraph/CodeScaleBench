#!/bin/bash
# Reward: checklist (0.0-1.0) — F1 defect detection plus fix quality score
# Test script for cr-ghost-001: Review a Ghost PR for injected functional bugs and compliance violations

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

# Defect 1: NotFoundError guard restored in comments-service.js
svc_file = "ghost/core/core/server/services/comments/comments-service.js"
if os.path.isfile(svc_file):
    with open(svc_file) as f:
        svc = f.read()
    # Accept multiple guard patterns:
    # (a) NotFoundError + commentNotFound + !comment — original exact match
    # (b) NotFoundError with any error message + null/undefined check on comment
    # (c) Different error class (e.g., errors.NotFoundError, GhostError) with comment guard
    # (d) comment === null / comment === undefined / !comment / comment == null
    has_error = bool(
        re.search(r'NotFoundError|GhostError.*not\s*found', svc, re.IGNORECASE)
    )
    has_guard = bool(
        re.search(r'!comment\b|comment\s*===?\s*(null|undefined)|comment\s*==\s*null', svc)
    )
    has_error_msg = bool(
        re.search(r'commentNotFound|comment.*not\s*found|Comment\s*not\s*found', svc, re.IGNORECASE)
    )
    if has_error and has_guard:
        fix_hits += 1
        print("Fix defect-1: PASS (NotFoundError guard restored)", file=sys.stderr)
    elif has_guard and has_error_msg:
        # Guard exists with an error message but maybe different error class
        fix_hits += 1
        print("Fix defect-1: PASS (comment null guard with error restored)", file=sys.stderr)
    else:
        print("Fix defect-1: FAIL (NotFoundError guard not found)", file=sys.stderr)
else:
    print(f"Fix defect-1: FAIL ({svc_file} not found)", file=sys.stderr)

# Defect 2: frame.options.id restored in comments-controller.js
ctrl_file = "ghost/core/core/server/services/comments/comments-controller.js"
if os.path.isfile(ctrl_file):
    with open(ctrl_file) as f:
        ctrl = f.read()
    # Accept multiple patterns for restoring the id from frame options:
    # (a) frame.options.id — original exact match
    # (b) frame.options?.id — optional chaining variant
    # (c) frame.data.id or frame.params.id — alternative property paths
    # (d) Destructured: { id } = frame.options or const id = frame.options.id
    has_frame_id = bool(
        re.search(r'frame\.options\.id|frame\.options\?\.\s*id', ctrl) or
        re.search(r'frame\.(data|params)\.id', ctrl) or
        re.search(r'\{\s*id\s*\}\s*=\s*frame\.options', ctrl) or
        re.search(r'(?:const|let|var)\s+id\s*=\s*frame\.options\.id', ctrl)
    )
    if has_frame_id:
        fix_hits += 1
        print("Fix defect-2: PASS (frame.options.id restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (frame.options.id not found)", file=sys.stderr)
else:
    print(f"Fix defect-2: FAIL ({ctrl_file} not found)", file=sys.stderr)

# Defect 3: cacheInvalidate: false restored in comment-likes.js
ep_file = "ghost/core/core/server/api/endpoints/comment-likes.js"
if os.path.isfile(ep_file):
    with open(ep_file) as f:
        ep = f.read()
    # Accept multiple cache invalidation patterns:
    # (a) cacheInvalidate — original (any reference to cache invalidation config)
    # (b) cache_invalidate — snake_case variant
    # (c) CacheInvalidate — PascalCase variant
    # (d) cache-invalidate — kebab-case in string
    has_cache_config = bool(
        re.search(r'cacheInvalidate|cache_invalidate|CacheInvalidate|cache-invalidate', ep)
    )
    if has_cache_config:
        fix_hits += 1
        print("Fix defect-3: PASS (cacheInvalidate header restored)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (cacheInvalidate not found)", file=sys.stderr)
else:
    print(f"Fix defect-3: FAIL ({ep_file} not found)", file=sys.stderr)

# Defect 4: withRelated: ['member'] restored in comments-service.js
if os.path.isfile(svc_file):
    # Accept multiple patterns for member relation inclusion:
    # (a) 'member' or "member" — original string literal check
    # (b) withRelated containing member in any array syntax
    # (c) Template literal `member`
    # (d) Variable reference like MEMBER_RELATION or memberRelation
    has_member = bool(
        "'member'" in svc or
        '"member"' in svc or
        re.search(r'`member`', svc) or
        re.search(r'withRelated.*member', svc, re.IGNORECASE) or
        re.search(r'(MEMBER_RELATION|memberRelation)', svc)
    )
    if has_member:
        fix_hits += 1
        print("Fix defect-4: PASS (member relation restored)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (member relation not found in withRelated)", file=sys.stderr)
else:
    print(f"Fix defect-4: FAIL ({svc_file} not found)", file=sys.stderr)

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
