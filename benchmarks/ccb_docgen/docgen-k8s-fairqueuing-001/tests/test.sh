#!/bin/bash
# Reward: checklist (0.0-1.0) with hallucination penalties only
# Canonical ground-truth content should score 1.0.

set -e

DOC="/workspace/documentation.md"
GROUND_TRUTH="/tests/ground_truth.json"
REWARD_FILE="/logs/verifier/reward.txt"

mkdir -p /logs/verifier

if [ ! -f "$GROUND_TRUTH" ]; then
    echo "ERROR: ground_truth.json not found at $GROUND_TRUTH"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

if [ ! -f "$DOC" ]; then
    echo "No documentation found at $DOC"
    echo "0.0" > "$REWARD_FILE"
    exit 0
fi

python3 << 'PYEOF'
import hashlib
import json
import re
from pathlib import Path

DOC_PATH = Path('/workspace/documentation.md')
GT_PATH = Path('/tests/ground_truth.json')
REWARD_PATH = Path('/logs/verifier/reward.txt')

text = DOC_PATH.read_text(errors='ignore')
gt = json.loads(GT_PATH.read_text())

# Canonical human-authored source should always score 1.0 when provided verbatim.
doc_sha = hashlib.sha256(text.encode("utf-8")).hexdigest().lower()
canonical_sha = ((((gt.get("ground_truth_provenance") or {}).get("canonical_source") or {}).get("sha256") or "").lower())
if canonical_sha and doc_sha == canonical_sha:
    print("Canonical source SHA match: awarding 1.0")
    REWARD_PATH.write_text("1.00\n")
    raise SystemExit(0)


def check_any(patterns, body):
    for p in patterns:
        try:
            if re.search(p, body, re.IGNORECASE | re.DOTALL):
                return True
        except re.error:
            if p.lower() in body.lower():
                return True
    return False


def check_all(patterns, body):
    for p in patterns:
        try:
            if not re.search(p, body, re.IGNORECASE | re.DOTALL):
                return False
        except re.error:
            if p.lower() not in body.lower():
                return False
    return True


def ratio(items, all_patterns=False):
    score = 0.0
    total = 0.0
    for it in items:
        w = float(it.get('weight', 0.0))
        total += w
        ok = check_all(it.get('patterns', []), text) if all_patterns else check_any(it.get('patterns', []), text)
        if ok:
            score += w
    return (score / total) if total > 0 else 0.0

# Base checklist score (content-grounded only)
r_topics = ratio(gt.get('required_topics', []))
r_refs = ratio(gt.get('file_references', []))
r_flow = ratio(gt.get('data_flow', []), all_patterns=True)
r_ext = ratio(gt.get('extension_points', []))

w = gt.get('weights', {})
base = (
    r_topics * float(w.get('required_topics', 0.4)) +
    r_refs * float(w.get('file_references', 0.25)) +
    r_flow * float(w.get('data_flow', 0.2)) +
    r_ext * float(w.get('extension_points', 0.15))
)

# Hallucination penalty: invalid path mentions only.
penalty = 0.0
path_candidates = set(re.findall(r"(?:staging/src|pkg|cmd|api)/[A-Za-z0-9_./-]+\.go", text))
invalid = 0
for p in path_candidates:
    if not Path('/workspace', p).exists():
        invalid += 1
if path_candidates:
    invalid_ratio = invalid / len(path_candidates)
    penalty += min(0.35, invalid_ratio * 0.5)

final = max(0.0, min(1.0, base - penalty))

print('=== Score Breakdown ===')
print(f'base: {base:.3f}')
print(f'  topics={r_topics:.3f} refs={r_refs:.3f} flow={r_flow:.3f} ext={r_ext:.3f}')
print('=== Hallucination Check ===')
print(f'path_candidates={len(path_candidates)} invalid_paths={invalid} penalty={penalty:.3f}')
print(f'FINAL={final:.3f}')

REWARD_PATH.write_text(f"{final:.2f}\n")
PYEOF
