# Submission Format

This document describes how to package evaluation results for submission to the CodeContextBench leaderboard.

## Directory Structure

A submission is a directory tree with one subdirectory per task. Each task subdirectory contains a `result.json` and a trajectory file.

```
my-submission/
├── ccb_pytorch/
│   ├── sgt-001/
│   │   ├── result.json
│   │   └── trajectory.json
│   ├── sgt-002/
│   │   ├── result.json
│   │   └── trajectory.json
│   └── sgt-003/
│       ├── result.json
│       └── trajectory.txt
├── ccb_swebenchpro/
│   ├── qutebrowser__qutebrowser-8307/
│   │   ├── result.json
│   │   └── trajectory.json
│   └── NodeBB__NodeBB-11488/
│       ├── result.json
│       └── trajectory.json
└── ccb_k8sdocs/
    └── apiserver-doc-001/
        ├── result.json
        └── trajectory.json
```

Task subdirectory names must match the canonical `task_name` field in the corresponding `result.json`.

## Result Format

Each `result.json` must conform to [`schemas/result.schema.json`](../schemas/result.schema.json).

### Required Fields

| Field | Type | Description |
|-------|------|-------------|
| `task_name` | string | Canonical task identifier (e.g., `sgt-001`) |
| `verifier_result.rewards.reward` | number (0.0–1.0) | Canonical reward score |
| `exception_info` | object or null | Exception details if errored; null on success |
| `started_at` | string | ISO 8601 timestamp (trial start) |
| `finished_at` | string | ISO 8601 timestamp (trial end) |

### Optional Fields

| Field | Type | Description |
|-------|------|-------------|
| `agent_info.name` | string | Agent name (e.g., `claude-code`) |
| `agent_info.model_info.name` | string | Model identifier (e.g., `anthropic/claude-opus-4-5-20251101`) |
| `agent_result.n_input_tokens` | integer or null | Total input tokens consumed |
| `agent_result.n_output_tokens` | integer or null | Total output tokens produced |
| `trajectory_path` | string or null | Relative path to the trajectory file |

**Important:** The reward field is `verifier_result.rewards.reward` — not `rewards.score`. Submissions using `score` instead of `reward` will fail validation.

### Minimal Example

```json
{
  "task_name": "sgt-001",
  "verifier_result": {
    "rewards": {
      "reward": 0.85
    }
  },
  "exception_info": null,
  "started_at": "2026-02-06T10:00:00Z",
  "finished_at": "2026-02-06T10:15:00Z"
}
```

## Trajectory Files

Every task subdirectory **must** include a trajectory file. Submissions without trajectory files are rejected.

Accepted formats:

### JSON trajectory (`trajectory.json`)

A JSON array of interaction steps:

```json
[
  {
    "role": "system",
    "content": "You are a coding agent...",
    "timestamp": "2026-02-06T10:00:00Z"
  },
  {
    "role": "assistant",
    "content": "I'll start by reading the file...",
    "tool_calls": [
      {"name": "Read", "parameters": {"file_path": "/workspace/src/main.py"}}
    ],
    "timestamp": "2026-02-06T10:00:05Z"
  },
  {
    "role": "tool",
    "content": "def main():\n    ...",
    "timestamp": "2026-02-06T10:00:06Z"
  }
]
```

Fields per step:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `role` | string | yes | `system`, `user`, `assistant`, or `tool` |
| `content` | string | yes | Message content |
| `tool_calls` | array | no | Tool invocations (for assistant messages) |
| `timestamp` | string | no | ISO 8601 timestamp |

### Plain text trajectory (`trajectory.txt`)

A plain text transcript of the agent session. No required format — any readable log of the agent's actions is accepted.

```
[10:00:00] Reading /workspace/src/main.py
[10:00:05] File contains 150 lines. Found the target function on line 42.
[10:00:10] Editing line 42: changing return type from int to float
[10:00:15] Running tests... 8/8 passed.
```

## Pre-Submission Validation

Validate your submission before packaging:

```bash
python3 scripts/validate_submission.py --submission-dir my-submission/
```

This checks every `result.json` against the schema and reports errors per task:

```
OK    ccb_pytorch/sgt-001
OK    ccb_pytorch/sgt-002
FAIL  ccb_pytorch/sgt-003: missing required field verifier_result.rewards.reward

3 files checked: 2 valid, 1 invalid
```

Exit code 0 means all files are valid. Exit code 1 means at least one file failed validation.

## Packaging

Use the packaging script to create a validated submission archive:

```bash
python3 scripts/package_submission.py \
  --results-dir my-submission/ \
  --output my-submission.tar.gz
```

The script validates all `result.json` files and checks that each task has a trajectory file before creating the archive. It fails fast with clear errors if anything is missing.

## Completeness

See [LEADERBOARD.md](LEADERBOARD.md) for scoring rules. Key points:

- **Per-benchmark leaderboard**: You must submit results for **all tasks** in a benchmark to appear on that benchmark's leaderboard.
- **Aggregate leaderboard**: You must have complete results for **all 13 benchmarks** to appear on the aggregate leaderboard.
- Errored tasks (non-null `exception_info`) count as `reward=0.0` — they are not excluded.
- Partial submissions appear on individual benchmark leaderboards where coverage is complete.
