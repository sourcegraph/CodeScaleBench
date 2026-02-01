#!/bin/bash
# DI-Bench validator test for dibench-csharp-irongut-codecoveragesummary
set -e

cd /app/repo

python3 << 'EOF'
import sys
sys.path.insert(0, '/app')

from validators import validate_task
from pathlib import Path

repo_path = Path('/app/repo')
language = 'csharp'

print(f"Validating {language} project dependencies...")
is_valid, errors = validate_task(language, repo_path)

if is_valid:
    print("PASS: Dependency validation succeeded")
    sys.exit(0)
else:
    print("FAIL: Dependency validation failed:")
    for error in errors:
        print(f"  - {error}")
    sys.exit(1)
EOF
