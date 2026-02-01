# BigCode MCP Empty Results Diagnosis

## Summary

**Investigation of:** `runs/official/bigcode_mcp_opus_20260131_130446/`
**Date:** 2026-02-01
**Conclusion:** Task directories exist and contain valid results. The "0 task dirs" observation was incorrect -- the issue is that results are scattered across multiple batch timestamp directories (one per `harbor run` invocation) rather than grouped into a single batch, and the run is incomplete (missing `sourcegraph_no_deepsearch` config entirely, `deepsearch_hybrid` has only 1 of 4 tasks).

---

## Root Cause

The BigCode MCP shell runner (`bigcode_mcp_comparison.sh`) calls `harbor run --path` **once per task** in a loop. Each invocation creates a **separate batch timestamp directory** under the config's `--jobs-dir`. This is correct behavior -- it is not a bug.

The actual issues are:

### 1. Incomplete 3-Config Coverage

The original `bigcode_mcp_comparison.sh` only supports 2 configs: `baseline` and `sourcegraph_hybrid`. The run directory shows:

| Config | Batch Dirs | Tasks Completed | Expected |
|--------|-----------|-----------------|----------|
| `baseline` | 6 | 6 (4 unique + 2 reruns) | 4 |
| `deepsearch_hybrid` | 1 | 1 (k8s-001 only) | 4 |
| `sourcegraph_hybrid` | 8 | 8 (4 unique + 4 reruns) | 4 |

- `deepsearch_hybrid` was likely started manually and abandoned after 1 task
- `sourcegraph_no_deepsearch` was never run (not in the original 2-config script)

### 2. Duplicate Task Runs

Multiple invocations of the shell script wrote to the **same `--jobs-dir`** path (`bigcode_mcp_opus_20260131_130446`). Because each `harbor run` creates a unique batch timestamp, duplicate runs accumulated:

**Baseline duplicates:**
- `big-code-k8s-001` ran twice (2026-01-31__13-04-54 and 2026-01-31__13-11-22 as "k8s-001-precise")
- `big-code-servo-001` ran twice (2026-01-31__13-19-05 and 2026-02-01__02-21-38)

**Sourcegraph_hybrid duplicates:**
- `big-code-k8s-001` ran 4 times (as "precise", "standard", and two unnamed variants)
- `big-code-servo-001` ran twice

### 3. Misleading "0 task dirs" Observation

The observation likely came from looking at the batch directory level without descending into timestamp subdirectories. The actual structure is:

```
bigcode_mcp_opus_20260131_130446/
├── baseline/
│   ├── 2026-01-31__13-04-54/          # <- batch dir (not a task dir)
│   │   └── big-code-k8s-001__Qt4rwLj/ # <- actual task dir (inside batch)
│   ├── 2026-01-31__13-11-22/
│   │   └── big-code-k8s-001-precise__A4DeByn/
│   └── ...
```

Someone may have expected task dirs directly under `baseline/` rather than nested under batch timestamp dirs.

---

## Task Results

All 15 completed task runs scored **reward = 1.0** (100% pass rate):

| Task | Baseline | Deepsearch_hybrid | Sourcegraph_hybrid |
|------|----------|-------------------|--------------------|
| big-code-k8s-001 | 1.0 | 1.0 | 1.0 |
| big-code-servo-001 | 1.0 | -- | 1.0 |
| big-code-trt-001 | 1.0 | -- | 1.0 |
| big-code-vsc-001 | 1.0 | -- | 1.0 |

One `sourcegraph_hybrid` servo task had an `AgentTimeoutError` (timed out after 6000s) but still received reward=1.0 from the verifier.

---

## Errors Found

1. **AgentTimeoutError** -- `sourcegraph_hybrid/2026-01-31__14-31-09/big-code-servo-001__C7y6Z86`
   - Agent execution timed out after 6000s (~1h40m)
   - Verifier still evaluated and assigned reward=1.0
   - Not a blocking issue; task completed before timeout was enforced at result level

2. **Session directory warnings** -- Some tasks logged "No Claude Code session directory found" or "Multiple Claude Code session directories found"
   - Did not affect task completion or rewards
   - Likely a session ID detection issue in the trajectory writer

---

## Recommended Fix

The fix is a **config and execution change**, not a code change:

### For the official 3-config run:

1. **Use the updated `bigcode_3config.sh`** (already created in US-004) which supports all 3 configs: `baseline`, `sourcegraph_no_deepsearch`, `sourcegraph_hybrid`

2. **Use a fresh `--jobs-dir` timestamp** -- do NOT reuse `bigcode_mcp_opus_20260131_130446`. The new script already generates a unique timestamp per invocation.

3. **Run all 3 configs in a single invocation:**
   ```bash
   cd ~/evals/custom_agents/agents/claudecode
   ./configs/bigcode_3config.sh
   ```

4. **No changes needed to `configs/bigcode_3config.yaml`** -- the YAML is reference-only (BigCode is a local benchmark); the shell script is the execution mechanism.

### Verification after re-run:

After a clean run, expect this structure:
```
runs/official/bigcode_mcp_opus_<TIMESTAMP>/
├── baseline/                         # 4 batch dirs, 4 task dirs
├── sourcegraph_no_deepsearch/        # 4 batch dirs, 4 task dirs
└── sourcegraph_hybrid/               # 4 batch dirs, 4 task dirs
```

Each config should have exactly 4 batch timestamp directories, each containing 1 task directory.

### Existing results are valid

The completed tasks in the Jan 31 run produced valid results and can be used for analysis. However, for a clean official comparison:
- Baseline has valid results for all 4 tasks
- `sourcegraph_hybrid` has valid results for all 4 tasks
- `deepsearch_hybrid` only has 1 task (unusable for comparison)
- `sourcegraph_no_deepsearch` has 0 tasks (never run)

A full re-run with `bigcode_3config.sh` is recommended to produce a clean, comparable dataset.
