# MCP Report Triage — 2026-02-07

## Archival Summary

23 directories archived from `runs/official/` to `runs/official/archive/`:

| Category | Count | Details |
|----------|-------|---------|
| Investigation test runs | 9 | `investigation_haiku_*` (4), `investigation_opus_*` (5). No verifier scores. |
| Preamble test runs | 3 | `locobench_preamble_test_*` (v1, v2, v3). Single-task preamble iteration tests. |
| Superseded empty batches | 4 | `bigcode_mcp_20260204_*` (2), `k8s_docs_20260203/04` (2). 0 task-level results. |
| Broken/invalid batches | 2 | `swebenchpro_20260203` (all `__archived_invalid`), `sweperf_20260203` (no scored tasks). |
| CrossRepo duplicate | 1 | `crossrepo_20260207_163817` — identical to `_171252` (kept newer). |
| Incomplete single-task runs | 3 | `sweperf_20260207_*` (3). 0-1 results, only sweperf-001. |
| One-off test run | 1 | `swebenchpro_20260207_032046` — 1 task, "sourcegraph" config (not standard), no score. |

## Remaining 17 Active Directories

Post-archival MANIFEST: **215 tasks across 26 runs** (12 suites).

## Open Issues from Report

### P0 — Critical
- **CodeContextBench-szi**: Judge JSON parsing — strip markdown code fences before JSON.parse
- **CodeContextBench-ufn**: LoCoBench `/app/project/` write permissions

### P1 — High
- **CodeContextBench-9th**: Strengthen MCP preamble (6 runs had `no_context_usage`)
- Build error audit: 13/15 build_error runs are MCP. Go/JS/Rust/C# container toolchains.
- LoCoBench cross_file_refactoring task ambiguity
- PyTorch tasks with pre-applied fixes (sgt-010, sgt-024)

### P2 — Medium
- Mirror NumPy + Servo repos to Sourcegraph
- Add preamble guidance for search strategies
- sg_nls_search underutilized outside RepoQA
- Build error flag over-sensitivity

### Key Report Findings (for reference)
- **MCP never flips outcomes**: 0 cases where failing baseline passes with MCP
- **MCP value is efficiency**: K8s Docs (-54% wall), LargeRepo (-59% wall), PyTorch (-41% wall)
- **MCP hurts when**: agent is distracted (TAC SG_base), wrong tools used (PyTorch), or infra broken
- **Attribution**: 22 wins from MCP tool value, 10 losses from infrastructure, 24 losses from agent behavior
- **Cleanest benchmarks**: RepoQA (no issues), K8s Docs (no issues)
