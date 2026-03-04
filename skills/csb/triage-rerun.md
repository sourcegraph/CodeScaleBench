# CSB Triage & Rerun Skills

Investigate failed tasks, diagnose root causes, and verify fixes. Use when investigating benchmark failures or rerunning tasks.

**Relevant files:** `scripts/status_fingerprints.py`, `docs/ERROR_CATALOG.md`

---

## Triage Failure

Investigate a failed benchmark task and produce a diagnosis.

### Input

User provides one of:
- Task path: `runs/official/pytorch_opus_.../baseline/.../sgt-005__hash/`
- Suite/config/task: `csb_sdlc_pytorch/baseline/sgt-005`
- Just a task name: `sgt-005`
- Or says "triage the most recent failure"

### Steps

#### 1. Locate the task directory

```bash
cd ~/CodeScaleBench

# If "most recent failure"
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
"
```

#### 2. Read key files in order

- `result.json` — primary source of truth
- `status.json` if it exists
- Agent transcript (last 100 lines of `agent/claude-code.txt`)
- Verifier output (`verifier/test-stdout.txt`, `verifier/reward.txt`)
- Task log

#### 3. Run error fingerprinting

```bash
python3 scripts/status_fingerprints.py "$TASK_DIR/result.json"
```

#### 4. Classify the failure

Categories:
- **infrastructure**: API errors, rate limits, token refresh, network, Docker issues
- **timeout**: Task exceeded time limit
- **verifier_bug**: Error in the verifier/scorer script
- **task_setup**: Missing dependencies, git clone failures, Docker compose issues
- **agent_bug**: Agent produced invalid output format
- **task_difficulty**: Agent tried but task is genuinely hard
- **flaky**: Passed in other configs, failed now with no clear cause
- **mcp_related**: Failure specific to MCP-enabled configs

#### 5. Check for known patterns

Cross-reference with `docs/ERROR_CATALOG.md`.

#### 6. Produce diagnosis

```
## Diagnosis: <task_name>

**Classification**: <category>
**Status**: errored / completed_fail / timeout
**Error**: <one-line summary>
**Root Cause**: <explanation>
**Known Pattern?**: Yes/No

**Evidence**:
- result.json exception: <type + message>
- Agent transcript: <relevant excerpt>
- Verifier output: <relevant excerpt>

**Suggested Fix**:
- File: <path>
- Change: <description>

**Repro Command**:
<harbor run command>

**Cross-config comparison**:
- baseline: <pass/fail/error>
- sourcegraph_full: <pass/fail/error>
```

#### 7. Offer to fix

If code change needed, offer to apply. If infrastructure, provide remediation command.

### Variants

#### Triage agent behavior (not just failures)

For behavior analysis of successful tasks:
1. Read `task_metrics.json` for quantitative overview (MCP ratio, tool calls, timing)
2. Read transcript for qualitative analysis
3. Compare with baseline transcript
4. Produce behavior report with MCP usage classification

---

## Quick Rerun

Run a single benchmark task locally to verify a fix works.

### Steps

#### 1. Resolve the task path

```bash
cd ~/CodeScaleBench
find benchmarks -type d -name "TASKNAME" | head -5
```

#### 2. Determine MCP type

- `none` — baseline, no MCP tools (default, fastest)
- `base` — Sourcegraph base tools
- `deepsearch` — Sourcegraph full

#### 3. Set up environment

```bash
cd ~/CodeScaleBench
source .env.local 2>/dev/null || true
export PYTHONPATH="$(pwd):$PYTHONPATH"
source configs/_common.sh
ensure_fresh_token
```

#### 4. Run the task

```bash
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

#### 5. Check result

```bash
LATEST=$(ls -td /tmp/quick-rerun/*/ 2>/dev/null | head -1)
if [ -z "$LATEST" ]; then
    LATEST=$(ls -td /tmp/quick-rerun/*/*/ 2>/dev/null | head -1)
fi
# Check result.json for pass/fail/error
```

#### 6. Report

- If **pass**: "Fix verified. Ready to commit?"
- If **fail**: Show the new error, offer to triage
- If **error**: Show exception, suggest next steps

### Options

- Use `--model anthropic/claude-opus-4-5-20251101` for production-grade test
- Run verifier only: `bash benchmarks/<suite>/<task_name>/tests/test.sh`
- Clean up: `rm -rf /tmp/quick-rerun`
