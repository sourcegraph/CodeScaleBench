# SWE-Perf Performance Optimization Task

## Overview

**Task ID**: {id}
**Repository**: {repo_name}
**Difficulty**: {difficulty}
**Target Function**: `{target_function}`
**Baseline Runtime**: {baseline_runtime} seconds

---

## Description

{description}

## Target Function

The function to optimize is located at:
- **File**: {file_path}
- **Function**: `{target_function}`

## Baseline Performance

The current baseline runtime is **{baseline_runtime} seconds**.
Your goal is to reduce this runtime while maintaining correctness.

{optimization_hints}

## Human Reference

For reference, here is how humans approached this optimization:
{human_solution_reference}

---

## Instructions

1. Analyze the target function and understand its purpose
2. Profile the code to identify bottlenecks
3. Apply optimizations (algorithmic improvements, vectorization, caching, etc.)
4. Ensure all existing tests pass
5. Benchmark your optimized solution

## Testing

Run the benchmarks with:
```bash
{test_command}
```

## Output

Your optimized code should be in `/workspace/optimized/`.
The verifier will measure runtime improvement as:

```
runtime_reduction = 1 - (optimized_runtime / baseline_runtime)
```

Higher values indicate better optimization. A value of 0.5 means 2x speedup.

## Workspace Structure

```
/workspace/
├── original/          # Original code (read-only reference)
├── optimized/         # Your optimized implementation
├── tests/             # Test suite
└── benchmark_results.json  # Your benchmark output
```

## Output Format

After optimizing the code, write benchmark results to `/workspace/benchmark_results.json`:

```json
{
    "task_id": "{id}",
    "optimized_runtime": 0.05,
    "baseline_runtime": {baseline_runtime},
    "tests_passed": true,
    "tests_total": 10,
    "optimization_notes": "Applied vectorization to inner loop"
}
```

The verifier will use the `optimized_runtime` field to compute your score.

## Tips

- Profile before optimizing to find the real bottlenecks
- Ensure correctness - optimization at the cost of correctness scores 0
- Consider algorithmic complexity first, then micro-optimizations
- Use NumPy/vectorization for numerical code where applicable
- Consider caching for repeated computations
