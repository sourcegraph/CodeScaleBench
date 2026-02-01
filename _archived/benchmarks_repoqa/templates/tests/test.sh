#!/bin/bash
# RepoQA Verification Script
# Verifies agent solution against ground truth

echo "Starting RepoQA verifier..." 1>&2

cd /app || { echo "ERROR: Cannot cd to /app"; exit 1; }

# Create logs directory for Harbor
mkdir -p /logs/verifier || { echo "ERROR: Cannot create /logs/verifier"; exit 1; }

echo "=========================================="
echo "RepoQA Verifier"
echo "Task Variant: {task_variant}"
echo "=========================================="

# DEBUG: Check what directories exist
echo "DEBUG: Checking directories..."
ls -la /logs/ 2>&1 || echo "Cannot list /logs"
echo "Creating /logs/verifier if needed..."
mkdir -p /logs/verifier 2>&1 || echo "Cannot create /logs/verifier"

# Ground truth is uploaded by Harbor to /tests/ground_truth.json
echo "DEBUG: Checking for /tests/ground_truth.json..."
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: No ground_truth.json found at /tests/ground_truth.json"
    echo "Contents of /tests:"
    ls -la /tests/ || echo "Cannot list /tests"
    echo '{"score": 0.0}' > /logs/verifier/reward.json
    echo "DEBUG: Wrote error reward to /logs/verifier/reward.json"
    exit 0
fi
echo "DEBUG: Found /tests/ground_truth.json"

# The agent writes solution.json to /app/ (shared mount between agent and verifier)
SOLUTION_FILE="/app/solution.json"

if [ ! -f "$SOLUTION_FILE" ]; then
    echo "ERROR: Agent did not create solution.json in /app/"
    echo "The agent must run: cat > /app/solution.json << 'JSONEOF' ... JSONEOF"
    echo "Contents of /app:"
    ls -la /app/ | head -20
    echo '{"score": 0.0}' > /logs/verifier/reward.json
    exit 0
fi
echo "DEBUG: Found /app/solution.json"

# Run verifier - execute Python with /app in path
echo "DEBUG: Creating /tmp/verify.py..."
cat > /tmp/verify.py << 'PYEOF'
import json
import sys
from pathlib import Path

# Add /tests to path to find verifier module (Harbor mounts tests dir)
sys.path.insert(0, '/tests')

# Import verifiers
from verifiers import SemanticRetrievalQAVerifier

try:
    # Load ground truth
    with open('/tests/ground_truth.json') as f:
        ground_truth = json.load(f)
    
    # Load agent output
    with open('/app/solution.json') as f:
        agent_output = json.load(f)
    
    # Verify
    verifier = SemanticRetrievalQAVerifier(ground_truth)
    result = verifier.verify(agent_output)
    
    # Build reward
    reward = {'score': float(result.correct_function)}
    
    # Log results
    print(f'Verification Results:')
    print(f'  Correct Function: {result.correct_function:.2f}')
    print(f'  Correct Path: {result.correct_path:.2f}') 
    print(f'  Justification: {result.justification_score:.2f}')
    print(f'  Details: {result.reasoning}')
    
    # Write reward
    with open('/logs/verifier/reward.json', 'w') as f:
        json.dump(reward, f, indent=2)

except Exception as e:
    import traceback
    print(f'ERROR: Verification failed: {e}')
    traceback.print_exc()
    reward = {'score': 0.0}
    with open('/logs/verifier/reward.json', 'w') as f:
        json.dump(reward, f, indent=2)
PYEOF

echo "DEBUG: Created /tmp/verify.py, now running python3..."
python3 /tmp/verify.py 2>&1 | tee /logs/verifier/verify-debug.log
PYTHON_EXIT_CODE=$?
echo "DEBUG: Python3 completed with exit code: $PYTHON_EXIT_CODE"
if [ $PYTHON_EXIT_CODE -ne 0 ]; then
    echo "ERROR: Python verification script failed with code $PYTHON_EXIT_CODE"
    echo "See /logs/verifier/verify-debug.log for details"
fi

# Ensure proper permissions
chmod 664 /logs/verifier/reward.json 2>/dev/null || true

# Always exit 0 for Harbor compatibility
exit 0
