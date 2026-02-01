# LoCoBench-Agent Harbor Adapter

Harbor adapter for [LoCoBench-Agent](https://github.com/locobench/locobench-agent) benchmark tasks. Converts LoCoBench-Agent's 8,000 interactive scenarios into Harbor task format for evaluating code search and codebase understanding tools.

## Overview

- **8,000 scenarios** across 10 programming languages and 8 task categories
- **Selected subset**: 50 high-complexity tasks optimized for MCP value demonstration
- **Language-specific Dockerfiles** for fast builds (no multi-language mega-image)
- **Semantic verifier** using keyword overlap scoring

## Quick Start

```bash
# 1. Download data (if not already present)
# Data should be at benchmarks/locobench_agent/data/
# - generated/  (1000 synthetic projects)
# - output/scenarios/  (8000 task JSON files)

# 2. Extract to JSONL format
python benchmarks/locobench_agent/extract_dataset.py

# 3. Select top 50 tasks by MCP value
python benchmarks/locobench_agent/select_tasks.py

# 4. Generate Harbor tasks
python benchmarks/locobench_agent/run_adapter.py \
    --dataset_path benchmarks/locobench_agent/locobench_dataset.jsonl \
    --output_dir benchmarks/locobench_agent/tasks \
    --selected_tasks benchmarks/locobench_agent/selected_tasks.json

# 5. Run a task with Harbor
harbor run -a <agent> \
    -p benchmarks/locobench_agent/tasks/<task_id> \
    -n 1
```

## Task Selection Criteria

Tasks are selected to maximize MCP tool value demonstration:

| Factor | Weight | Description |
|--------|--------|-------------|
| context_length | 0.3 | Larger context = more search needed |
| files_count | 0.3 | More files = cross-file reasoning |
| task_category | 0.4 | Category bonus (architectural=1.0, cross_file=0.9, bug=0.8) |

**Minimum thresholds**: context_length > 50K tokens, files_count > 5

See [docs/TASK_SELECTION_CRITERIA.md](docs/TASK_SELECTION_CRITERIA.md) for details.

## Task Categories

| Category | MCP Value | Description |
|----------|-----------|-------------|
| architectural_understanding | High | System-wide structure analysis |
| cross_file_refactoring | High | Multi-file changes |
| bug_investigation | High | Root cause analysis |
| security_analysis | Medium | Vulnerability identification |
| feature_implementation | Medium | Adding functionality |
| code_comprehension | Lower | Understanding specific code |
| integration_testing | Lower | Test design |
| multi_session_development | Lower | Iterative development |

## Generated Task Structure

Each task directory contains:

```
tasks/<task_id>/
├── instruction.md          # Task prompt and context
├── task.toml               # Harbor metadata
├── environment/
│   ├── Dockerfile          # Language-specific (fast builds)
│   └── project/            # Synthetic codebase
├── tests/
│   ├── test.sh             # Verification entry point
│   ├── verify.py           # Semantic similarity scorer
│   ├── ground_truth.json   # Expected solution
│   └── task_metadata.json  # Task info
└── solution/
    └── solve.sh            # Oracle solution for testing
```

## CLI Reference

### extract_dataset.py

Extracts scenarios from raw JSON to normalized JSONL.

```bash
python extract_dataset.py
# Output: locobench_dataset.jsonl (8000 tasks)
```

### select_tasks.py

Scores and selects top tasks by MCP value.

```bash
python select_tasks.py
# Output: selected_tasks.json (top 50 tasks with scores)
```

### run_adapter.py

Generates Harbor task directories.

```bash
# Generate from selected tasks
python run_adapter.py \
    --dataset_path locobench_dataset.jsonl \
    --output_dir ./tasks \
    --selected_tasks selected_tasks.json

# Generate specific tasks
python run_adapter.py \
    --dataset_path locobench_dataset.jsonl \
    --output_dir ./tasks \
    --task_ids task_id_1 task_id_2

# Generate with limit
python run_adapter.py \
    --dataset_path locobench_dataset.jsonl \
    --output_dir ./tasks \
    --limit 10
```

## Verification

The verifier (`verify.py`) scores solutions using:

| Metric | Weight | Description |
|--------|--------|-------------|
| keyword_overlap | 0.5 | F1 score of keywords vs ground truth |
| file_references | 0.2 | References to context files |
| code_blocks | 0.2 | Presence of code in solution |
| length_score | 0.1 | Solution length (min 100 words) |

Output: `/logs/verifier/reward.json` with score 0.0-1.0

## Language Support

Tasks span 10 languages with dedicated Dockerfiles:

- C, C++, C#, Go, Java, JavaScript, PHP, Python, Rust, TypeScript

Each Dockerfile installs only the required language toolchain + Python for the verifier.

## Files

| File | Description |
|------|-------------|
| adapter.py | LoCoBenchTask, LoCoBenchLoader, LoCoBenchAdapter |
| extract_dataset.py | Raw JSON to JSONL extraction |
| select_tasks.py | Task scoring and selection |
| run_adapter.py | CLI for task generation |
| templates/ | Harbor task templates |
| DATA_EXPLORATION.md | Dataset structure documentation |
| docs/TASK_SELECTION_CRITERIA.md | Selection criteria details |
| SMOKE_TEST_RESULTS.md | Validation test results |
