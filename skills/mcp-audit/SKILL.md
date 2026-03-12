---
name: mcp-audit
description: Analyze MCP tool usage patterns, reward/time deltas conditioned on MCP adoption, and zero-MCP investigation. Triggers on mcp audit, mcp analysis, mcp impact, tool usage analysis, did mcp help.
user-invocable: true
---

# MCP Audit

Analyze MCP (Sourcegraph) tool usage across benchmark runs to understand where MCP helps, hurts, or goes unused.

## What This Does

Runs `scripts/mcp_audit.py` which:
1. Collects `task_metrics.json` from paired_rerun batches (BL + SF on same VM)
2. Pairs baseline vs sourcegraph_full tasks for fair comparison
3. Classifies tasks by MCP usage: zero-MCP vs used-MCP (light/moderate/heavy)
4. Computes reward and time deltas conditioned on actual MCP usage
5. Identifies negative flips (baseline pass → MCP fail)

## Steps

### 1. Run the MCP audit

```bash
cd ~/CodeScaleBench && python3 scripts/mcp_audit.py --json --verbose 2>/dev/null
```

Save the JSON output for analysis. The script prints progress to stderr and results to stdout.

### 2. Parse and present key findings

From the JSON output, present these tables:

**Overview:**

| Metric | Value |
|--------|-------|
| Total unique tasks | N |
| Complete BL+SF pairs | N |
| Used-MCP tasks | N |
| Zero-MCP tasks | N |
| Total MCP calls | N |

**Per-benchmark MCP adoption:**

| Benchmark | Total | Used MCP | Zero MCP | Zero % |
|-----------|------:|----------:|----------:|-------:|

**Reward deltas (used-MCP only, cleaner signal):**

| Group | N | BL Mean | SF Mean | Delta | p-value |
|-------|--:|--------:|--------:|------:|--------:|
| Used-MCP | N | X | Y | +Z% | p |
| Zero-MCP | N | X | Y | -Z% | p |
| Light (1-5 calls) | N | X | Y | Z% | |
| Moderate (6-20) | N | X | Y | Z% | |
| Heavy (20+) | N | X | Y | Z% | |

**Timing deltas:**

| Group | BL Mean (s) | SF Mean (s) | Delta |
|-------|------------:|------------:|------:|

### 3. Investigate zero-MCP tasks

For each zero-MCP task, classify the reason:
- **Trivially local**: Task requires only local file operations (e.g., DependEval dependency_recognition)
- **Explicit file list**: Instructions specify exact files to examine (e.g., CodeReview)
- **Full local codebase**: Complete codebase available in container (e.g., SWE-Perf)
- **Both configs failed**: Neither baseline nor SG_full succeeded
- **Agent confusion**: MCP available but agent didn't discover/use it (investigate transcript)

For unexplained zero-MCP cases, offer to read the transcript:
```bash
# Find the task's transcript
find $(readlink -f runs/official) -path "*sourcegraph_full*" -name "claude-code.txt" | xargs grep -l "TASK_ID_HERE" 2>/dev/null
```

### 4. Check for negative flips

List any tasks where baseline passes but SG_full fails (reward regression):
- In used-MCP group: Indicates MCP is actively harmful on these tasks
- In zero-MCP group: Indicates preamble overhead or non-determinism

### 5. MCP tool distribution

Show which MCP tools are most/least used:

| Tool | Calls | Tasks | Avg/Task |
|------|------:|------:|---------:|
| keyword_search | N | N | X |
| nls_search | N | N | X |
| read_file | N | N | X |
| ... | | | |

### 6. Summary and recommendations

Synthesize findings into:
- **MCP value**: Where it demonstrably helps (search-heavy benchmarks)
- **MCP risk**: Where it hurts (implementation-heavy, preamble overhead)
- **Optimization opportunities**: Zero-MCP tasks that SHOULD use MCP but don't
- **Cost-benefit**: Is the token/time overhead justified by reward improvement?

## Variants

### All runs (not just paired reruns)
```bash
python3 scripts/mcp_audit.py --all-runs --json --verbose
```

### Text output (human-readable)
```bash
python3 scripts/mcp_audit.py --verbose
```

### Save to file
```bash
python3 scripts/mcp_audit.py --json --verbose --output docs/MCP_AUDIT_$(date +%Y-%m-%d).md
```

## Key Technical Notes

- **Transcript-first extraction**: Tool counts come from `claude-code.txt` (includes Task subagent MCP calls), NOT `trajectory.json` (main-agent only). This was fixed in commit 59cdf7db.
- **Paired reruns**: BL and SF run concurrently on same VM, eliminating load confounds. Prefixed `paired_rerun_*` in runs/official/.
- **Valid task filter**: Tasks with <10s agent time or 0 output tokens are excluded (auth failures).
- **MCP tool name variants**: Some batches use `sg_` prefix (`mcp__sourcegraph__sg_keyword_search`), others don't. The script handles both.
- **Zero-MCP != MCP failure**: Most zero-MCP tasks rationally chose local tools. Only investigate if the task type suggests MCP should help.

## Related Skills

- `/compare-configs` — Binary pass/fail divergence (simpler, doesn't condition on MCP usage)
- `/evaluate-traces` — Comprehensive trace audit (broader scope, includes data integrity)
- `/cost-report` — Token and cost analysis (doesn't pair tasks or condition on MCP)
