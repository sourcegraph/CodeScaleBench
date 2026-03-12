---
name: quick-rerun
description: Run a single benchmark task locally to verify a fix. Uses haiku for speed. Triggers on quick rerun, rerun task, verify fix, test task.
user-invocable: true
---

# Quick Rerun

Run a single benchmark task with minimal settings to verify a fix works.

## Input

User provides:
- A benchmark task path: `benchmarks/csb_sdlc_pytorch/sgt-005`
- Or a task from a failed run to re-test: `sgt-005`
- Or says "rerun the task I just fixed"

## Steps

### 1. Resolve the task path

If user gave a task name, find the benchmark path:

```bash
cd ~/CodeScaleBench
# Find the task definition
find benchmarks -type d -name "TASKNAME" | head -5
```

### 2. Determine the MCP type

Ask the user or infer from context:
- `none` — baseline, no MCP tools
- `base` — Sourcegraph base tools (keyword search)
- `deepsearch` — Sourcegraph full (keyword + deep search)

Default to `none` (baseline) for fastest verification.

### 3. Set up environment

```bash
cd ~/CodeScaleBench

# Load credentials
source .env.local 2>/dev/null || true

# Set up Python path for agent (agents/ is in the project root)
export PYTHONPATH="$(pwd):$PYTHONPATH"

# Refresh token if needed
source configs/_common.sh
ensure_fresh_token
```

### 4. Run the task

```bash
cd ~/CodeScaleBench

# Baseline (no MCP) — fastest
BASELINE_MCP_TYPE=none harbor run \
    --path benchmarks/<suite>/<task_name> \
    --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
    --model anthropic/claude-haiku-4-5-20251001 \
    --jobs-dir /tmp/quick-rerun \
    -n 1 \
    --timeout-multiplier 1.0 \
    2>&1 | tee /tmp/quick-rerun.log
```

For MCP-Full:
```bash
BASELINE_MCP_TYPE=sourcegraph_full harbor run \
    --path benchmarks/<suite>/<task_name> \
    --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
    --model anthropic/claude-haiku-4-5-20251001 \
    --jobs-dir /tmp/quick-rerun \
    -n 1 \
    2>&1 | tee /tmp/quick-rerun.log
```

### 5. Check result

```bash
# Find the most recent task output
LATEST=$(ls -td /tmp/quick-rerun/*/ 2>/dev/null | head -1)

if [ -z "$LATEST" ]; then
    # Check for batch dir layout
    LATEST=$(ls -td /tmp/quick-rerun/*/*/ 2>/dev/null | head -1)
fi

echo "Task dir: $LATEST"

# Check result.json
if [ -f "$LATEST/result.json" ]; then
    python3 -c "
import json
data = json.load(open('$LATEST/result.json'))
exc = data.get('exception_info')
vr = data.get('verifier_result') or {}
rewards = vr.get('rewards') or {}
reward = rewards.get('reward', rewards.get('score'))
if exc:
    exc_msg = exc.get('exception_message', exc.get('message', str(exc)[:100])) if isinstance(exc, dict) else str(exc)[:100]
    print(f'ERRORED: {exc_msg}')
elif reward is not None and reward > 0:
    print(f'PASS (reward={reward})')
else:
    print(f'FAIL (reward={reward})')
"
else
    echo "No result.json found — task may still be running or crashed early"
    echo "Log tail:"
    tail -20 /tmp/quick-rerun.log 2>/dev/null
fi
```

### 6. Report result

- If **pass**: "Fix verified. Ready to commit?" and offer to run with the full model (opus) if needed.
- If **fail**: "Still failing. Here's the new error: ..." and offer to triage.
- If **error**: Show the exception and suggest next steps.

## Options

### Use full model instead of haiku
If the user wants a more realistic test:
```bash
# Use opus for production-grade verification
--model anthropic/claude-opus-4-5-20251101
```

### Run verifier only
If the fix was to the verifier/test.sh and you just want to re-check scoring:
```bash
cd <task_dir>
bash benchmarks/<suite>/<task_name>/tests/test.sh
```

### Clean up
```bash
rm -rf /tmp/quick-rerun
```
