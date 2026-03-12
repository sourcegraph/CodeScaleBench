---
name: whats-next
description: Analyze current benchmark state and recommend what to work on next. Triggers on whats next, what should I do, next steps, prioritize work.
user-invocable: true
---

# What's Next

Analyze the current state of benchmark runs and recommend the highest-value next action.

## Steps

### 1. Get current status with gap analysis

```bash
cd ~/CodeScaleBench && python3 scripts/aggregate_status.py --gap-analysis --format json
```

### 2. Get config comparison

```bash
cd ~/CodeScaleBench && python3 scripts/compare_configs.py --format json
```

### 3. Categorize the situation and recommend

Based on the data, present recommendations using ALL applicable scenarios below. Always check for gaps first.

#### Priority 0: Missing runs (gap analysis)

If `gap_analysis.total_missing > 0`, this is the **highest priority** — we can't analyze what doesn't exist.

- Show total missing task runs vs expected
- Group by config (SG_full gaps are most critical since those are rerun-dependent)
- For each suite with gaps, show: suite name, config, count missing
- Suggest the appropriate `*_3config.sh` script to run, or specific rerun commands
- Note: SG_full gaps are likely from archived DS-compromised runs that need rerun with the DS retry preamble

#### If runs are still in progress

Report:
- How many tasks are still running
- How many have completed so far (pass/fail/error)
- Suggest triaging any existing failures while waiting

#### If there are failures, prioritize by impact

**Priority 1: Infrastructure errors** (token refresh, API errors)
These block everything. Fix first.
- Show count and type
- Provide the fix command (e.g., refresh token, reduce parallelism)
- Suggest rerunning failed tasks after fix:
  ```bash
  python3 scripts/rerun_failed.py --filter token_refresh_403
  ```

**Priority 2: All-fail tasks** (adapter/verifier bugs)
These are broken everywhere — fixing helps all configs.
- List the tasks and their error type
- Suggest triaging each one: `/triage-failure <task>`

**Priority 3: Divergent tasks** (some configs pass, some fail)
These reveal MCP signal but are lower priority to fix.
- List tasks where MCP helps (baseline fails, MCP passes)
- List tasks where MCP hurts (baseline passes, MCP fails)
- Suggest investigating the "MCP hurts" cases first (potential regressions)

**Priority 4: Config-specific failures**
- Note any patterns (e.g., "all SG_full failures are on K8s tasks")

#### If paired reruns completed

After paired_rerun batches finish (BL + SF on same VM), recommend analysis:
- Run `/mcp-audit` to analyze MCP usage patterns and reward/time deltas
- Run `/reextract-metrics` if any extraction bugs were recently fixed
- Check zero-MCP rate — if >30% for a benchmark, MCP may not suit that task type

#### If extraction bugs were fixed

After changes to `extract_task_metrics.py` or `csb_metrics/extractors.py`:
- Run `/reextract-metrics` to batch-update all task_metrics.json files
- Then regenerate MANIFEST: `python3 scripts/generate_manifest.py`
- Then re-run analysis skills (`/mcp-audit`, `/evaluate-traces`) with corrected data

#### If all tasks are passing

Great state. Recommend:
- Run `/compare-configs` for divergence analysis
- Run `/mcp-audit` for MCP-conditioned reward/time analysis
- Start the next benchmark suite if any remain
- Review the eval report with `/generate-report`

#### If blocked on infrastructure

Show exactly what's blocking and how to fix it:
- Token refresh: provide the credential refresh steps
- Rate limits: suggest reducing parallelism or waiting
- Docker issues: suggest checking disk space and Docker status

### 4. Present as an actionable recommendation

Format the output as:

```
## Current State
X tasks total: Y passing, Z failed, W errored, V running
Gap: N missing task runs (of M expected)

## Recommended Actions (in priority order)

1. **[CRITICAL]** Run missing SG_full tasks (77 task runs needed)
   → SG_full has 0 valid runs for 10 suites after DS-compromised archival
   → Ensure DS retry preamble is deployed in claude_baseline_agent.py
   → Run: `./configs/locobench_3config.sh` (25 missing)
   → Run: `./configs/swebenchpro_3config.sh` (36 missing)
   → ...

2. **[HIGH]** Fix infrastructure errors (N tasks blocked)
   → ...

3. **[MEDIUM]** Fill baseline/SG_full gaps (N tasks)
   → SWE-bench Pro baseline: 12 missing (protonmail, internetarchive, etc.)
   → ...

4. **[LOW]** Investigate divergent tasks
   → ...
```

## Follow-up Actions

The user can then say:
- "triage task_012" → invokes `/triage-failure`
- "fix it" → applies the suggested fix
- "rerun task_012" → invokes `/quick-rerun`
- "compare configs" → invokes `/compare-configs`
- "mcp audit" → invokes `/mcp-audit` for MCP-conditioned analysis
- "reextract metrics" → invokes `/reextract-metrics` after extraction fixes
- "watch benchmarks" → invokes `/watch-benchmarks` for updated status
- "evaluate traces" → invokes `/evaluate-traces` for comprehensive audit
