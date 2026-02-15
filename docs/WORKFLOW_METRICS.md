# Workflow Metrics Methodology

> **Important**: All time projections in this document and in CodeContextBench
> enterprise reports are **modeled estimates**, not direct measurements.
> They are derived from agent trace data combined with published developer
> productivity research. They should be interpreted as directional
> indicators, not precise predictions.

## Overview

CodeContextBench measures AI coding agent performance across 14 benchmark
suites. To translate raw benchmark metrics (tokens, tool calls, task time)
into business-relevant productivity estimates, we map each benchmark suite
to an **engineering workflow category** and apply conservative
token-to-time conversion multipliers.

## Workflow Categories

| Category | Description | Benchmark Suites |
|----------|-------------|-----------------|
| Code Comprehension | Reading, understanding, and reviewing unfamiliar code | LoCoBench, RepoQA, CodeReview |
| Cross-Repo Navigation | Tracing dependencies across repositories or large monorepos | CrossRepo, LargeRepo |
| Dependency Analysis | Resolving, analyzing, and installing project dependencies | DependEval, DIBench |
| Bug Localization | Fault localization, root-cause analysis, minimal-fix identification | LinuxFLBench, SWE-Perf |
| Feature Implementation | Implementing features, modifying code based on issue descriptions | SWE-bench Pro, PyTorch, TAC |
| Onboarding | Ramping up on unfamiliar projects, reading docs, first tasks | K8s Docs, Investigation |

## Token-to-Time Conversion

### Methodology

We convert agent token consumption and tool call counts to
**engineer-equivalent minutes** using two independent multipliers:

1. **Tokens per minute** — the rate at which an experienced engineer
   reads and comprehends unfamiliar code. This varies by workflow
   complexity.
2. **Tool calls per minute** — the rate at which an engineer manually
   performs equivalent IDE actions (file opens, searches, edits,
   terminal commands).

The **maximum** of the two estimates is used as the final
engineer-equivalent time, ensuring we capture the bottleneck dimension.

```
engineer_minutes = max(
    total_tokens / tokens_per_minute,
    total_tool_calls / tool_calls_per_minute
)
```

### Multiplier Values

| Category | Tokens/min | Tool calls/min | Rationale |
|----------|-----------|---------------|-----------|
| Code Comprehension | 800 | 3.0 | Lower throughput due to dense reading requirements |
| Cross-Repo Navigation | 600 | 2.5 | Slowest due to context-switching overhead across repos |
| Dependency Analysis | 700 | 2.0 | Low action rate — much time spent reading docs/configs |
| Bug Localization | 500 | 2.0 | Cognitive complexity of debugging reduces throughput |
| Feature Implementation | 1,000 | 4.0 | Higher throughput for familiar edit-test cycles |
| Onboarding | 900 | 3.5 | Moderate rate — structured reading plus exploration |

### Conservatism

All multipliers are calibrated to the **lower bound** of published
estimates. This means:

- Time savings projections will be **understated** rather than overstated.
- Values assume an **experienced engineer** on an unfamiliar codebase
  (not a junior developer or a domain expert).
- Multipliers do not account for interruptions, meetings, or other
  non-coding time — they model pure focused-work minutes only.

## Research Foundations

The multiplier values are informed by several bodies of published
developer productivity research:

### Google DORA (DevOps Research and Assessment)

The DORA program's annual State of DevOps reports (2014–2024) establish
that elite teams spend significantly less time on unplanned work and
manual processes. Key findings relevant to our multipliers:

- Code review throughput: 200–1,000 lines/hour depending on complexity
  (Beller et al., 2014; Cohen, 2006).
- Context-switching penalty: 15–25 minutes per interruption (DeMarco &
  Lister, 2013), supporting lower tool-calls-per-minute for cross-repo
  workflows.

*Source: DORA Team, "Accelerate: State of DevOps" (2018–2024),
Google Cloud.*

### Microsoft Developer Velocity Index

Microsoft's research on developer velocity and inner-loop productivity
provides empirical data on IDE interaction rates:

- Average file opens per task: 8–15 for bug fixes, 15–30 for features
  (Minelli et al., 2015).
- Search-to-edit ratio: developers spend 35–50% of coding time
  navigating and searching (Ko et al., 2006; Sillito et al., 2008).

These findings validate our tool-call multipliers and the navigation
ratio metric.

*Source: Microsoft Developer Division, "Developer Velocity Index"
(2020–2023).*

### McKinsey Developer Productivity

McKinsey's framework for measuring developer productivity emphasizes
distinguishing inner loop (coding, testing, debugging) from outer loop
(review, deploy, monitor) activities:

- Inner-loop cycle time: 5–60 minutes depending on task complexity.
- AI-assisted coding can reduce inner-loop time by 20–45% for
  comprehension-heavy tasks.

We use the lower end of these ranges (20%) as our baseline assumption
for context-infrastructure benefit.

*Source: McKinsey & Company, "Yes, you can measure software developer
productivity" (2023).*

## Disclaimers

1. **Modeled, not measured**: Time savings are extrapolated from agent
   benchmark performance, not observed in production engineering
   environments.

2. **Task-level, not project-level**: Benchmarks measure isolated task
   completion. Real-world engineering involves coordination, review,
   and deployment overhead not captured here.

3. **Agent ≠ engineer**: Agent tool-call patterns differ from human
   IDE usage. The conversion assumes functional equivalence (same
   information gathered/produced), not behavioral equivalence.

4. **Conservative by design**: All projections err toward understating
   impact. Actual time savings in practice may be higher for workflows
   with significant context-switching overhead.

5. **Enterprise context**: Multipliers are calibrated for regulated
   enterprise environments (fintech, healthcare, defense) where
   code review thoroughness and compliance requirements increase
   time-per-action relative to startup environments.
