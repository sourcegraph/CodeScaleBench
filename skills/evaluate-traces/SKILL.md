# Skill: Evaluate Benchmark Traces

Comprehensive evaluation of benchmark run traces: data integrity validation, output quality assessment, and efficiency analysis across configurations and benchmarks.

## Trigger Phrases
- evaluate traces, analyze traces, review benchmark results, audit traces, check eval results, analyze run, benchmark evaluation, evaluate run, trace quality, run quality

## Instructions

When triggered, perform a **comprehensive trace evaluation** covering three dimensions: (1) data integrity, (2) output quality, and (3) efficiency. Accept optional arguments to scope the analysis (e.g., specific suite, config, or run).

---

### Phase 1: Scope Selection

If the user provides arguments (e.g., `evaluate traces for SWE-bench Pro SG_full`), use those to scope. Otherwise, evaluate ALL official runs.

**Key paths and tools:**
- MANIFEST: `runs/official/MANIFEST.json` (symlink to evals dir — not in git)
- Audit script: `python3 scripts/audit_traces.py [--json] [--suite X] [--config X]`
- Manifest generator: `python3 scripts/generate_manifest.py`
- Run directory: `runs/official/`
- Configs: `baseline`, `sourcegraph_full`

**Critical technical details:**
- `runs/official` is a **symlink** — use the real path for `find` commands
- MCP tool names in traces may have `sg_` prefix (`mcp__sourcegraph__sg_keyword_search`) OR not (`mcp__sourcegraph__keyword_search`) depending on batch vintage. Always check for both patterns.
- Batch timestamp dirs use pattern `YYYY-MM-DD__HH-MM-SS` with `__` separator — don't confuse with task dirs (`task_name__hash`)
- Task-level result.json has full data; batch-level result.json only has aggregate stats
- **Transcript vs trajectory**: `claude-code.txt` includes ALL tool calls (including Task subagent MCP calls). `trajectory.json` only has main-agent calls and UNDERCOUNTS MCP usage. Always prefer transcript for tool counting.

---

### Phase 2: Data Integrity Audit

Launch parallel subagents to check data integrity:

#### 2a. MCP Adoption Validation
For each SG config task in MANIFEST:
- Read `agent/claude-code.txt` (NOT trajectory.json) and count `mcp__sourcegraph` tool_use invocations
- Check both `sg_` prefix and non-prefix tool name variants
- Verify SG_full tasks use MCP tools (should be ~100% of scored tasks)
- Verify SG_full tasks use MCP tools AND check Deep Search (`deepsearch`) adoption
- Classify tasks into **used-MCP** vs **zero-MCP** groups:
  - **Used-MCP**: At least 1 MCP tool call in transcript. Further classify by intensity:
    - Light (1-5 calls): Minimal MCP usage, likely spot checks
    - Moderate (6-20 calls): Regular MCP usage during exploration
    - Heavy (20+ calls): MCP-centric workflow
  - **Zero-MCP**: MCP available but 0 calls. Classify reason:
    - Trivially local (DependEval dependency_recognition — all data in local files)
    - Explicit file list (CodeReview — instructions name exact files)
    - Full local codebase (SWE-Perf — complete repo in container)
    - Both configs failed (neither BL nor SF produced useful output)
    - Agent confusion (needs transcript investigation)
- Report zero-MCP rate per benchmark. High zero-MCP (>30%) suggests MCP isn't valuable for that task type.
- **Important**: Compute reward/time deltas SEPARATELY for used-MCP and zero-MCP groups. Mixing them dilutes the signal (zero-MCP tasks add preamble overhead with no MCP benefit).

#### 2b. Baseline Contamination Check
- Scan ALL baseline `claude-code.txt` for any `mcp__sourcegraph` tool calls (should be 0)
- Check baseline `instruction.txt` for Sourcegraph/MCP references (cosmetic, not functional)

#### 2c. Infrastructure Failure Detection
- **Zero-token tasks**: `n_input_tokens=0, n_output_tokens=0` → auth failures (agent never ran)
- **Crash failures**: `n_input/n_output=null`, no trajectory, `<=5 claude-code.txt lines` → Docker/Node.js crash
- **Null-token H3 bug**: `null` tokens but agent ran fine (50+ cc_lines, valid rewards) — NOT failures
- **Exceptions**: `AgentSetupTimeoutError`, `RuntimeError` in result.json
- **Setup failures**: Non-zero return code in `agent/setup/stdout.txt`

#### 2d. Dedup Integrity
- Verify MANIFEST dedup prefers non-zero-token results over zero-token results
- Check for auth-failed runs that may corrupt scores via timestamp-based dedup
- Regenerate MANIFEST if issues found: `python3 scripts/generate_manifest.py`

---

### Phase 3: Output Quality Assessment

Read the MANIFEST and compute quality metrics:

#### 3a. Per-Suite Reward Analysis
For each benchmark suite, report:

| Suite | Config | Tasks | Scored | Errored | Mean Reward | Pass Rate | Delta vs BL |
|-------|--------|------:|-------:|--------:|------------:|----------:|------------:|

Where:
- **Scored** = tasks - errored (infra failures excluded from mean)
- **Pass Rate** = passed / scored
- **Delta vs BL** = suite mean under config minus suite mean under baseline

#### 3b. Cross-Config Comparison (matched tasks)
For fair comparison, compute metrics only on tasks that ran successfully across ALL configs:
- Identify intersection of scored tasks per suite across baseline, SG_full
- Compute matched-task means for each config
- Report which tasks flipped outcome (pass→fail or fail→pass) between configs

#### 3c. Task-Level Quality Patterns
Identify and report:
- **MCP helps**: Tasks where SG configs improve reward over baseline
- **MCP hurts**: Tasks where SG configs decrease reward
- **MCP neutral**: No change
- **Full helps only**: SG_full improves over baseline (richer context tooling value)
- **Persistent failures**: Tasks that fail across ALL configs (task difficulty, not config issue)
- **Config-specific failures**: Tasks that fail only in one config (investigate MCP distraction effect)

#### 3d. Benchmark Category Insights
Group findings by benchmark type:
- **Search-heavy** (K8s Docs, LargeRepo, LoCoBench): MCP should help with efficiency
- **Implementation-heavy** (TAC, SWE-Perf, PyTorch): MCP may distract from coding
- **Mixed** (SWE-bench Pro, CrossRepo): Variable MCP impact
- **Local-only** (DependEval, DIBench, RepoQA): MCP provides little value

---

### Phase 4: Efficiency Analysis

Extract efficiency metrics from result.json and traces:

#### 4a. Token Usage
For each suite × config, compute:
- Mean input tokens, output tokens, cache tokens
- Total cost estimate (input × $15/M + output × $75/M for Opus)
- Token ratio: cache_tokens / input_tokens (cache efficiency)

#### 4b. Wall Clock Time
From `started_at` / `finished_at` in result.json:
- Mean wall clock seconds per task
- Wall clock delta: SG configs vs baseline (positive = slower)
- Identify suites where MCP is faster (LargeRepo, K8s Docs typically)

#### 4c. MCP Tool Distribution
For SG configs, report tool usage breakdown:
- Top tools by call count and task coverage
- `keyword_search` typically dominates (~40-50% of calls)
- `read_file` and `list_files` are 2nd/3rd
- Deep Search actual usage (tool_use events, not init listings)
- Unused tools: `go_to_definition`, `get_contributor_repos` typically unused
- **Preamble overhead**: Zero-MCP tasks still incur ~26% time and ~40% cost overhead from preamble injection. Factor this into cost-effectiveness calculations.

For deeper MCP-conditioned analysis, use `/mcp-audit` which pairs tasks and computes deltas separately for used-MCP vs zero-MCP groups.

#### 4d. Cost-Effectiveness
Compute cost per unit of reward:
- Cost per scored task = total_cost / scored_tasks
- Cost per reward point = total_cost / total_reward
- MCP overhead = (SG_cost - BL_cost) / BL_cost
- Value ratio: reward_delta / cost_delta (is the MCP cost justified?)

---

### Phase 5: Synthesis and Report

Produce a structured report with:

1. **Executive Summary**: 3-5 bullet points on key findings
2. **Data Quality**: Pass/fail status for each integrity check
3. **Corrected Scores**: Per-suite × per-config table with errored tasks excluded
4. **Weighted Averages**: Overall mean across all suites per config
5. **MCP Value Assessment**: Where MCP helps (efficiency), where it hurts (distraction), where neutral
6. **Efficiency Comparison**: Cost and speed table by config
7. **Recommendations**: Actionable items (reruns needed, config changes, investigation items)

Write the report to `docs/TRACE_AUDIT_<date>.md`.

---

### Phase 6: Follow-up

After presenting results, offer:
- **Create beads issues** for any rerun needs or investigation items
- **Regenerate MANIFEST** if data corrections were applied
- **Update MEMORY.md** with key findings for future sessions

---

## Key Files

| File | Path | Contents |
|------|------|----------|
| MANIFEST | `runs/official/MANIFEST.json` | Canonical run tracking (suite/config → task results) |
| Batch result | `<config>/<datetime>/result.json` | Aggregate timing and counts |
| Task result | `<config>/<datetime>/<task__hash>/result.json` | Reward, tokens, exceptions |
| Agent trace | `<task__hash>/agent/claude-code.txt` | Full Claude Code JSONL transcript |
| Trajectory | `<task__hash>/agent/trajectory.json` | Structured step log |
| Instructions | `<task__hash>/agent/instruction.txt` | Instructions given to agent |
| CLAUDE.md | `<task__hash>/agent/CLAUDE.md` | Preamble + workspace config |

## Analysis Scripts

| Script | Usage |
|--------|-------|
| `scripts/audit_traces.py` | Trace audit: tool counts, MCP adoption, errors, compliance |
| `scripts/mcp_audit.py` | MCP-conditioned paired analysis: used vs zero-MCP, intensity buckets |
| `scripts/generate_manifest.py` | Rebuild MANIFEST from on-disk results |
| `scripts/aggregate_status.py` | Run scanner with error fingerprinting |
| `scripts/compare_configs.py` | Cross-config divergence analysis |
| `scripts/cost_report.py` | Token usage and cost aggregation |
| `scripts/reextract_all_metrics.py` | Batch re-extract task_metrics.json after bug fixes |

## Known Patterns

1. **Zero-token (int 0)**: Auth failures — agent started but auth failed. Exactly 3 claude-code.txt lines.
2. **Null-token + no trajectory + <=5 lines**: Crash failures (protonmail Node v16, openlibrary gpg)
3. **Null-token + valid rewards**: H3 token-logging bug — agent ran fine, just tokens not recorded
4. **MCP distraction on TAC**: MCP overuse on implementation tasks can reduce scores
5. **Deep Search unused**: Only ~1% of SG_full tasks actually invoke deepsearch (agent prefers sync tools)
6. **SWE-Perf regression**: MCP can hurt SWE-Perf (performance tasks need focused coding, not search)
7. **Subagent MCP calls hidden**: Task subagent MCP calls only appear in `claude-code.txt`, NOT `trajectory.json`. ~11 tasks had hidden MCP calls (142 calls total) reclassified from zero-MCP to used-MCP after transcript-first extraction fix (commit 59cdf7db).
8. **Zero-MCP is mostly rational**: ~80% of zero-MCP tasks are trivially local (DependEval), have explicit file lists (CodeReview), or have full local codebases (SWE-Perf). Only ~20% warrant investigation.
9. **Monotonic MCP intensity-reward**: Light users +2.2%, Moderate +3.6%, Heavy +6.1% reward improvement. More MCP = more benefit, on tasks where MCP is used at all.

## Run Directory Layout

```
runs/official/
  MANIFEST.json
  <benchmark>_<variant>_opus_<timestamp>/
    baseline/
      <YYYY-MM-DD__HH-MM-SS>/          # Batch timestamp
        <task_name>__<hash>/            # Task directory
          result.json
          agent/
            claude-code.txt             # JSONL transcript
            trajectory.json             # ATIF structured trace
            instruction.txt             # Task instructions
            CLAUDE.md                   # Preamble config
          verifier/
            reward.txt
    sourcegraph_full/
      [same structure]
  archive/                              # Archived broken/superseded runs
```
