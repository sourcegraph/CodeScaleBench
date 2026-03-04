# CodeScaleBench: Testing Coding Agents on Large Codebases and Multi-Repo Software Engineering Tasks

_Alternate title: "Existing benchmarks are weak for evaluating enterprise-scale coding agents, so I built my own."_  

In January I wrote about my frustrations with coding-agent benchmarks and why most of them do not answer the practical questions I care about. CodeScaleBench is the result: a benchmark designed to test coding agents on large codebases, multi-repo workflows, and tasks across the full software development lifecycle (SDLC), not just bug-fix micro-slices.

## Why I Built This

Most benchmark suites are strong in one narrow direction and weak in the rest:
- small or single-repo scope
- mostly one language family (often Python-heavy)
- weak or gameable verification
- poor auditability (limited or no transcript-level inspection)
- leaderboard-friendly summaries that hide important failure modes

What I wanted:
1. Large codebases (ideally 1M+ LOC, including very large repos).
2. Multi-language coverage.
3. Multi-repo tasks.
4. SDLC coverage: understand, design, feature, fix, test, docs, refactor, secure, debug.
5. Retrieval-aware evaluation (did the agent find the right context, and did that help?).

## What CodeScaleBench Is

CodeScaleBench is currently:
- **370 paired tasks total**
- **CodeScaleBench-SDLC**: 150 tasks across SDLC phases (direct code/task verifiers)
- **CodeScaleBench-Org**: 220 org-scale discovery tasks (artifact verifier on `answer.json`)
- **9 languages** across **40+ repositories**

Two run conditions per task:
- **Baseline**: local code + standard local tools
- **MCP-augmented**: no local source, Sourcegraph MCP tools required

This is intentionally conservative for MCP: baseline has complete local access, while MCP must retrieve context remotely.

## Setup Summary

I evaluate the same task under baseline vs MCP to isolate retrieval/access-method effects.

For MCP runs:
- repositories are mirrored at pinned commits to ensure exact-version retrieval
- the agent gets Sourcegraph MCP tools (keyword search, semantic search, symbol navigation, dependency tracing, file reads, etc.)

## What I Adapted vs. What I Dropped

| Benchmark | Status | Notes |
|---|---|---|
| SWE-Bench Pro | Adapted | Useful issue-resolution tasks across languages. |
| LinuxFLBench | Adapted | Large-codebase fault-localization stress tests. |
| Qodo Code Review | Adapted | Used with synthetic defect injection. |
| TheAgentCompany | Adapted | One task retained (`bustub-hyperloglog-impl-001`). |
| RepoQA | Concepts reused | Ceiling saturation; replaced by harder large-repo tasks. |
| ContextBench | Used for curation | Used to calibrate curator-agent GT automation. |
| DIBench / DependEval / LoCoBench | Dropped | Not suitable for repo-grounded MCP evaluation in this framework. |

Most SDLC tasks and all Org tasks are original, pinned to real repository states.

## Headline Outcome (Current Analysis Snapshot)

From the current analysis set:
- **Overall reward delta (MCP - baseline): +0.0349**
- **SDLC delta: +0.0363**
- **Org delta: +0.0339**

Single-number summaries are directionally useful, but not sufficient. The value is task-type dependent.

## Where MCP Shows the Most Value

Largest suite-level gains are concentrated in retrieval-heavy work:
- SDLC: strongest gains in **Understand**, **Refactor**, **Fix**
- Org: strongest gains in **Incident** and **Security**; these are often cross-repo and high-context tasks

This aligns with the expected value proposition: MCP helps most when relevant context is distributed and non-local.

## Updated Retrieval Breakdown (Newly Curated Ground Truth, `runs/analysis`)

I recomputed retrieval metrics for overlap tasks with both pre-existing and curated ground truth variants.  
Source artifact: `results/ir/baseline_vs_mcp_breakdown_org_sdlc_runs_analysis_20260304.json`.

Scored tasks in this slice:
- Org: 206
- SDLC: 123
- Combined: 329

### Curated GT (`ground_truth_agent.json` / `oracle_answer_agent.json`)

| Group | n | P@5 (BL/MCP) | R@5 (BL/MCP) | F1@5 (BL/MCP) | P@10 (BL/MCP) | R@10 (BL/MCP) | F1@10 (BL/MCP) | Total File Recall (BL/MCP) |
|---|---:|---|---|---|---|---|---|---|
| Org | 206 | 0.007 / 0.471 | 0.002 / 0.149 | 0.003 / 0.206 | 0.007 / 0.311 | 0.004 / 0.177 | 0.005 / 0.200 | 0.005 / 0.182 |
| SDLC | 123 | 0.364 / 0.489 | 0.261 / 0.371 | 0.260 / 0.356 | 0.243 / 0.318 | 0.314 / 0.430 | 0.234 / 0.308 | 0.331 / 0.437 |
| Combined | 329 | 0.140 / 0.478 | 0.099 / 0.232 | 0.099 / 0.262 | 0.095 / 0.313 | 0.120 / 0.272 | 0.091 / 0.240 | 0.127 / 0.277 |

### Pre-existing GT (`ground_truth.json` / `oracle_answer.json`)

| Group | n | P@5 (BL/MCP) | R@5 (BL/MCP) | F1@5 (BL/MCP) | P@10 (BL/MCP) | R@10 (BL/MCP) | F1@10 (BL/MCP) | Total File Recall (BL/MCP) |
|---|---:|---|---|---|---|---|---|---|
| Org | 206 | 0.011 / 0.199 | 0.005 / 0.089 | 0.006 / 0.114 | 0.008 / 0.124 | 0.008 / 0.104 | 0.007 / 0.105 | 0.008 / 0.106 |
| SDLC | 123 | 0.301 / 0.397 | 0.296 / 0.410 | 0.266 / 0.354 | 0.194 / 0.241 | 0.343 / 0.463 | 0.218 / 0.280 | 0.356 / 0.476 |
| Combined | 329 | 0.119 / 0.273 | 0.114 / 0.209 | 0.103 / 0.204 | 0.078 / 0.167 | 0.133 / 0.238 | 0.086 / 0.170 | 0.138 / 0.244 |

## MCP Value Highlights from the New Retrieval Slices

### 1) Multi-repo tasks benefit more than single-repo tasks

Curated GT deltas (`MCP - baseline`, combined):
- `single_repo` (n=158): **F1@10 +0.0853**, **Total Recall +0.1119**
- `multi_repo` (n=171): **F1@10 +0.2089**, **Total Recall +0.1862**

### 2) Gains persist across size bins, with strongest lift in 1M-5M proxy bucket

Curated GT deltas (`MCP - baseline`) by revised LOC size bands:
- `<400K` (n=15): F1@10 +0.2503, Total +0.2780
- `400K-2M` (n=31): F1@10 +0.2618, Total +0.2424
- `2M-8M` (n=143): F1@10 +0.1796, Total +0.1622
- `8M-40M` (n=74): F1@10 +0.0719, Total +0.0590
- `>40M` (n=3): F1@10 +0.0242, Total +0.0667
- `unknown` (n=63): F1@10 +0.0992, Total +0.1601

Interpretation: retrieval lift is not uniform, but MCP shows clear upside where task context is more distributed and retrieval-heavy.

Method note: I corrected an Org path-normalization bug in an earlier draft where some baseline paths were mismatched due to path shape differences (for example `repo/repo/path` vs `repo/path`). I also replaced SDLC size proxies with non-proxy repository size mapping for the size-bin slice in this version.

## Cost and Speed

Current paired means:
- mean cost delta: **+$0.040/task**
- wall-clock delta: **-36.22s**
- agent execution delta: **-101.06s**

So the current tradeoff is: slightly higher spend, materially faster completion.

## Tool-Use Pattern

Agents heavily favor keyword search and file reads. Deep Search remains rarely used organically.

This suggests prompt/tool-policy design still matters: better capability exists than what default behavior frequently exploits.

## Auditing Matters

Every run emits:
- `result.json` (score, timing, metadata)
- full trajectory/transcript with tool calls

These traces are essential. They exposed benchmark bugs, prompt contamination, verifier issues, and environment loopholes (including a git-history bypass incident) that would have silently distorted results if not audited.

## Quality Assurance Is Most of the Work

Benchmark quality gates check:
1. Task validity
2. Outcome validity
3. Reporting completeness
4. Reproducibility
5. Tool effectiveness
6. Statistical validity

Without this, benchmark claims become fragile very quickly.

## What This Means

The current signal is not “MCP always wins.”  
The signal is:
- MCP has measurable value, especially in cross-repo and context-heavy discovery tasks.
- The effect is heterogeneous across task families.
- Retrieval quality improvements do not always map linearly to reward outcomes.

That is exactly why this benchmark is structured around SDLC and org-use-case slices instead of a single aggregate score.

## What’s Next

Planned next steps:
1. Expand multi-run coverage to reduce non-determinism noise.
2. Evaluate additional harnesses (Codex, Cursor, Gemini, Copilot, OpenHands).
3. Compare alternate MCP providers on the same task set.
4. Run tool-policy experiments (especially semantic/deep-search nudges).
5. Continue tightening verifier and QA infrastructure before final white paper publication.
