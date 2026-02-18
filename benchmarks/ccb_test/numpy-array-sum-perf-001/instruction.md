# SWE-Perf Performance Optimization Task

## Overview

**Task ID**: ccb_sweperf-001
**Repository**: numpy
**Difficulty**: medium
**Target Function**: `numpy.core.multiarray.array_sum`
**Baseline Runtime**: 0.045000 seconds

---

## Description

Optimize the array summation function to reduce computation time for large multi-dimensional arrays.

## Target Function

The function to optimize is located at:
- **File**: numpy/core/src/multiarray/calculation.c
- **Function**: `numpy.core.multiarray.array_sum`

## Baseline Performance

The current baseline runtime is **0.045000 seconds**.
Your goal is to reduce this runtime while maintaining correctness.


### Optimization Hints

- Consider using SIMD instructions via NumPy's ufunc mechanism
- Evaluate memory access patterns for cache efficiency
- Profile with line_profiler to identify bottlenecks


## Human Reference

For reference, here is how humans approached this optimization:
Replaced naive loop with vectorized NumPy operations using np.einsum for efficient summation across axes.

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
python -m pytest tests/test_array_ops.py -v -k sum
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

## Deliverable

After optimizing the code, write benchmark results to `/workspace/benchmark_results.json`:

```json
{
    "task_id": "ccb_sweperf-001",
    "optimized_runtime": 0.05,
    "baseline_runtime": 0.045000,
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
