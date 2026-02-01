#!/bin/bash
# DI-Bench Python Validator Test Script
# Replaces Docker-in-Docker CI/CD execution with Python dependency validation

set -e

cd /app/repo

# Create logs directory for Harbor
mkdir -p /logs/verifier

# Run Python-based validation
python3 << 'EOF'
import sys
import json
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, '/app')

try:
    from validators import validate_task
    
    repo_path = Path('/app/repo')
    language = '{language}'
    
    print(f"Validating {language} project in {repo_path}")
    is_valid, errors = validate_task(language, repo_path)
    
    # Log results
    if is_valid:
        print("✓ Validation passed!")
        reward = 1
    else:
        print("✗ Validation failed:")
        for error in errors:
            print(f"  - {error}")
        reward = 0
    
    # Write reward for Harbor
    with open('/logs/verifier/reward.txt', 'w') as f:
        f.write(str(reward))
    
    sys.exit(0)
    
except ImportError:
    print("✗ Could not import validators module")
    with open('/logs/verifier/reward.txt', 'w') as f:
        f.write('0')
    sys.exit(0)
except Exception as e:
    print(f"✗ Error during validation: {e}")
    with open('/logs/verifier/reward.txt', 'w') as f:
        f.write('0')
    sys.exit(0)
EOF
