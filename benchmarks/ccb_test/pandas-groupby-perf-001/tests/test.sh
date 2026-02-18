#!/bin/bash
# Reward: test_ratio (0.0-1.0) — performance test pass rate
# SWE-Perf Verification Script
# Task: ccb_sweperf-003
# Target: pandas.core.groupby.ops.GroupBy._aggregate_series_fast


# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

set -uo pipefail

echo "=== SWE-Perf Verifier ==="
echo "Task ID: ccb_sweperf-003"
echo "Repository: pandas"
echo "Target Function: pandas.core.groupby.ops.GroupBy._aggregate_series_fast"
echo "Baseline Runtime: 0.095"

# Create output directories
mkdir -p /logs/verifier

# Check for ground truth
if [ ! -f /tests/ground_truth.json ]; then
    echo "ERROR: ground_truth.json not found"
    echo '{"score": 0.0, "error": "Missing ground truth", "runtime_reduction": 0.0}' > /logs/verifier/reward.json
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

# Check for optimized code
OPTIMIZED_DIR="/workspace/optimized"
if [ ! -d "$OPTIMIZED_DIR" ]; then
    echo "WARNING: Optimized directory not found, checking /workspace"
    OPTIMIZED_DIR="/workspace"
fi

# Look for benchmark results
BENCHMARK_RESULTS=""
for path in /workspace/benchmark_results.json /workspace/optimized/benchmark_results.json /logs/benchmark_results.json; do
    if [ -f "$path" ]; then
        BENCHMARK_RESULTS="$path"
        break
    fi
done

echo "Optimized code directory: $OPTIMIZED_DIR"
echo "Benchmark results file: $BENCHMARK_RESULTS"

# Run Python verifier to compute runtime_reduction
python3 /tests/verify.py \
    --optimized-dir "$OPTIMIZED_DIR" \
    --benchmark-results "$BENCHMARK_RESULTS" \
    --ground-truth /tests/ground_truth.json \
    --output /logs/verifier/reward.json \
    2>&1 | tee /logs/verifier/verifier.log

# Extract score and write to reward.txt
if [ -f /logs/verifier/reward.json ]; then
    SCORE=$(python3 -c "import json; print(json.load(open('/logs/verifier/reward.json')).get('score', 0.0))" 2>/dev/null || echo "0.0")
    echo "$SCORE" > /logs/verifier/reward.txt
    echo "Verification complete. Score: $SCORE"
else
    echo "0.0" > /logs/verifier/reward.txt
    echo "Verification failed - no reward.json generated"
fi

# Always exit 0 for Harbor compatibility
exit 0
