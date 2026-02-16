#!/bin/bash
# Reward: checklist (0.0-1.0) — F1 defect detection plus fix quality score
# Test script for cr-security-002: Review Kafka for injected security-adjacent defects
# Security defects (critical/high) are weighted 2x in fix scoring

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
# 50% fix score (proportion of defects with correct code fixes, security 2x weight)

EXPECTED_DEFECTS="/tests/expected_defects.json"
REVIEW_JSON="/workspace/review.json"

FINAL_SCORE=$(python3 - "$EXPECTED_DEFECTS" "$REVIEW_JSON" <<'PYEOF'
import json, sys, os, re

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

# ── Fix scoring (security-weighted) ──────────────────────
# Check if agent's code changes contain the expected fix patterns
# Security-critical defects (critical/high) are weighted 2x
fix_results = {}  # defect_id -> (passed, weight)

# Defect 1 (critical, 2x): Iteration count check restored (< not >)
scram_file = "clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java"
if os.path.isfile(scram_file):
    with open(scram_file) as f:
        scram_code = f.read()
    defect1_pass = False
    # Pattern A: iterations() < mechanism.minIterations() (correct check)
    if re.search(r'scramCredential\.iterations\(\)\s*<\s*mechanism\.minIterations\(\)', scram_code):
        defect1_pass = True
        # Verify the buggy pattern (>) is NOT present
        if re.search(r'scramCredential\.iterations\(\)\s*>\s*mechanism\.minIterations\(\)', scram_code):
            defect1_pass = False
    fix_results["defect-1"] = (defect1_pass, SECURITY_WEIGHT)
    if defect1_pass:
        print("Fix defect-1: PASS (iteration count check uses <)", file=sys.stderr)
    else:
        print("Fix defect-1: FAIL (iteration count check not restored to <)", file=sys.stderr)
else:
    fix_results["defect-1"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-1: FAIL ({scram_file} not found)", file=sys.stderr)

# Defect 2 (critical, 2x): Timing-safe MessageDigest.isEqual restored
if os.path.isfile(scram_file):
    defect2_pass = False
    # Find verifyClientProof function
    vcp_idx = scram_code.find("verifyClientProof")
    if vcp_idx >= 0:
        vcp_func = scram_code[vcp_idx:vcp_idx+600]
        # Pattern A: MessageDigest.isEqual(computedStoredKey, expectedStoredKey)
        if re.search(r'MessageDigest\.isEqual\s*\(\s*computedStoredKey\s*,\s*expectedStoredKey\s*\)', vcp_func):
            defect2_pass = True
        # Pattern B: MessageDigest.isEqual(expectedStoredKey, computedStoredKey) (reversed args)
        if not defect2_pass and re.search(r'MessageDigest\.isEqual\s*\(\s*expectedStoredKey\s*,\s*computedStoredKey\s*\)', vcp_func):
            defect2_pass = True
        # Verify Arrays.equals is NOT present (buggy pattern)
        if defect2_pass and re.search(r'Arrays\.equals\s*\(\s*(computedStoredKey|expectedStoredKey)', vcp_func):
            defect2_pass = False
    fix_results["defect-2"] = (defect2_pass, SECURITY_WEIGHT)
    if defect2_pass:
        print("Fix defect-2: PASS (MessageDigest.isEqual restored)", file=sys.stderr)
    else:
        print("Fix defect-2: FAIL (timing-safe comparison not found)", file=sys.stderr)
else:
    fix_results["defect-2"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-2: FAIL ({scram_file} not found)", file=sys.stderr)

# Defect 3 (high, 2x): Session expiration time calculation restored
sasl_server_file = "clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java"
if os.path.isfile(sasl_server_file):
    with open(sasl_server_file) as f:
        sasl_server_code = f.read()
    defect3_pass = False
    # Pattern A: sessionExpirationTimeNanos = authenticationEndNanos + 1000 * 1000 * retvalSessionLifetimeMs
    if re.search(r'sessionExpirationTimeNanos\s*=\s*authenticationEndNanos\s*\+\s*1000\s*\*\s*1000\s*\*\s*retvalSessionLifetimeMs', sasl_server_code):
        defect3_pass = True
    # Verify the commented-out pattern is NOT present
    if defect3_pass and re.search(r'//\s*sessionExpirationTimeNanos\s*=\s*authenticationEndNanos', sasl_server_code):
        defect3_pass = False
    fix_results["defect-3"] = (defect3_pass, SECURITY_WEIGHT)
    if defect3_pass:
        print("Fix defect-3: PASS (session expiration calculation restored)", file=sys.stderr)
    else:
        print("Fix defect-3: FAIL (session expiration not restored)", file=sys.stderr)
else:
    fix_results["defect-3"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-3: FAIL ({sasl_server_file} not found)", file=sys.stderr)

# Defect 4 (critical, 2x): DENY ACL negation restored
acl_file = "core/src/main/scala/kafka/security/authorizer/AclAuthorizer.scala"
if os.path.isfile(acl_file):
    with open(acl_file) as f:
        acl_code = f.read()
    defect4_pass = False
    # Find aclsAllowAccess definition
    aaa_idx = acl_code.find("def aclsAllowAccess")
    if aaa_idx >= 0:
        aaa_func = acl_code[aaa_idx:aaa_idx+500]
        # Pattern A: !denyAclExists(acls) && allowAclExists(acls)
        if re.search(r'!\s*denyAclExists\s*\(\s*acls\s*\)\s*&&\s*allowAclExists\s*\(\s*acls\s*\)', aaa_func):
            defect4_pass = True
        # Verify the buggy pattern (no negation) is NOT present
        if defect4_pass and re.search(r'(?<!\!)\s*denyAclExists\s*\(\s*acls\s*\)\s*&&\s*allowAclExists', aaa_func):
            defect4_pass = False
    fix_results["defect-4"] = (defect4_pass, SECURITY_WEIGHT)
    if defect4_pass:
        print("Fix defect-4: PASS (DENY ACL negation restored)", file=sys.stderr)
    else:
        print("Fix defect-4: FAIL (DENY ACL negation not found)", file=sys.stderr)
else:
    fix_results["defect-4"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-4: FAIL ({acl_file} not found)", file=sys.stderr)

# Defect 5 (high, 2x): Credential class type validation restored
cred_cache_file = "clients/src/main/java/org/apache/kafka/common/security/authenticator/CredentialCache.java"
if os.path.isfile(cred_cache_file):
    with open(cred_cache_file) as f:
        cred_cache_code = f.read()
    defect5_pass = False
    # Find cache() method
    cache_idx = cred_cache_code.find("public <C> Cache<C> cache(String mechanism")
    if cache_idx >= 0:
        cache_func = cred_cache_code[cache_idx:cache_idx+500]
        # Pattern A: if (cache.credentialClass() != credentialClass)
        if re.search(r'if\s*\(\s*cache\.credentialClass\(\)\s*!=\s*credentialClass\s*\)', cache_func):
            defect5_pass = True
        # Pattern B: credentialClass != cache.credentialClass() (reversed)
        if not defect5_pass and re.search(r'if\s*\(\s*credentialClass\s*!=\s*cache\.credentialClass\(\)\s*\)', cache_func):
            defect5_pass = True
        # Verify the commented-out pattern is NOT present
        if defect5_pass and re.search(r'//\s*if\s*\(\s*cache\.credentialClass', cache_func):
            defect5_pass = False
    fix_results["defect-5"] = (defect5_pass, SECURITY_WEIGHT)
    if defect5_pass:
        print("Fix defect-5: PASS (credential class validation restored)", file=sys.stderr)
    else:
        print("Fix defect-5: FAIL (credential class validation not found)", file=sys.stderr)
else:
    fix_results["defect-5"] = (False, SECURITY_WEIGHT)
    print(f"Fix defect-5: FAIL ({cred_cache_file} not found)", file=sys.stderr)

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
