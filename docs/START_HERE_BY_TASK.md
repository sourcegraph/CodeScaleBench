# Start Here By Task

Use this page first for operational work. Each path is intentionally short to minimize context loading.

## Launch / Rerun Benchmarks
### When To Read This
- You are about to run a benchmark batch or scoped rerun.

### Read Order
1. `docs/ops/WORKFLOWS.md`
2. `docs/reference/CONFIGS.md`
3. `docs/DAYTONA.md (Daytona is default)`
4. `docs/ops/QA_PROCESS.md`

### Key Commands
```bash
python3 scripts/check_infra.py
python3 scripts/validate_tasks_preflight.py --all

# Daytona Cloud (default — up to 125 concurrent sandboxes, no local Docker needed)
export HARBOR_ENV=daytona DAYTONA_OVERRIDE_STORAGE=10240
# use configs/*_2config.sh wrappers for paired baseline/MCP runs

# Local Docker (only for 21 sweap-images tasks incompatible with Daytona)
# use configs/* runner with interactive confirmation gate, unset HARBOR_ENV
```

## Monitor Active Runs
### When To Read This
- A run is in progress and you need status, classification, or summaries.

### Read Order
1. `docs/ops/WORKFLOWS.md`
2. `docs/ERROR_CATALOG.md`
3. `docs/ops/SCRIPT_INDEX.md`

### Key Commands
```bash
python3 scripts/aggregate_status.py --staging
python3 scripts/mcp_audit.py --run <run_dir>
```

## Triage Failed Tasks
### When To Read This
- You need root cause and targeted rerun guidance.

### Read Order
1. `docs/ERROR_CATALOG.md`
2. `docs/ops/QA_PROCESS.md`
3. `docs/ops/TROUBLESHOOTING.md`

### Key Commands
```bash
python3 scripts/validate_task_run.py --run <run_dir>
python3 scripts/rerun_failed.py --help
```

## Analyze Results (Configs / MCP / IR / Cost)
### When To Read This
- You are comparing configs or evaluating MCP/retrieval impact.

### Read Order
1. `docs/EVALUATION_PIPELINE.md`
2. `docs/RETRIEVAL_EVAL_SPEC.md`
3. `docs/SCORING_SEMANTICS.md`

### Key Commands
```bash
python3 scripts/compare_configs.py --run <run_dir>
python3 scripts/mcp_audit.py --run <run_dir>
python3 scripts/ir_analysis.py --run <run_dir>
python3 scripts/cost_report.py --run <run_dir>
```

## Generate Reports / Submission Artifacts
### When To Read This
- You are finalizing a run and producing canonical outputs.

### Read Order
1. `docs/EVALUATION_PIPELINE.md`
2. `docs/SUBMISSION.md`
3. `docs/LEADERBOARD.md`

### Key Commands
```bash
python3 scripts/generate_manifest.py
python3 scripts/generate_eval_report.py
python3 scripts/package_submission.py --help
```

## Modify Tasks / Task Metadata
### When To Read This
- You are changing task definitions, metadata, or suite composition.

### Read Order
1. `docs/TASK_SELECTION.md`
2. `docs/TASK_CATALOG.md`
3. `docs/EXTENSIBILITY.md`

### Key Commands
```bash
python3 scripts/validate_tasks_preflight.py --task <task_dir> --smoke-runtime
python3 scripts/sync_task_metadata.py --help
```
