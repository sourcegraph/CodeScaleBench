# 10Figure Benchmark Tasks

This directory contains Harbor task definitions generated from the 10Figure benchmark corpus. Tasks are generated using `runners/gen_harbor_tasks.py` from 10Figure YAML task definitions.

## Directory Structure

```
10figure/
├── MANIFEST.json             # Benchmark metadata (updated after generation)
├── README.md                 # This file
├── templates/
│   └── test.sh.j2            # Jinja2 template for test script generation
├── synthetic_test_data/      # Example YAML files for validation
│   ├── cross_file_reasoning_01.yaml
│   ├── refactor_rename_01.yaml
│   ├── api_upgrade_01.yaml
│   └── bug_localization_01.yaml
└── [generated task dirs]     # Individual benchmark tasks (after generation)
    └── <task_id>/
        ├── instruction.md    # Human-readable task description
        ├── task.toml         # Harbor task metadata
        ├── task.yaml         # 10Figure task definition (for validator)
        ├── repo_path         # Path to repository in container
        ├── environment/
        │   └── Dockerfile    # Task container setup
        └── tests/
            └── test.sh       # Validation script (generated from template)
```

## Expected Corpus Input Format

The generator expects a directory of YAML files, one per task. Each YAML file must contain at minimum:

- `task_id` (string, required): Unique identifier for the task
- `task_type` (string, required): One of `cross_file_reasoning`, `refactor_rename`, `api_upgrade`, `bug_localization`

Additional fields depend on the task type:

### cross_file_reasoning

```yaml
task_id: "10fig-cfr-001"
task_type: "cross_file_reasoning"
description: "Trace the NewPodAdmissionHandler call chain"
start_symbol: "NewPodAdmissionHandler"       # Symbol to start tracing from
goal: "Find where pod resource limits are validated"  # What the agent should accomplish
difficulty: "hard"                           # Optional: hard (default), medium
language: "go"                               # Optional: defaults to go
ground_truth:                                # Optional: for validator
  files:
    - "pkg/kubelet/lifecycle/handlers.go"
```

### refactor_rename

```yaml
task_id: "10fig-rr-001"
task_type: "refactor_rename"
description: "Rename GetPodStatus to FetchPodStatus"
symbol_to_rename: "GetPodStatus"             # Symbol to rename
new_name: "FetchPodStatus"                   # New name
difficulty: "medium"
language: "go"
ground_truth:
  affected_files:
    - "pkg/kubelet/kubelet.go"
```

### api_upgrade

```yaml
task_id: "10fig-au-001"
task_type: "api_upgrade"
description: "Migrate from deprecated API"
old_api: "runtime.GOMAXPROCS"                # Deprecated API
new_api: "runtime.SetMaxProcs"               # Replacement API
difficulty: "hard"
language: "go"
ground_truth:
  call_sites: 12
```

### bug_localization

```yaml
task_id: "10fig-bl-001"
task_type: "bug_localization"
description: "Fix nil pointer dereference"
error_message: "panic: runtime error: ..."   # Error message
symptoms:                                    # List of observable symptoms
  - "Pod enters CrashLoopBackOff"
  - "kubelet logs show nil pointer"
difficulty: "hard"
language: "go"
ground_truth:
  root_cause_file: "pkg/kubelet/kubelet.go"
```

See `synthetic_test_data/` for complete working examples of each task type.

## Expected Corpus Directory Structure

The 10Figure corpus (not version-controlled, ~5GB) should have this layout:

```
/10figure/                    (or local path like /path/to/harbor-10figure-dataset)
├── src/                      # Source repositories
│   ├── kubernetes/           # Target codebase (multiple versions)
│   ├── firefox/
│   ├── llvm/
│   └── ...
├── tasks/                    # Task definitions (YAML format) -- this is --input
│   ├── cross_file_reasoning_01.yaml
│   ├── refactor_rename_01.yaml
│   ├── api_upgrade_01.yaml
│   ├── bug_localization_01.yaml
│   └── ...
└── scripts/                  # Utilities
    └── validate_patch.py     # Validator for task evaluation
```

## Generating Tasks

When the corpus data arrives, generate Harbor tasks with:

```bash
cd /path/to/CodeContextBench

python3 runners/gen_harbor_tasks.py \
  --input /path/to/10figure/tasks \
  --output benchmarks/10figure \
  --templates benchmarks/10figure/templates \
  --repo kubernetes \
  --corpus-root /10figure
```

### Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--input` | Directory containing 10Figure task YAML files | Required |
| `--output` | Output directory for generated Harbor tasks | Required |
| `--templates` | Directory containing Jinja2 templates (test.sh.j2) | Required |
| `--repo` | Repository name for task environment | `kubernetes` |
| `--corpus-root` | Corpus root path in container | `/10figure` |

### Validating with Synthetic Data

To verify the generator works without the full corpus:

```bash
python3 runners/gen_harbor_tasks.py \
  --input benchmarks/10figure/synthetic_test_data \
  --output /tmp/10figure_test \
  --templates benchmarks/10figure/templates \
  --repo kubernetes \
  --corpus-root /10figure
```

This produces 4 tasks (one per task type) and verifies the full pipeline.

## After Generation

After running the generator:

1. Verify each task directory has all 6 required files:
   `instruction.md`, `task.toml`, `task.yaml`, `repo_path`, `environment/Dockerfile`, `tests/test.sh`

2. MANIFEST.json is automatically updated with `task_count`, `task_ids`, and `status: "generated"`

3. Run tasks in Harbor:
   ```bash
   harbor run \
     --path benchmarks/10figure/<task_id> \
     --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
     --model anthropic/claude-opus-4-5-20251101
   ```

4. Or use the unified orchestrator:
   ```bash
   python3 scripts/run_comparison.py --benchmark 10figure --configs baseline mcp-full
   ```

## Task Types

The generator supports four 10Figure task types:

1. **cross_file_reasoning** - Trace function call chains across files
2. **refactor_rename** - Rename symbols throughout codebase
3. **api_upgrade** - Migrate deprecated API patterns
4. **bug_localization** - Find and fix bugs

Each task type generates appropriate instructions and validation scripts.

## Validation

The generated `tests/test.sh` script:

1. Checks for agent patch file at `/logs/agent/patch.diff`
2. Runs the validator with the patch and task definition
3. Extracts the overall score from validation result
4. Writes score to `/logs/verifier/reward.txt`

The validator expects:
- Patch file in unified diff format
- Task YAML with ground truth definition
- Access to corpus at `/10figure` with `scripts/validate_patch.py`
