---
name: triage-failure
description: Investigate a specific failed benchmark task — read logs, identify root cause, check if known pattern, suggest fix. Triggers on triage, investigate failure, debug task, diagnose failure.
user-invocable: true
---

# Triage Failure

Investigate a failed benchmark task and produce a diagnosis.

## Input

User provides one of:
- Task path: `runs/official/pytorch_opus_.../baseline/.../sgt-005__hash/`
- Suite/config/task: `csb_sdlc_pytorch/baseline/sgt-005`
- Just a task name: `sgt-005` (will search for it)
- Or says "triage the most recent failure"

## Steps

### 1. Locate the task directory

If user gave a full path, use it directly. Otherwise, find it:

```bash
cd ~/CodeScaleBench

# If "most recent failure" — get failures from aggregate_status.py
python3 scripts/aggregate_status.py --failures-only --format json | python3 -c "
import sys, json
data = json.load(sys.stdin)
tasks = [t for t in data['tasks'] if t['status'] in ('errored', 'completed_fail', 'timeout')]
tasks.sort(key=lambda t: t.get('dir_mtime', ''), reverse=True)
if tasks:
    t = tasks[0]
    print(f'Task: {t[\"task_name\"]}')
    print(f'Suite: {t[\"suite\"]}')
    print(f'Config: {t[\"config\"]}')
    print(f'Status: {t[\"status\"]}')
    print(f'Dir: {t[\"task_dir\"]}')
else:
    print('No failures found')
"
```

If user gave a task name, search for it:
```bash
# Find all dirs matching the task name
find runs/official -type d -name "*TASKNAME*" | head -10
```

### 2. Read key files in order

Read the files in the task directory to understand what happened:

```bash
TASK_DIR="<resolved path>"

# 1. result.json — primary source of truth
cat "$TASK_DIR/result.json" | python3 -m json.tool

# 2. status.json if it exists (from aggregate_status --write-status)
cat "$TASK_DIR/status.json" 2>/dev/null | python3 -m json.tool

# 3. Agent transcript (last 100 lines)
tail -100 "$TASK_DIR/agent/claude-code.txt" 2>/dev/null

# 4. Verifier output
cat "$TASK_DIR/verifier/test-stdout.txt" 2>/dev/null | tail -50
cat "$TASK_DIR/verifier/reward.txt" 2>/dev/null

# 5. Task log
cat "$TASK_DIR/../$(basename $TASK_DIR | sed 's/__.*//').log" 2>/dev/null | tail -50
```

### 3. Run error fingerprinting

```bash
python3 scripts/status_fingerprints.py "$TASK_DIR/result.json"
```

### 4. Classify the failure

Categorize into one of:
- **infrastructure**: API errors, rate limits, token refresh, network, Docker issues
- **timeout**: Task exceeded time limit (check if agent was stuck or task is inherently slow)
- **verifier_bug**: Error in the verifier/scorer script (KeyError, parse error, etc.)
- **task_setup**: Missing dependencies, git clone failures, Docker compose issues
- **agent_bug**: Agent produced invalid output format or took wrong approach
- **task_difficulty**: Agent tried but task is genuinely hard (completed_fail with effort)
- **flaky**: Passed in other configs or previous runs, failed now with no clear cause
- **mcp_related**: Failure specific to MCP-enabled configs

### 5. Check for known patterns

```bash
# Check error catalog
cat ~/CodeScaleBench/docs/ERROR_CATALOG.md
```

Cross-reference the error with known patterns in the catalog.

### 6. Produce diagnosis

Present findings in this format:

```
## Diagnosis: <task_name>

**Classification**: <category from step 4>
**Status**: errored / completed_fail / timeout
**Error**: <one-line summary of what went wrong>
**Root Cause**: <explanation of why it failed>
**Known Pattern?**: Yes (see ERROR_CATALOG.md#section) / No

**Evidence**:
- result.json exception: <type + message>
- Agent transcript: <relevant excerpt>
- Verifier output: <relevant excerpt>

**Suggested Fix**:
- File: <path to file that needs changing>
- Change: <description of the fix>

**Repro Command**:
```bash
cd ~/CodeScaleBench
# For baseline
BASELINE_MCP_TYPE=none harbor run \
    --path benchmarks/<suite>/<task> \
    --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
    --model anthropic/claude-opus-4-5-20251101 \
    --jobs-dir runs/official/<run_dir>/<config> \
    -n 1
```

**Cross-config comparison**:
- baseline: <pass/fail/error>
- sourcegraph_full: <pass/fail/error>
```

### 7. Offer to fix

If the fix is a code change (verifier bug, task setup issue), offer to apply it.
If it's infrastructure, provide the remediation command.

## Variants

### Triage all failures in a suite
```bash
python3 scripts/aggregate_status.py --suite csb_sdlc_pytorch --failures-only --format json
```
Then triage each one.

### Triage by error type
```bash
python3 scripts/aggregate_status.py --failures-only --format json | python3 -c "
import sys, json
data = json.load(sys.stdin)
for t in data['tasks']:
    fp = t.get('error_fingerprint') or {}
    if fp.get('fingerprint_id') == 'token_refresh_403':
        print(f\"{t['suite']}/{t['config']}/{t['task_name']}: {t['task_dir']}\")
"
```

### Triage agent behavior (not just failures)

Sometimes you need to investigate **unexpected behavior in successful tasks** — e.g., "why didn't the agent use MCP?" or "why did it spend 40% of time on search?"

For behavior analysis of a successful task:

#### 1. Locate the task directory (same as failure triage)

#### 2. Read task_metrics.json for quantitative overview
```bash
cat "$TASK_DIR/task_metrics.json" | python3 -m json.tool
```

Key fields to check:
- `tool_calls_mcp` / `tool_calls_total` → MCP ratio (0 = zero-MCP)
- `mcp_ratio` → fraction of tool calls that are MCP
- `tool_calls_by_name` → which specific tools were used
- `search_strategy_type` → keyword-only, mixed, nls-heavy, etc.
- `agent_execution_seconds` → time spent vs baseline

#### 3. Read the transcript for qualitative analysis
Use the Read tool on `$TASK_DIR/agent/claude-code.txt` to understand the agent's decision flow:
- Did the agent attempt MCP and fail, or never try?
- Did it use Task subagents that made MCP calls? (check for `"tool": "Task"` blocks)
- Did it backtrack or retry after MCP results?
- Was MCP usage productive (did it inform the solution) or wasteful (searched then ignored results)?

#### 4. Compare with baseline transcript
Read the baseline transcript for the same task to see how the agent approached it without MCP.

#### 5. Produce behavior report

```
## Behavior Analysis: <task_name>

**Config**: sourcegraph_full
**Reward**: X (baseline: Y, delta: Z)
**MCP Usage**: N calls (ratio: X%)
**Agent Time**: X sec (baseline: Y sec, delta: Z%)

**Tool Usage Pattern**:
- MCP tools: keyword_search (N), read_file (N), ...
- Local tools: Read (N), Bash (N), Edit (N), ...

**Behavior Classification**:
- [ ] MCP-productive: MCP results directly informed the solution
- [ ] MCP-wasteful: Searched but ignored results
- [ ] MCP-distracted: Spent time on MCP instead of implementing
- [ ] Zero-MCP rational: Task doesn't benefit from remote search
- [ ] Zero-MCP problematic: Should have used MCP but didn't

**Key Observations**:
- <what the agent did and why>
```

This variant is useful for:
- Investigating zero-MCP tasks flagged by `/mcp-audit`
- Understanding MCP distraction effects (TAC, SWE-Perf)
- Validating that MCP wins are genuine (not just lucky non-determinism)
