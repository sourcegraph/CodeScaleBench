# CSB Task Authoring Skills

Scaffold new benchmark tasks, score task quality, and audit benchmark suites against ABC criteria. Use when creating new tasks, reviewing task quality, or auditing benchmark integrity.

**Relevant files:** `benchmarks/**`, `scripts/abc_score_task.py`, `scripts/abc_audit.py`, `configs/selected_benchmark_tasks.json`

---

## Scaffold Task

Interactively scaffold a new Harbor-compatible benchmark task. Generates task.toml, instruction.md, Dockerfile, test.sh, and registers the task.

### Phases

#### Phase 1: Mode Selection
- **Add task to existing suite** or **Create new benchmark suite**

#### Phase 2: Core Details
- Benchmark suite, Language, Difficulty, Task type (repo-clone / pre-built-image / standalone)

#### Phase 3: Task-Specific Inputs
- Task ID, Description, Repo, Commit hash, SDLC phase, Category, Time limit

#### Phase 4: File Generation

**Language → Base Image Mapping:**

| Language | Base Image |
|----------|-----------|
| go | `golang:1.23-bookworm` |
| python | `python:3.11-bookworm` |
| cpp | `gcc:13-bookworm` |
| rust | `rust:1.75-bookworm` |
| typescript | `node:20-bookworm` |
| java | `eclipse-temurin:21-bookworm` |
| mixed | `ubuntu:22.04` |

**Generated files:**
- `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/task.toml`
- `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/instruction.md`
- `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/environment/Dockerfile`
- `benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}/tests/test.sh`

#### Phase 5: Registration
Add entry to `configs/selected_benchmark_tasks.json`.

#### Phase 6: Validation
```bash
cd ~/CodeScaleBench && python3 scripts/validate_tasks_preflight.py --task benchmarks/csb_sdlc_{BENCHMARK}/{TASK_ID}
```

---

## Score Tasks

Score individual benchmark tasks on three weighted quality dimensions.

### Dimensions
- **Instruction Clarity (0.30)**: Length, structure, no placeholders, metadata present
- **Verifier Quality (0.40)**: test.sh exists, error handling, meaningful assertions, partial credit
- **Reproducibility (0.30)**: Dockerfile present, pinned versions, deterministic checkout, time limit

### Usage

```bash
# Single task
cd ~/CodeScaleBench && python3 scripts/abc_score_task.py --task benchmarks/csb_sdlc_pytorch/sgt-005

# All tasks in a suite
python3 scripts/abc_score_task.py --suite csb_sdlc_pytorch --format table

# All tasks with threshold
python3 scripts/abc_score_task.py --all --threshold 0.7 --format table

# JSON output
python3 scripts/abc_score_task.py --suite csb_sdlc_swebenchpro --format json
```

---

## Benchmark Audit

Audit benchmark suites against the ABC (Agent Benchmark Criteria) framework.

### Dimensions
- **Task Validity**: Instructions, metadata, Docker setup
- **Outcome Validity**: Verifier quality, determinism, scoring
- **Reporting**: Metrics completeness, error handling

### Usage

```bash
# Specific suite
cd ~/CodeScaleBench && python3 scripts/abc_audit.py --suite csb_sdlc_pytorch --format table

# All suites
python3 scripts/abc_audit.py --all --format table

# Critical only
python3 scripts/abc_audit.py --suite csb_sdlc_swebenchpro --critical-only

# Filter by dimension
python3 scripts/abc_audit.py --suite csb_sdlc_pytorch --dimension task_validity
```

### ABC Criteria Reference

- **T1-T5**: Task validity (instructions, metadata, Dockerfile, no placeholders, no methodology leaks)
- **O1-O4**: Outcome validity (test.sh, meaningful assertions, determinism, partial credit)
- **R1-R2**: Reporting (metrics extraction, error handling)
