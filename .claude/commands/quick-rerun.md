Rerun a single task with haiku model for fast verification.

## Steps

1. Identify the task to rerun (from failure triage or gap analysis)
2. Find the benchmark suite and task directory
3. Run with haiku for quick turnaround:
```bash
harbor run --path benchmarks/<suite>/<task_dir> --model haiku
```

4. Check results in runs/staging/

## Arguments

$ARGUMENTS — task name or path to rerun
