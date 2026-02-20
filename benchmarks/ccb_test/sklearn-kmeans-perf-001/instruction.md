# SWE-Perf Performance Optimization Task

## Overview

**Task ID**: ccb_sweperf-002
**Repository**: scikit-learn
**Difficulty**: hard
**Target Function**: `sklearn.cluster._k_means._kmeans_single_elkan`
**Baseline Runtime**: 0.182000 seconds

---

## Description

Optimize the K-Means clustering single iteration using Elkan's algorithm for distance computation pruning.

## Target Function

The function to optimize is located at:
- **File**: sklearn/cluster/_k_means_elkan.pyx
- **Function**: `sklearn.cluster._k_means._kmeans_single_elkan`

## Baseline Performance

The current baseline runtime is **0.182000 seconds**.
Your goal is to reduce this runtime while maintaining correctness.


### Optimization Hints

- Use triangle inequality to skip redundant distance calculations
- Maintain upper and lower bounds for cluster assignments
- Consider Cython optimizations for inner loops


## Human Reference

For reference, here is how humans approached this optimization:
Applied triangle inequality optimization (Elkan's algorithm) to skip unnecessary distance calculations, reducing complexity from O(nkd) to O(nkd/b) where b is the pruning factor.

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
