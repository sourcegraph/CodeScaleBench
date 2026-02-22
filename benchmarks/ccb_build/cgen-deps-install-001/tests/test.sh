#!/bin/bash
# Reward: binary (0.0-1.0) — dependency installation pass or fail
# DI-Bench validator test for ccb_dibench-python-inducer-cgen
set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
# Artifact mode: parse answer.json, extract analysis text, apply diffs
if [ -f /tmp/.artifact_only_mode ] && [ -f /tests/answer_json_verifier_lib.sh ]; then
    source /tests/answer_json_verifier_lib.sh
fi


REWARD_FILE="/logs/verifier/reward.txt"
mkdir -p /logs/verifier

cd /app/repo

python3 << 'EOF'
import sys
sys.path.insert(0, '/tests')

from validators import validate_task
from pathlib import Path

repo_path = Path('/app/repo')
language = 'python'

print(f"Validating {language} project dependencies...")
is_valid, errors = validate_task(language, repo_path)

if is_valid:
    print("PASS: Dependency validation succeeded")
    with open('/logs/verifier/reward.txt', 'w') as f:
        f.write('1.0\n')
    sys.exit(0)
else:
    print("FAIL: Dependency validation failed:")
    for error in errors:
        print(f"  - {error}")
    with open('/logs/verifier/reward.txt', 'w') as f:
        f.write('0.0\n')
    sys.exit(1)
EOF
