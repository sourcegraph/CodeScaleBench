---
name: benchmark-audit
description: Audit benchmark suites against ABC framework (Task/Outcome/Reporting validity). Checks instruction quality, verifier correctness, reproducibility. Triggers on benchmark audit, audit benchmark, abc audit, task validity.
user-invocable: true
---

# Benchmark Audit

Audit benchmark suites against the ABC (Agent Benchmark Criteria) framework across three dimensions: Task Validity, Outcome Validity, and Reporting.

## What This Does

Runs `scripts/abc_audit.py` which:
1. Checks each benchmark task against ABC criteria
2. Evaluates Task Validity (instructions, metadata, Docker setup)
3. Evaluates Outcome Validity (verifier quality, determinism, scoring)
4. Evaluates Reporting (metrics completeness, error handling)
5. Produces letter grades (A-F) per dimension and overall

## Steps

### 1. Audit a specific suite

```bash
cd ~/CodeScaleBench && python3 scripts/abc_audit.py --suite csb_sdlc_pytorch --format table
```

### 2. Audit all suites

```bash
python3 scripts/abc_audit.py --all --format table
```

### 3. Show only critical issues

```bash
python3 scripts/abc_audit.py --suite csb_sdlc_swebenchpro --critical-only
```

### 4. JSON output for detailed analysis

```bash
python3 scripts/abc_audit.py --all --format json
```

### 5. Filter by dimension

```bash
python3 scripts/abc_audit.py --suite csb_sdlc_pytorch --dimension task_validity
python3 scripts/abc_audit.py --suite csb_sdlc_pytorch --dimension outcome_validity
```

### 6. Present findings

For each suite, present:

| Dimension | Grade | Score | Critical Issues | Warnings |
|-----------|-------|------:|----------------:|---------:|
| Task Validity | B+ | 0.85 | 0 | 2 |
| Outcome Validity | A- | 0.90 | 0 | 1 |
| Reporting | B | 0.80 | 1 | 3 |
| **Overall** | **B+** | **0.85** | **1** | **6** |

List any critical issues with their criterion ID and recommended fix.

## ABC Criteria Reference

- **T1**: Instructions present and non-empty
- **T2**: task.toml has required fields (time_limit_sec, language, difficulty)
- **T3**: Dockerfile builds successfully
- **T4**: No template placeholders in instructions
- **T5**: Instructions don't leak evaluation methodology
- **O1**: test.sh exists and is executable
- **O2**: Verifier has meaningful assertions (not just exit 0)
- **O3**: Scoring is deterministic (same input → same score)
- **O4**: Partial credit where appropriate
- **R1**: Metrics extraction works (result.json → task_metrics.json)
- **R2**: Error handling doesn't mask failures

## Related Skills

- `/score-tasks` — Score individual task quality (instruction clarity, verifier quality, reproducibility)
- `/validate-tasks` — Pre-flight validation (lighter, focused on "will this run?")
