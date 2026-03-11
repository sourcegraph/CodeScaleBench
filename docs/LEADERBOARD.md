# Leaderboard Scoring Specification

This document defines how CodeScaleBench ranks agent submissions on the leaderboard.

## Submissions

A **submission** is a set of task results from a single agent system. Each submission is identified by its agent name and configuration label — for example:

- `Claude Code (baseline)` — Claude Code with built-in tools only
- `Claude Code (Sourcegraph)` — Claude Code with Sourcegraph MCP tools
- `Codex (default)` — OpenAI Codex with its default configuration
- `Augment Code (custom MCP)` — Augment Code with a custom tool server

Different configurations of the same agent are treated as separate submissions. The leaderboard ranks all submissions against each other.

## Primary Metric: Mean Reward

Each task produces a **reward** value between 0.0 and 1.0 (stored in `result.json` as `verifier_result.rewards.reward`). The primary metric for a benchmark is the **mean reward** across all tasks in that benchmark:

```
mean_reward = sum(task_rewards) / task_count
```

## LLM Judge Score

In addition to the automated verifier reward, tasks may be evaluated by an LLM judge that reviews the full agent trace, instruction, ground truth solution, and agent output. The judge produces a composite score (0.0-1.0) based on the following rubric dimensions:

| Dimension | What it measures |
|-----------|-----------------|
| **Correctness** | Is the agent's solution functionally correct? |
| **Completeness** | Does the solution address all requirements? |
| **Code Quality** | Is the code clean, idiomatic, and well-structured? |
| **Reasoning Quality** | How well did the agent reason about the problem? |
| **Tool Use Efficiency** | How efficiently did the agent use available tools? |

The judge score is a **complementary quality signal** — it does **not** affect ranking. The automated verifier reward remains the canonical ranking metric. Judge scores appear in a separate column on the leaderboard and display `---` when not available for a task.

The aggregate judge score is computed identically to the aggregate verifier score: the unweighted mean of per-benchmark mean judge scores over qualifying (complete) benchmarks.

## Error Handling

Tasks that error (agent crash, timeout, container failure) count as **reward = 0.0**. They are never excluded from the denominator. If a submission errors on 2 of 10 tasks and scores 1.0 on the other 8, its mean reward is `8.0 / 10 = 0.80`.

## Per-Benchmark Completeness

To qualify for a work type's leaderboard, a submission must include results for **all** tasks in that work type. The 9 work types and required task counts are:

| Work Type | Tasks | Reward Type |
|-----------|------:|-------------|
| crossrepo | 47 | varies by task |
| understand | 44 | varies by task |
| refactor | 43 | varies by task |
| security | 39 | varies by task |
| feature | 34 | varies by task |
| debug | 26 | varies by task |
| fix | 19 | varies by task |
| test | 12 | varies by task |
| document | 11 | varies by task |

Reward semantics (test_ratio, diff_similarity, checklist, etc.) are defined per task; see [SCORING_SEMANTICS.md](SCORING_SEMANTICS.md).

A submission missing any task in a work type does **not** appear on that work type's leaderboard. Partial results are retained in the data for analysis but excluded from rankings.

## Aggregate Score

The **CSB Aggregate Score** is the unweighted (macro) average of per-work-type mean rewards:

```
csb_aggregate = sum(per_work_type_mean_rewards) / N_qualifying_work_types
```

All work types carry equal weight regardless of task count. The aggregate score is computed over work types where the submission has complete results. A submission with complete results for 8 of 9 work types gets an aggregate over those 8. Submissions with more complete work types are ranked higher when scores are close.

## Tie-Breaking

When two submissions have equal mean reward (to 3 decimal places), ties are broken in order:

1. **Work types completed** — number of work types with full task coverage (more is better)
2. **Pass rate** — fraction of tasks with reward > 0.0 (higher is better)
3. **Median reward** — median of per-task rewards (higher is better)
4. **Token efficiency** — total tokens used, `n_input_tokens + n_output_tokens` (lower is better)

## Interpreting Scores

Reward values are always 0.0–1.0, but the semantics differ by task (reward type is defined per task):

| Reward Type | What 0.8 Means |
|-------------|----------------|
| **test_ratio** | 80% of test cases pass |
| **diff_similarity** | Patch is 80% similar to the reference diff |
| **semantic_similarity** | Agent output is 80% semantically similar to the reference answer |
| **checklist** | 80% of weighted checklist items satisfied |
| **binary** | Not applicable — reward is either 0.0 or 1.0 |

See [SCORING_SEMANTICS.md](SCORING_SEMANTICS.md) for full definitions.

### Reward Type Details

- **test_ratio**: The fraction of repository test cases that pass after the agent's changes. Measures functional correctness.
- **diff_similarity**: Similarity between the agent's code diff and the expected reference diff. Measures implementation accuracy.
- **semantic_similarity**: Embedding-based similarity between the agent's output and the reference answer. Measures content accuracy.
- **checklist**: Weighted sum of discrete checks (file presence, pattern matching, structural correctness). Measures completeness.
- **binary**: Pass or fail — the task is either solved (1.0) or not (0.0). No partial credit.

## Calculation Example

An agent runs all 9 SDLC suites (150 tasks) and achieves:

| Suite | Mean Reward |
|-------|-------------|
| csb_sdlc_understand | 0.550 |
| csb_sdlc_design | 0.400 |
| csb_sdlc_fix | 0.320 |
| csb_sdlc_feature | 0.380 |
| csb_sdlc_refactor | 0.350 |
| csb_sdlc_test | 0.500 |
| csb_sdlc_document | 0.620 |
| csb_sdlc_secure | 0.450 |
| csb_sdlc_debug | 0.410 |

**CSB Aggregate Score** = sum of means / 9 = **0.442**

**Suites completed** = 9/9

**Pass rate** = tasks with reward > 0.0 / total tasks = e.g., 109 / 150 ≈ 0.727
