# SWE-Perf Adapter

Harbor benchmark adapter for SWE-Perf - a performance optimization benchmark for evaluating AI agents' ability to optimize Python code.

## Overview

SWE-Perf contains 140 performance optimization instances from real Python repositories. Each task challenges an agent to optimize a specific function for better runtime performance while maintaining correctness.

The primary evaluation metric is **runtime_reduction**:
```
runtime_reduction = 1 - (optimized_runtime / baseline_runtime)
```

- `0.0` = no improvement
- `0.5` = 2x speedup
- `0.9` = 10x speedup

## Task Structure

Each generated Harbor task contains:

```
{task_id}/
├── task.toml           # Task configuration with primary_metric = "runtime_reduction"
├── instruction.md      # Task instructions including optimization hints
├── environment/
│   └── Dockerfile      # Python 3.10 environment with benchmarking tools
└── tests/
    ├── test.sh         # Verification script
    ├── verify.py       # Runtime reduction calculator
    └── ground_truth.json  # Baseline runtime and reference solution
```

## Data Directory Structure

The adapter loads tasks from `benchmarks/sweperf/data/`:

```
data/
├── tasks.json          # Combined file with all instances (optional)
├── manifest.json       # Manifest-based loading (optional)
├── instances/          # Individual task files (optional)
│   ├── task_001.json
│   └── ...
└── *.json              # Direct JSON files in data/ (fallback)
```

### Task JSON Schema

```json
{
  "id": "sweperf-001",
  "repo_name": "numpy",
  "target_function": "numpy.core.multiarray.array_sum",
  "human_solution_reference": "Description of human optimization approach",
  "baseline_runtime": 0.045,
  "description": "Task description",
  "difficulty": "medium",
  "file_path": "path/to/source/file.py",
  "test_command": "python -m pytest tests/ -v",
  "optimization_hints": [
    "Hint 1",
    "Hint 2"
  ],
  "metadata": {
    "expected_speedup": 2.5,
    "optimization_category": "vectorization"
  }
}
```

## Usage

### Generate Tasks

```bash
# Generate all tasks
python run_adapter.py --output_dir ./tasks/

# Filter by repository
python run_adapter.py --output_dir ./tasks/ --repo numpy

# Limit number of tasks
python run_adapter.py --output_dir ./tasks/ --limit 10

# Combine filters
python run_adapter.py --output_dir ./tasks/ --repo scikit-learn --limit 5
```

### CLI Options

| Flag | Description |
|------|-------------|
| `--output_dir` | Output directory for generated Harbor tasks (required) |
| `--data_dir` | Path to SWE-Perf data directory (default: `benchmarks/sweperf/data/`) |
| `--repo` | Filter by repository name (e.g., `numpy`, `scikit-learn`) |
| `--limit` | Maximum number of tasks to generate |

### Programmatic API

```python
from benchmarks.sweperf.adapter import SWEPerfAdapter, SWEPerfLoader

# Load tasks
loader = SWEPerfLoader("path/to/data")
tasks = loader.load()
print(f"Loaded {len(tasks)} tasks")

# Filter by repository
numpy_tasks = loader.filter_by_repo("numpy")

# Filter by difficulty
hard_tasks = loader.filter_by_difficulty("hard")

# Filter by runtime range (for task selection)
fast_tasks = loader.filter_by_baseline_runtime(max_runtime=0.1)

# Generate Harbor tasks
adapter = SWEPerfAdapter(task_dir="./output", data_dir="path/to/data")
adapter.generate_task("sweperf-001")
```

## Reward JSON Format

The verifier outputs `reward.json` in Harbor-compatible format:

```json
{
  "score": 0.5,
  "runtime_reduction": 0.5,
  "metrics": {
    "baseline_runtime": 1.0,
    "optimized_runtime": 0.5,
    "speedup": 2.0,
    "tests_passed": true
  }
}
```

**Score Interpretation:**
- Score equals `runtime_reduction` (0.0 to 1.0)
- Correctness failure (`tests_passed: false`) results in score 0.0
- Missing benchmark results results in score 0.0

## Workspace Structure (Agent View)

```
/workspace/
├── original/          # Original code (read-only reference)
├── optimized/         # Agent's optimized implementation
├── tests/             # Test suite
└── benchmark_results.json  # Agent's benchmark output (optional)
```

The verifier reads `benchmark_results.json` from the workspace if available:

```json
{
  "optimized_runtime": 0.5,
  "tests_passed": true
}
```

## Requirements

- Python 3.10+
- Docker (for running tasks)

### Python Dependencies

- `pytest` - Test framework
- `pytest-benchmark` - Benchmarking
- `pyperf` - Performance measurement
- `memory_profiler` - Memory profiling
- `line_profiler` - Line-by-line profiling

## Testing

Run adapter tests:

```bash
python -m pytest benchmarks/sweperf/tests/test_adapter.py -v
```

Run smoke test:

```bash
python scripts/smoke_test_adapter.py --adapter_dir ./benchmarks/sweperf/ --num_tasks 3
```

## References

- [SWE-Perf Paper/Repository](https://github.com/sweperf/sweperf) (placeholder)
- [Harbor Benchmark Framework](https://harbor.ai/) (placeholder)
