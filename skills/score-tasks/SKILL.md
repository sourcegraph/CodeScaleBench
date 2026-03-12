---
name: score-tasks
description: Score individual task quality on instruction clarity, verifier quality, and reproducibility. Triggers on score task, task quality, rate tasks, task score.
user-invocable: true
---

# Score Tasks

Score individual benchmark tasks on three weighted quality dimensions.

## What This Does

Runs `scripts/abc_score_task.py` which scores tasks on:
- **Instruction Clarity (0.30)**: Length, structure, no placeholders, metadata present
- **Verifier Quality (0.40)**: test.sh exists, error handling, meaningful assertions, partial credit
- **Reproducibility (0.30)**: Dockerfile present, pinned versions, deterministic checkout, time limit set

## Steps

### 1. Score a single task

```bash
cd ~/CodeScaleBench && python3 scripts/abc_score_task.py --task benchmarks/csb_sdlc_pytorch/sgt-005
```

### 2. Score all tasks in a suite

```bash
python3 scripts/abc_score_task.py --suite csb_sdlc_pytorch --format table
```

### 3. Score all tasks with threshold

Flag tasks scoring below the threshold as needing review:
```bash
python3 scripts/abc_score_task.py --all --threshold 0.7 --format table
```

### 4. JSON output

```bash
python3 scripts/abc_score_task.py --suite csb_sdlc_swebenchpro --format json
```

### 5. Present findings

**Suite summary:**

| Task | Overall | Instruction | Verifier | Reproducibility | Needs Review |
|------|--------:|------------:|---------:|----------------:|:------------:|
| sgt-005 | 0.85 | 0.90 | 0.80 | 0.85 | No |
| sgt-008 | 0.65 | 0.70 | 0.55 | 0.70 | Yes |

Highlight tasks that need review and explain which sub-checks failed.

## Related Skills

- `/benchmark-audit` — Suite-level ABC audit (broader, checks outcome and reporting too)
- `/validate-tasks` — Pre-flight validation (operational, not quality scoring)
