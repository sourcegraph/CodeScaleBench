# Leaderboard Scoring Specification

This document defines how CodeContextBench ranks agents on the leaderboard.

## Primary Metric: Mean Reward

Each task produces a **reward** value between 0.0 and 1.0 (stored in `result.json` as `verifier_result.rewards.reward`). The primary metric for a benchmark is the **mean reward** across all tasks in that benchmark:

```
mean_reward = sum(task_rewards) / task_count
```

## Error Handling

Tasks that error (agent crash, timeout, container failure) count as **reward = 0.0**. They are never excluded from the denominator. If an agent errors on 2 of 10 tasks and scores 1.0 on the other 8, its mean reward is `8.0 / 10 = 0.80`.

## Per-Benchmark Completeness

To qualify for a benchmark's leaderboard, an agent must run **all** tasks in that benchmark. The required task counts are:

| Benchmark | Tasks | Reward Type |
|-----------|-------|-------------|
| SWE-bench Pro | 36 | test_ratio |
| DependEval | 32 | binary |
| LoCoBench | 25 | semantic_similarity |
| PyTorch | 12 | diff_similarity |
| RepoQA | 10 | semantic_similarity |
| DIBench | 8 | binary |
| TAC | 8 | checklist |
| K8s Docs | 5 | checklist |
| CrossRepo | 5 | semantic_similarity |
| LinuxFLBench | 5 | checklist |
| LargeRepo | 4 | checklist |
| CodeReview | 3 | checklist |
| SWE-Perf | 3 | test_ratio |

An agent that runs 34 of 36 SWE-bench Pro tasks does **not** appear on the SWE-bench Pro leaderboard. Partial results are retained in the MANIFEST for analysis but excluded from rankings.

## Aggregate Score

The **CCB Aggregate Score** is the unweighted (macro) average of per-benchmark mean rewards:

```
ccb_aggregate = sum(per_benchmark_mean_rewards) / 13
```

All 13 benchmarks carry equal weight regardless of task count. An agent must have **complete results for all 13 benchmarks** to appear on the aggregate leaderboard. Agents with partial benchmark coverage appear only on qualifying per-benchmark leaderboards.

## Tie-Breaking

When two agents have equal mean reward (to 3 decimal places), ties are broken in order:

1. **Pass rate** — fraction of tasks with reward > 0.0 (higher is better)
2. **Median reward** — median of per-task rewards (higher is better)
3. **Token efficiency** — total tokens used, `n_input_tokens + n_output_tokens` (lower is better)

## Interpreting Scores

Reward values are always 0.0–1.0, but the semantics differ by benchmark:

| Reward Type | Benchmarks | What 0.8 Means |
|-------------|-----------|-----------------|
| **test_ratio** | SWE-bench Pro, SWE-Perf | 80% of test cases pass |
| **diff_similarity** | PyTorch | Patch is 80% similar to the reference diff |
| **semantic_similarity** | LoCoBench, RepoQA, CrossRepo | Agent output is 80% semantically similar to the reference answer |
| **checklist** | K8s Docs, LargeRepo, CodeReview, LinuxFLBench, TAC | 80% of weighted checklist items satisfied |
| **binary** | DIBench, DependEval | Not applicable — reward is either 0.0 or 1.0 |

### Reward Type Details

- **test_ratio**: The fraction of repository test cases that pass after the agent's changes. Measures functional correctness.
- **diff_similarity**: Similarity between the agent's code diff and the expected reference diff. Measures implementation accuracy.
- **semantic_similarity**: Embedding-based similarity between the agent's output and the reference answer. Measures content accuracy.
- **checklist**: Weighted sum of discrete checks (file presence, pattern matching, structural correctness). Measures completeness.
- **binary**: Pass or fail — the task is either solved (1.0) or not (0.0). No partial credit.

## Calculation Example

An agent runs all 13 benchmarks and achieves:

| Benchmark | Mean Reward |
|-----------|-------------|
| SWE-bench Pro | 0.650 |
| DependEval | 0.800 |
| LoCoBench | 0.500 |
| PyTorch | 0.100 |
| RepoQA | 1.000 |
| DIBench | 0.500 |
| TAC | 0.250 |
| K8s Docs | 0.920 |
| CrossRepo | 0.000 |
| LinuxFLBench | 0.860 |
| LargeRepo | 0.250 |
| CodeReview | 0.933 |
| SWE-Perf | 0.600 |

**CCB Aggregate Score** = (0.650 + 0.800 + 0.500 + 0.100 + 1.000 + 0.500 + 0.250 + 0.920 + 0.000 + 0.860 + 0.250 + 0.933 + 0.600) / 13 = **0.566**

**Pass rate** = tasks with reward > 0.0 / total tasks = e.g., 120 / 156 = 0.769
