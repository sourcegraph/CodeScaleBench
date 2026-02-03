# Large Repo Feature Implementation Benchmark

## Overview

The Large Repo benchmark (`ccb_largerepo`) contains 4 feature implementation tasks across major open-source codebases exceeding 1GB each. Each task requires navigating a large, distributed architecture to implement a real feature that touches multiple subsystems.

This benchmark is designed to measure whether Sourcegraph MCP tools provide meaningful advantage when an agent must discover and modify code scattered across a massive codebase—tasks where local `grep`/`rg` would require many searches and risk missing critical locations.

## Dataset Characteristics

| Attribute | Value |
|-----------|-------|
| **Number of Tasks** | 4 |
| **Task Type** | Feature implementation |
| **Difficulty** | Hard |
| **Codebase Size** | 1–1.6 GB per repository |
| **Languages** | Go, TypeScript, Rust, Python/C++ |
| **Evaluation Method** | Weighted scoring (code changes, tests, architecture) |
| **Execution** | Serial (high memory; concurrent runs risk OOM) |
| **Timeout Multiplier** | 10x |

## Tasks

| Task ID | Repository | Language | Description |
|---------|-----------|----------|-------------|
| `big-code-k8s-001` | kubernetes/kubernetes | Go | Add `NoScheduleNoTraffic` taint effect across scheduler, admission, endpoint, and node controllers |
| `big-code-vsc-001` | microsoft/vscode | TypeScript | Fix stale TypeScript diagnostics after Git branch switch by adding file-system change triggers to the diagnostics pipeline |
| `big-code-servo-001` | servo/servo | Rust | Implement `scrollend` DOM event with debouncing across the browser engine, DOM event system, and compositor |
| `big-code-trt-001` | NVIDIA/TensorRT-LLM | Python/C++ | Add `W4A8_MXFP4_INT8` quantization mode across Python/C++ enums, kernel selection, validation, and bindings |

## What This Benchmark Measures

**Does measure:**
- Agent ability to navigate and modify codebases exceeding 1GB
- Multi-subsystem feature implementation (changes span many packages/modules)
- Cross-language integration (Python/C++ boundary in TensorRT-LLM)
- Value of semantic search tools on architecturally distributed tasks
- Whether agents can follow existing patterns and conventions at scale

**Does NOT measure:**
- Performance on small or well-scoped codebases
- Bug fixing or refactoring ability (all tasks are new feature implementations)
- Agent performance diversity (only 4 tasks, each from a different repo)

## Task Structure

Each task directory follows the Harbor benchmark format:

```
big-code-{repo}-001/
├── instruction.md           # Full task description and requirements
├── task.toml                # Harbor metadata (timing, difficulty, verification)
├── reward.json              # Evaluation criteria with weights
├── CLAUDE.md                # Search strategy guidance (MCP vs local tools)
├── repo_path                # Path to repository root inside container
├── environment/
│   └── Dockerfile           # Container with pre-cloned repository
├── tests/
│   └── test.sh              # Verification script (outputs reward 0.0–1.0)
└── solution/
    └── solve.sh             # Placeholder
```

## Evaluation

Each task uses a weighted scoring scheme (0.0–1.0) defined in its `reward.json`. The general pattern:

| Criterion | Weight | Type |
|-----------|--------|------|
| Tests pass / code changes verified | 40–50% | Boolean |
| Relevant files modified | 30% | Boolean |
| Architecture understanding (tests added, correct subsystems touched) | 20–30% | Rating 0–1 |

The `tests/test.sh` script detects whether the agent made any code changes, then applies task-specific checks (e.g., grepping for new constants, verifying files were modified). A score of 0.0 means no changes were made; partial credit is awarded for incomplete implementations.

## Running the Benchmark

### Prerequisites

- Harbor installed and configured
- `~/evals/.env.local` with `ANTHROPIC_API_KEY` (required for all configs)
- `SOURCEGRAPH_ACCESS_TOKEN` and `SOURCEGRAPH_URL` (required for MCP configs)

### All Tasks, All 3 Configs

```bash
bash configs/largerepo_3config.sh
```

### Specific Configurations

```bash
bash configs/largerepo_3config.sh --baseline-only
bash configs/largerepo_3config.sh --base-only
bash configs/largerepo_3config.sh --full-only
```

### Single Task via Harbor

```bash
harbor run \
  --path benchmarks/ccb_largerepo/big-code-k8s-001 \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-opus-4-5-20251101 \
  -n 1
```

## Results

Output is written to `runs/` with one subdirectory per MCP configuration:

```
runs/{category}/largerepo_selected_opus_{TIMESTAMP}/
├── baseline/                        # No MCP
├── sourcegraph_base/       # MCP without deep search
└── sourcegraph_full/              # Full MCP (all 13 tools)
```

Per-task metrics can be extracted with:

```bash
python3 scripts/extract_task_metrics.py \
  --task-dir <result_dir> \
  --benchmark ccb_largerepo \
  --config baseline
```

## Known Limitations

1. **Small sample size** — 4 tasks across 4 different repos; not enough for statistical significance on its own.
2. **Serial execution only** — Large Docker images and high memory usage prevent parallel runs.
3. **No SCIP indexing for 3/4 repos** — Only Kubernetes has SCIP indexing; Servo, VS Code, and TensorRT-LLM rely on keyword/NLS search only.
4. **Single difficulty level** — All tasks are rated "hard"; no easy or medium tasks for calibration.

## See Also

- [MANIFEST.json](MANIFEST.json) — Benchmark metadata and task list
- [CLAUDE.md](CLAUDE.md) — Agent search strategy guidance
- [configs/largerepo_3config.sh](../../configs/largerepo_3config.sh) — 3-config runner script
- [ccb_pytorch](../ccb_pytorch/) — Related benchmark for multi-file changes in a single large repo
