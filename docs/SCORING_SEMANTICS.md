# Scoring Semantics

How each benchmark is scored, what the numbers mean, and known limitations.

## Scoring Types

| Type | Range | Description |
|------|-------|-------------|
| **binary** | 0.0 or 1.0 | Pass/fail — all tests must pass |
| **checklist** | 0.0–1.0 continuous | Weighted sum of boolean checks |
| **test-ratio** | 0.0–1.0 continuous | Fraction of test cases passing |
| **similarity** | 0.0–1.0 continuous | Semantic or keyword similarity to ground truth |
| **F1-hybrid** | 0.0–1.0 continuous | Detection F1 blended with fix quality |
| **ordering** | 0.0–1.0 continuous | Position-exact-match blended with rank correlation |
| **external** | 0.0–1.0 continuous | External verifier (e.g., TheAgentCompany eval) |

## Per-Benchmark Scoring

### SWE-bench Pro
- **Type**: test-ratio (pytest-based)
- **Mechanism**: Runs project-specific pytest suite; score = fraction of tests passing
- **Good score**: 1.0 (all repo tests pass)
- **Limitations**: Upstream test suites vary in granularity. Some tasks have 1 test (binary effective), others have 50+. Score does not penalize regressions in unrelated tests.

### DependEval
- **Type**: ordering (position-exact + Kendall tau)
- **Mechanism**: `score = 0.6 * position_exact_match + 0.4 * kendall_tau_normalized`
- **Good score**: ≥0.8 (most files in correct dependency order)
- **Limitations**: Does not verify that the ordering is a valid topological sort — only compares against a single reference ordering. Near-correct orderings (single swap) now receive partial credit via Kendall tau.

### PyTorch
- **Type**: diff_similarity (diff-based)
- **Mechanism**: Compares agent's code changes against expected ground-truth diff; score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision. sgt-001 uses a custom verifier (file + pattern checks).
- **Good score**: >= 0.5 (correct files touched with matching changes)
- **Limitations**: Diff similarity rewards matching the reference solution line-by-line; functionally equivalent but differently structured fixes may score lower. sgt-025 dropped from selection (Docker permanently broken: commit SHA unreachable).

### LoCoBench
- **Type**: similarity (weighted multi-signal)
- **Mechanism**: Blends keyword overlap (0.40), file references (0.25), code blocks (0.15), length (0.10), structural coherence (0.10)
- **Good score**: ≥0.6 (meaningful analysis with relevant references)
- **Limitations**: Unigram+bigram keyword matching can't verify semantic correctness. Code block scoring requires ground-truth keyword presence but doesn't verify code correctness.

### RepoQA
- **Type**: similarity (semantic retrieval)
- **Mechanism**: Verifier checks if agent identified correct function and path; score = correct_function (0.0 or 1.0)
- **Good score**: 1.0 (correct function identified)
- **Limitations**: Binary in practice (correct function or not). Justification quality not scored.

### K8s Docs
- **Type**: checklist (weighted keyword checks)
- **Mechanism**: Multi-check scoring: file exists (0.1), minimum content (0.1), keyword presence with negation filtering (0.8 across checks)
- **Good score**: ≥0.7 (comprehensive documentation with key concepts)
- **Limitations**: Keyword checks are context-aware (reject negated mentions) but can't verify technical accuracy. Minimum word count prevents empty-file gaming.

### CrossRepo
- **Type**: similarity (patch validation)
- **Mechanism**: `score = 0.4 * file_coverage + 0.6 * pattern_score`
- **Good score**: ≥0.6 (correct files modified with expected patterns)
- **Limitations**: Pattern matching is regex-based and may miss valid alternative implementations. Fallback diff collection restricted to expected file paths to prevent gaming.

### LargeRepo
- **Type**: checklist (compilation + keyword + test)
- **Mechanism**: Weighted checks: keyword presence (0.3), relevant file changes in ≥2 files (0.2), test additions (0.2), unit tests pass (0.3)
- **Good score**: ≥0.7 (keyword found, tests pass, multi-file changes)
- **Limitations**: Keyword-based scoring can't verify implementation correctness. Compilation check provides strong signal but only covers modified packages.

### CodeReview
- **Type**: F1-hybrid (detection + fix quality)
- **Mechanism**: `score = 0.5 * detection_F1 + 0.5 * fix_score`. Detection matches reported defects to expected defects by file path. Fix scoring checks for correct fix patterns with multiple acceptable alternatives.
- **Good score**: ≥0.7 (most defects found and fixed)
- **Limitations**: Fix pattern matching accepts alternatives but may miss novel correct approaches. Detection is file-path-based — reporting the right file but wrong defect counts as a match.

### TAC (TheAgentCompany)
- **Type**: external (TAC eval.py)
- **Mechanism**: External evaluator from TheAgentCompany; scores task completion
- **Good score**: 1.0
- **Limitations**: External verifier — not modified by this project.

### DIBench
- **Type**: test-ratio
- **Mechanism**: Runs dependency installation tests; score = fraction passing
- **Good score**: 1.0 (all dependencies installed correctly)
- **Limitations**: Network-dependent tasks may fail due to registry availability.

### SWE-Perf
- **Type**: external (task-specific verifier)
- **Mechanism**: Performance benchmarks with custom verification
- **Good score**: 1.0
- **Limitations**: External verifiers — not modified by this project.

### LinuxFLBench
- **Type**: checklist (fault localization accuracy)
- **Mechanism**: Checks if agent identified correct buggy file and functions. Ground truth loaded from `tests/ground_truth.json`.
- **Good score**: ≥0.7 (correct file and at least one correct function)
- **Limitations**: Only accepts exact file path and function name matches.

## Score Distribution Expectations

| Benchmark | Expected Baseline Range | Notes |
|-----------|------------------------|-------|
| SWE-bench Pro | 0.3–0.5 | Hard real-world bugs |
| DependEval | 0.3–0.6 | Ordering is partially correct for most |
| PyTorch | 0.05–0.25 | Diff similarity; 11 tasks (sgt-025 dropped) |
| LoCoBench | 0.4–0.6 | Similarity-based, partial credit common |
| RepoQA | 0.5–0.8 | Binary per-task, varies by difficulty |
| K8s Docs | 0.5–0.8 | Documentation generation is tractable |
| CrossRepo | 0.3–0.6 | Multi-repo coordination is hard |
| LargeRepo | 0.2–0.5 | Large codebase navigation required |
| CodeReview | 0.3–0.6 | Finding + fixing defects |
| TAC | 0.3–0.6 | Tool-augmented, network-dependent |
| DIBench | 0.4–0.7 | Dependency installation |
| SWE-Perf | 0.3–0.6 | Performance optimization |
| LinuxFLBench | 0.2–0.5 | Kernel fault localization |
