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
2. Identify bottlenecks in the code
3. Design optimizations (algorithmic improvements, vectorization, caching, etc.)
4. Write your optimization as a unified diff

Do NOT modify source files directly. Write your optimization as a unified diff.
The evaluation system applies your patch and benchmarks independently.

## Deliverable

Write a unified diff to `/workspace/solution.patch` that applies cleanly against
the repository source tree. The patch should contain all changes needed to
optimize the target function.

The verifier will measure runtime improvement as:

```
runtime_reduction = 1 - (optimized_runtime / baseline_runtime)
```

Higher values indicate better optimization. A value of 0.5 means 2x speedup.

## Tips

- Ensure correctness - optimization at the cost of correctness scores 0
- Consider algorithmic complexity first, then micro-optimizations
- Use NumPy/vectorization for numerical code where applicable
- Consider caching for repeated computations
