# SWE-Perf Performance Optimization Task

## Overview

**Task ID**: ccb_sweperf-003
**Repository**: pandas
**Difficulty**: medium
**Target Function**: `pandas.core.groupby.ops.GroupBy._aggregate_series_fast`
**Baseline Runtime**: 0.095000 seconds

---

## Description

Optimize the series aggregation in groupby operations for better performance on large datasets.

## Target Function

The function to optimize is located at:
- **File**: pandas/_libs/groupby.pyx
- **Function**: `pandas.core.groupby.ops.GroupBy._aggregate_series_fast`

## Baseline Performance

The current baseline runtime is **0.095000 seconds**.
Your goal is to reduce this runtime while maintaining correctness.


### Optimization Hints

- Leverage pandas' internal Cython-based hash tables
- Minimize Python object creation in tight loops
- Consider memory alignment for better cache performance


## Human Reference

For reference, here is how humans approached this optimization:
Replaced Python dictionary-based aggregation with Cython-optimized hash table lookup using pandas' internal khash implementation.

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

The verifier will measure runtime improvement relative to the baseline. Greater
speedups yield higher scores.

## Tips

- Ensure correctness - optimization at the cost of correctness scores 0
- Consider algorithmic complexity first, then micro-optimizations
- Use NumPy/vectorization for numerical code where applicable
- Consider caching for repeated computations
