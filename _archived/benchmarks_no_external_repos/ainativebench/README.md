# AINativeBench Adapter

Harbor adapter for the AINativeBench benchmark suite.

## Overview

AINativeBench is a benchmark suite consisting of 8 specialized benchmarks, each with 4 difficulty variants for evaluating AI coding agents on repository-level tasks.

### Supported Benchmarks

| Benchmark | Description |
|-----------|-------------|
| RepoBench | Repository-level code completion |
| CrossCodeEval | Cross-file code evaluation |
| RepoExec | Repository-level code execution |
| SWE-bench | Software engineering problem solving |
| DevBench | Developer benchmark tasks |
| Cocomic | Code completion with context |
| EvoCodeBench | Evolution-based code benchmark |
| MdEval | Multi-document evaluation |

### Variants

Each benchmark has 4 variants:
- `easy` - Basic difficulty tasks
- `medium` - Moderate difficulty tasks
- `hard` - Advanced difficulty tasks
- `retrieval` - Tasks requiring context retrieval (MCP-optimized)

## Setup Requirements

### Data Directory

The adapter expects task data in `benchmarks/ainativebench/data/` with the following structure:

```
data/
├── repobench/
│   ├── easy/
│   │   ├── task_001.json
│   │   └── ...
│   ├── medium/
│   ├── hard/
│   └── retrieval/
├── crosscodeeval/
│   └── ...
└── ...
```

Each task JSON file should have the following structure:

```json
{
  "id": "repobench-easy-001",
  "benchmark_name": "repobench",
  "variant": "easy",
  "description": "Task description",
  "language": "python",
  "context_files": ["file1.py", "file2.py"],
  "test_cases": [
    {
      "name": "test_example",
      "input_data": {"key": "value"},
      "expected_output": {"result": "expected"},
      "timeout_sec": 60
    }
  ],
  "scoring_metrics": {
    "primary_metric": "pass_rate",
    "secondary_metrics": [],
    "thresholds": {"pass_rate": 0.8}
  },
  "ground_truth": {},
  "metadata": {}
}
```

### Alternative: Manifest-Based Loading

The loader also supports a manifest-based structure:

```
data/
├── manifest.json
└── tasks/
    ├── repobench-easy-001.json
    └── ...
```

Where `manifest.json` contains:
```json
{
  "tasks": ["repobench-easy-001.json", "repobench-easy-002.json"]
}
```

## Usage

### Generate All Tasks

```bash
python run_adapter.py --output_dir ./tasks/
```

### Filter by Benchmark

```bash
python run_adapter.py --output_dir ./tasks/ --benchmark repobench
```

### Filter by Variant

```bash
python run_adapter.py --output_dir ./tasks/ --variant easy
```

### Combined Filters with Limit

```bash
python run_adapter.py --output_dir ./tasks/ --benchmark swe-bench --variant hard --limit 10
```

### Custom Data Directory

```bash
python run_adapter.py --output_dir ./tasks/ --data_dir /path/to/custom/data/
```

## Generated Task Structure

Each generated Harbor task has the following structure:

```
task_id/
├── task.toml           # Task configuration and metadata
├── instruction.md      # Instructions for the agent
├── environment/
│   ├── Dockerfile      # Python 3.10 with uv package manager
│   └── project/        # Workspace directory
└── tests/
    ├── test.sh         # Verification shell script
    ├── verify.py       # Python verifier for test_results/
    └── ground_truth.json
```

## Verification

The verifier expects agents to write test results to `/test_results/` as JSON files:

```json
{
  "test_name": "test_example",
  "passed": true,
  "output": "actual result",
  "expected": "expected result"
}
```

The verifier parses all JSON files in the directory and computes the `pass_rate` metric.

## Smoke Testing

Run smoke tests to validate the adapter:

```bash
python scripts/smoke_test_adapter.py --adapter_dir ./benchmarks/ainativebench/ --num_tasks 3
```

With Docker build validation:
```bash
python scripts/smoke_test_adapter.py --adapter_dir ./benchmarks/ainativebench/ --num_tasks 3 --build
```

## Harbor Integration

### task.toml Tags

Generated tasks include these tags for filtering:
- `ainativebench` - Identifies this benchmark
- `{benchmark_name}` - Specific benchmark (e.g., `repobench`)
- `{variant}` - Difficulty level
- `{language}` - Programming language

### MCP Optimization

Tasks with `model_hint = "requires-mcp"` are designed to benefit from MCP tools:
- Semantic search across repository files
- Cross-file context retrieval
- Code navigation and understanding

### Reward Format

The verifier outputs Harbor-compatible `reward.json`:

```json
{
  "score": 0.67,
  "metrics": {
    "pass_rate": 0.67,
    "total_tests": 3,
    "passed_tests": 2,
    "failed_tests": 1
  },
  "primary_metric": "pass_rate",
  "test_details": [...]
}
```
