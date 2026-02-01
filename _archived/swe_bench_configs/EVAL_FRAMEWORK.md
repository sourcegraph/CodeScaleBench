# SWE-bench Pro Evaluation Framework Documentation

**Version**: 2.0  
**Last Updated**: 2026-01-23  
**Environment**: GCP VM (Ubuntu 22.04) → Mac (dashboard/analysis)

---

## Table of Contents

1. [Overview](#overview)
2. [Agent Configurations](#agent-configurations)
3. [Benchmark & Task Selection](#benchmark--task-selection)
4. [Repository Mirroring (sg-benchmarks)](#repository-mirroring-sg-benchmarks)
5. [V2 Experiment Framework](#v2-experiment-framework)
6. [Configuration Examples](#configuration-examples)
7. [Data Export for Local Processing](#data-export-for-local-processing)
8. [Manifest Schema](#manifest-schema)
9. [Resource Requirements](#resource-requirements)
10. [Troubleshooting](#troubleshooting)

---

## Overview

This framework evaluates coding agent performance on SWE-bench Pro tasks, comparing:
- **Baseline Claude Code**: Standard Claude Code agent with all default tools, NO MCP
- **Deep Search Hybrid**: Claude Code + Sourcegraph Deep Search MCP + all local tools

All evaluations run on a **GCP VM** (Ubuntu 22.04) using Docker containers per task. Results are exported to canonical JSON format and synced to Mac for dashboard analysis.

### Architecture

```
GCP VM (Execution)                              Mac (Analysis)
┌─────────────────────────────────────┐         ┌──────────────────────┐
│  bench-eval-v2 run -c config.yaml   │         │  Dashboard           │
│           │                         │         │  ├── manifest.json   │
│           ▼                         │         │  ├── results.json    │
│  ┌─────────────────────────────┐    │   scp   │  └── comparison.json │
│  │ Harbor Framework            │────┼────────▶│                      │
│  │  ├── Docker containers      │    │         │  Analysis Scripts    │
│  │  ├── Agent execution        │    │         │  ├── analyze.py      │
│  │  └── SWE-bench verifier     │    │         │  └── visualize.py    │
│  └─────────────────────────────┘    │         └──────────────────────┘
│           │                         │
│           ▼                         │
│  jobs/<job_name>/                   │
│  eval_runs_v2/<experiment>/         │
└─────────────────────────────────────┘
```

---

## Agent Configurations

### Available Agents

| Agent | MCP Mode | Local Search | Use Case |
|-------|----------|--------------|----------|
| **BaselineClaudeCodeAgent** | `none` | ✅ Full | Control group - pure Claude Code |
| **BaselineClaudeCodeAgent** | `deepsearch_hybrid` | ✅ Full | Treatment - MCP + local tools |
| **BaselineClaudeCodeAgent** | `deepsearch` | ❌ Blocked | MCP-only (forced MCP usage) |
| **BaselineClaudeCodeAgent** | `sourcegraph` | ❌ Blocked | Full Sourcegraph MCP v1 |
| **DeepSearchMCPAgent** | Deep Search only | ✅ Full | Alternative implementation |
| **SourcegraphMCPAgent** | Full MCP v1 | ✅ Full | Alternative implementation |

### Prompt Strategies

**Baseline (no MCP)**:
- No system prompt modifications
- Full access to Grep, Glob, Bash (find/grep/rg)
- Agent uses standard code discovery patterns

**Deep Search Hybrid**:
- Strategic hybrid approach: MCP for semantic search, local for tactical
- System prompt guides when to use each
- CLAUDE.md uploaded with detailed workflow instructions
- Repository context injected: `sg-benchmarks/<repo>--<commit>`

**Deep Search / Sourcegraph (forced)**:
- Tool restrictions via `--tools` and `--disallowedTools` CLI flags
- Blocks: Grep, Glob, Bash(grep/rg/ag/find/fd/tree)
- Forces all code discovery through MCP

### Key Implementation Details

```python
# agents/claude_baseline_agent.py

# MCP mode selection via environment variable
mcp_type = os.environ.get("BASELINE_MCP_TYPE", "none").lower()

# Critical CLI flags for autonomous operation
flags = [
    '--dangerously-skip-permissions',  # Required for headless operation
    '--mcp-config /logs/agent/sessions/.mcp.json',  # MCP config path
]

# Environment variables for background tasks
env = {
    'FORCE_AUTO_BACKGROUND_TASKS': '1',
    'ENABLE_BACKGROUND_TASKS': '1',
}
```

---

## Benchmark & Task Selection

### SWE-bench Pro 50-Task Canonical Set

The canonical task set (`config/swebenchpro_50_tasks.txt`) includes 50 tasks:

| Repository | Count | Language | Task Types |
|------------|-------|----------|------------|
| ansible/ansible | 6 | Python | Variable handling, templates |
| element-hq/element-web | 2 | TypeScript | React components |
| flipt-io/flipt | 12 | Go | Feature flags, API |
| future-architect/vuls | 5 | Go | Security scanning |
| gravitational/teleport | 9 | Go | SSH/Kubernetes access |
| internetarchive/openlibrary | 5 | Python | Web application |
| navidrome/navidrome | 1 | Go | Media server |
| NodeBB/NodeBB | 2 | JavaScript | Forum software |
| protonmail/webclients | 7 | TypeScript | Email client |
| tutao/tutanota | 1 | TypeScript | Email encryption |

### Task Selection Strategies

The v2 framework supports multiple task selection methods:

```yaml
# 1. Explicit task list
task_selector:
  type: explicit
  task_ids:
    - "instance_navidrome__navidrome-bf2bcb12..."

# 2. Random sample
task_selector:
  type: random_sample
  sample_size: 10
  seed: 42

# 3. Tag-based filtering
task_selector:
  type: tags
  include_tags: ["go", "backend"]
  exclude_tags: ["flaky"]

# 4. From file
task_selector:
  type: file
  tasks_file: config/swebenchpro_50_tasks.txt
```

### Timeout Settings

| Task Complexity | Timeout | Concurrency |
|-----------------|---------|-------------|
| Single task test | 600s (10min) | 1 |
| Standard task | 3600s (1hr) | 2-3 |
| Complex task | 7200s (2hr) | 2 |
| 50-task run | 7200s | 2 |

---

## Repository Mirroring (sg-benchmarks)

### Why Mirroring is Required

Each SWE-bench task operates on a specific historical commit. Without mirroring:
- Sourcegraph indexes the **latest** code (HEAD)
- Agent's local working copy is at the **historical** commit
- Deep Search results may not match local code

### Solution: sg-benchmarks Organization

All benchmark repositories are mirrored at **https://github.com/sg-benchmarks/** with:
- HEAD pinned to the exact commit required by each task
- Full Sourcegraph indexing on the mirrored repos
- Deep Search results match the agent's local working copy

### Mirrored Repositories

All repositories for the 50-task canonical set (plus additional repos) are mirrored:

| Original Repository | Mirror URL | Task Count |
|---------------------|------------|------------|
| ansible/ansible | https://github.com/sg-benchmarks/ansible | 6 |
| element-hq/element-web | https://github.com/sg-benchmarks/element-web | 2 |
| flipt-io/flipt | https://github.com/sg-benchmarks/flipt | 12 |
| future-architect/vuls | https://github.com/sg-benchmarks/vuls | 5 |
| gravitational/teleport | https://github.com/sg-benchmarks/teleport | 9 |
| internetarchive/openlibrary | https://github.com/sg-benchmarks/openlibrary | 5 |
| navidrome/navidrome | https://github.com/sg-benchmarks/navidrome | 1 |
| NodeBB/NodeBB | https://github.com/sg-benchmarks/NodeBB | 2 |
| protonmail/webclients | https://github.com/sg-benchmarks/webclients | 7 |
| tutao/tutanota | https://github.com/sg-benchmarks/tutanota | 1 |

**Full organization**: https://github.com/sg-benchmarks/

Each mirror has HEAD pinned to the specific commit required by the SWE-bench task, ensuring Deep Search results match the agent's local working copy.

### How It Works

1. **Task runner** extracts repo/commit from task ID:
   ```
   instance_navidrome__navidrome-bf2bcb12799b21069f137749e0c331f761d1f693
   → navidrome--bf2bcb12
   ```

2. **Environment variable** passed to agent:
   ```bash
   SWEBENCH_REPO_COMMIT=navidrome--bf2bcb12
   ```

3. **MCP config** includes org/repo/commit hints:
   ```json
   {
     "mcpServers": {
       "deepsearch": {
         "type": "http",
         "url": "https://sourcegraph.sourcegraph.com/.api/mcp/deepsearch",
         "org": "sg-benchmarks",
         "repo": "navidrome",
         "commit": "bf2bcb12"
       }
     }
   }
   ```

4. **System prompt** references the correct repository:
   ```
   You are working in: sg-benchmarks/navidrome--bf2bcb12
   When making Deep Search queries, reference: sg-benchmarks/navidrome
   ```

---

## V2 Experiment Framework

### Overview

The v2 framework (`bench-eval-v2`) provides:
- **Matrix expansion**: Run all combinations of benchmarks × models × MCP modes × seeds
- **Strict pairing**: Baseline and MCP runs share identical invariants
- **Deterministic IDs**: Hash-based run/pair/experiment IDs
- **Canonical outputs**: Self-describing JSON for dashboard ingestion

### CLI Commands

```bash
# Run experiment
./bench-eval-v2 run -c configs_v2/examples/minimal.yaml

# Dry run (preview matrix expansion)
./bench-eval-v2 dry-run -c configs_v2/examples/swebenchpro_50_tasks_comparison.yaml

# Validate config
./bench-eval-v2 validate -c configs_v2/smoke_test.yaml

# Check status
./bench-eval-v2 status -e exp_swebenchpro50ta_2026-01-23_d76183
```

### Directory Structure

```
claudecode/
├── agents/                          # Agent implementations
│   ├── claude_baseline_agent.py     # Main agent with MCP support
│   ├── mcp_agents.py                # Alternative MCP agents
│   └── install-claude-code.sh.j2    # Custom install template
├── config/                          # V1 configs
│   ├── baseline_opus_50.yaml        # Baseline 50-task config
│   ├── deepsearch_hybrid_opus_50.yaml
│   ├── swebenchpro_50_tasks.txt     # Canonical task list
│   └── yamls/                       # Additional configs
├── configs_v2/                      # V2 experiment configs
│   ├── smoke_test.yaml              # Validation config
│   └── examples/
│       ├── minimal.yaml             # Single task test
│       ├── single.yaml              # Single agent/task ablation
│       └── swebenchpro_50_tasks_comparison.yaml  # Full 50-task
├── v2/                              # V2 runner implementation
│   ├── cli.py                       # CLI entry point
│   ├── config/                      # Config loading/schema
│   ├── runner/                      # Execution engine
│   ├── matrix/                      # Matrix expansion
│   ├── exporter/                    # Canonical JSON export
│   └── mcp/                         # MCP configuration
├── jobs/                            # Harbor job outputs
├── eval_runs_v2/                    # V2 canonical outputs
├── run_comparison.sh                # V1 comparison script
└── bench-eval-v2                    # V2 CLI wrapper
```

---

## Configuration Examples

### 1. Minimal Single-Task Ablation

For quick testing and debugging:

```yaml
# configs_v2/examples/minimal.yaml
experiment_name: minimal_v2_test
description: "Minimal v2 test: single task, baseline vs MCP"

benchmarks:
  - name: swebenchpro
    version: "1.0"
    task_selector:
      type: explicit
      task_ids:
        - "instance_navidrome__navidrome-bf2bcb12799b21069f137749e0c331f761d1f693"

agent:
  import_path: agents.claude_baseline_agent:BaselineClaudeCodeAgent
  version: "1.0.0"

models:
  - anthropic/claude-opus-4-5

mcp_modes:
  - baseline
  - deepsearch_hybrid

seeds: [0]

execution:
  concurrency: 1
  timeout_seconds: 3600
  environment:
    type: docker
    delete_containers: false

pairing:
  enabled: true
  baseline_mode: baseline
```

### 2. Single Agent/Single Task Test

For focused debugging of a specific configuration:

```yaml
# config/yamls/single_task_test.yaml
run_name: single_task_test
description: "Single task sanity check"

agent:
  type: baseline
  import_path: agents.claude_baseline_agent:BaselineClaudeCodeAgent
  model: anthropic/claude-opus-4-5
  mcp_type: deepsearch_hybrid

dataset:
  name: swebenchpro
  version: "1.0"

tasks:
  - "instance_navidrome__navidrome-bf2bcb12799b21069f137749e0c331f761d1f693"

concurrency: 1
environment:
  delete_containers: false
```

### 3. Full 50-Task Comparison

Production configuration for full ablation study:

```yaml
# configs_v2/examples/swebenchpro_50_tasks_comparison.yaml
experiment_name: swebenchpro_50_tasks_baseline_vs_hybrid
description: "50-task ablation: Baseline (no MCP) vs Hybrid (Deep Search + local tools)"

benchmarks:
  - name: swebenchpro
    version: "1.0"
    task_selector:
      type: explicit
      task_ids:
        # All 50 tasks from config/swebenchpro_50_tasks.txt
        - "instance_ansible__ansible-4c5ce5a1a9e79a845aff4978cfeb72a0d4ecf7d6-v105..."
        # ... (50 total)

agent:
  import_path: agents.claude_baseline_agent:BaselineClaudeCodeAgent
  version: "1.0.0"

models:
  - anthropic/claude-opus-4-5

mcp_modes:
  - baseline
  - deepsearch_hybrid

seeds: [0]

execution:
  concurrency: 2              # 2 concurrent trials to prevent batch incompleteness
  timeout_seconds: 7200       # 2 hours per task
  environment:
    type: docker
    delete_containers: false  # Keep containers for debugging

output:
  root_dir: eval_runs_v2
  export_on_complete: true

pairing:
  enabled: true
  baseline_mode: baseline

tags:
  - 50-task-comparison
  - baseline-vs-hybrid
  - full-ablation
```

---

## Data Export for Local Processing

### Sync Script (Mac → GCP VM)

Use the targeted sync script to pull job outputs from the GCP VM:

```bash
# On Mac: ~/evals/sync_script_targeted.sh
#!/bin/bash

# Tar the files on remote, copy tar, then extract locally
echo "Creating tar of target files on remote..."
gcloud compute ssh stephanie_jarmak@instance-20251230-155636 \
  --zone us-central1-f \
  --project benchmarks-482815 \
  --command "cd /home/stephanie_jarmak/evals/custom_agents/agents/claudecode/jobs && tar czf /tmp/sync.tar.gz ."

echo "Copying tar file..."
gcloud compute scp \
  --zone us-central1-f \
  --project benchmarks-482815 \
  stephanie_jarmak@instance-20251230-155636:/tmp/sync.tar.gz \
  /tmp/sync.tar.gz

echo "Extracting to local directory..."
cd ~/evals/custom_agents/agents/claudecode/jobs
tar xzf /tmp/sync.tar.gz

echo "Cleaning up..."
rm /tmp/sync.tar.gz
gcloud compute ssh stephanie_jarmak@instance-20251230-155636 \
  --zone us-central1-f \
  --project benchmarks-482815 \
  --command "rm /tmp/sync.tar.gz"

echo "Done!"
```

**Usage**:
```bash
cd ~/evals
./sync_script_targeted.sh
```

This syncs the entire `jobs/` directory from the VM to `~/evals/custom_agents/agents/claudecode/jobs/` on your Mac.

### Directory Structure on Mac

After sync, files are available at:
```
~/evals/custom_agents/agents/claudecode/
├── jobs/                              # Synced from VM
│   ├── swebenchpro_run_baseline_opus_navidrome_seed0_*/
│   ├── swebenchpro_run_deepsearch_hybrid_opus_navidrome_seed0_*/
│   └── ...
└── eval_runs_v2/                      # V2 canonical outputs (sync separately if needed)
    └── exp_swebenchpro50ta_2026-01-23_d76183/
        └── manifest.json
```

### Syncing V2 Outputs (eval_runs_v2)

To also sync V2 canonical outputs, create an additional script or modify the existing one:

```bash
# Sync eval_runs_v2 directory
gcloud compute ssh stephanie_jarmak@instance-20251230-155636 \
  --zone us-central1-f \
  --project benchmarks-482815 \
  --command "cd /home/stephanie_jarmak/evals/custom_agents/agents/claudecode/eval_runs_v2 && tar czf /tmp/eval_runs_v2.tar.gz ."

gcloud compute scp \
  --zone us-central1-f \
  --project benchmarks-482815 \
  stephanie_jarmak@instance-20251230-155636:/tmp/eval_runs_v2.tar.gz \
  /tmp/eval_runs_v2.tar.gz

cd ~/evals/custom_agents/agents/claudecode/eval_runs_v2
tar xzf /tmp/eval_runs_v2.tar.gz
rm /tmp/eval_runs_v2.tar.gz
```

### Key Files for Dashboard Analysis

```
jobs/<job_name>/
├── result.json                        # Job-level aggregated results
├── config.json                        # Job configuration (secrets redacted)
├── job.log                            # Job execution log
└── <trial_name>/
    ├── result.json                    # Per-task result with reward, timing
    ├── trial.log                      # Trial execution log
    └── agent/
        ├── claude-code.txt            # Full agent trace (JSON lines with tokens, tools)
        ├── .mcp.json                  # MCP configuration used
        ├── CLAUDE.md                  # Uploaded guidance document
        └── sessions/                  # Claude Code session data

eval_runs_v2/<experiment_id>/
├── manifest.json                      # Experiment metadata & run summary
├── index.json                         # Quick lookup indices
├── runs/<run_id>/
│   ├── results.json                   # Canonical run results
│   └── harbor_ref.json                # Links to raw Harbor outputs
└── pairs/<pair_id>/
    └── comparison.json                # Side-by-side comparison
```

### Token Usage Extraction

Token usage is stored in `claude-code.txt` as JSON lines. The `result` entry contains:

```json
{
  "type": "result",
  "usage": {
    "input_tokens": 12345,
    "output_tokens": 6789,
    "cache_read_input_tokens": 1000,
    "cache_creation_input_tokens": 500
  },
  "total_cost_usd": 0.45,
  "duration_ms": 180000,
  "num_turns": 15
}
```

Use the metrics extractor to parse this:

```bash
python agents/metrics_extractor.py jobs/<job_name>/<trial_name>/
```

### Analysis Scripts

| Script | Location | Purpose |
|--------|----------|---------|
| `metrics_extractor.py` | `agents/` | Extract token, cost, tool usage from trials |
| `metrics_aggregator.py` | `agents/` | Aggregate metrics across trials |
| `report_generator.py` | `agents/` | Generate comparison reports |
| `analyze_mcp_experiment.py` | `archive/old_scripts/` | Analyze MCP adoption patterns |

### Key Output Files

**manifest.json** - Experiment-level metadata:
```json
{
  "schema_version": "1.0.0",
  "experiment_id": "exp_swebenchpro50ta_2026-01-23_d76183",
  "created_at": "2026-01-23T13:13:50.438849Z",
  "status": "running",
  "config": {
    "source_file": "configs_v2/examples/swebenchpro_50_tasks_comparison.yaml",
    "config_hash": "sha256:721427184d108a01090cbf9a7345c749...",
    "experiment_name": "swebenchpro_50_tasks_baseline_vs_hybrid",
    "benchmarks": ["swebenchpro"],
    "models": ["anthropic/claude-opus-4-5"],
    "mcp_modes": ["baseline", "deepsearch_hybrid"],
    "seeds": [0],
    "tags": ["50-task-comparison", "baseline-vs-hybrid", "v2", "full-ablation"]
  },
  "matrix_summary": {
    "total_runs": 2,
    "total_pairs": 1,
    "dimensions": {
      "benchmarks": 1,
      "models": 1,
      "mcp_modes": 2,
      "seeds": 1,
      "tasks": 50
    }
  },
  "runs": [
    {"run_id": "run_baseline_opus_...", "status": "pending", "mcp_mode": "baseline"},
    {"run_id": "run_deepsearch_hybrid_opus_...", "status": "pending", "mcp_mode": "deepsearch_hybrid"}
  ],
  "pairs": [
    {"pair_id": "pair_opus_...", "status": "pending", "mcp_mode": "deepsearch_hybrid"}
  ]
}
```

**Trial result.json** - Per-task execution details:
```json
{
  "id": "d64edec6-9627-4c01-9ae3-8a1a3b7bcfa6",
  "task_name": "instance_navidrome__navidrome-bf2bcb12...",
  "agent_info": {
    "name": "claude-code",
    "model_info": {"name": "claude-opus-4-5", "provider": "anthropic"}
  },
  "verifier_result": {
    "rewards": {"reward": 0.0}
  },
  "agent_execution": {
    "started_at": "2026-01-20T01:19:33.111085",
    "finished_at": "2026-01-20T01:31:07.379891"
  }
}
```

**Agent trace (claude-code.txt)** - Full agent conversation log with tool usage

---

## Manifest Schema

### V2 Manifest Schema (v1.0.0)

```typescript
interface ManifestV2 {
  schema_version: "1.0.0";
  experiment_id: string;  // e.g., "exp_swebenchpro50ta_2026-01-23_d76183"
  created_at: string;     // ISO 8601 timestamp
  finished_at: string | null;
  status: "created" | "pending" | "running" | "completed" | "failed";
  
  config: {
    source_file: string;  // Path to YAML config
    config_hash: string;  // SHA256 hash for reproducibility
    experiment_name: string;
    description: string | null;
    benchmarks: string[];
    models: string[];
    mcp_modes: string[];
    seeds: number[];
    tags: string[];
  };
  
  matrix_summary: {
    total_runs: number;
    total_pairs: number;
    dimensions: {
      benchmarks: number;
      models: number;
      mcp_modes: number;
      seeds: number;
      tasks: number;
    };
  };
  
  runs: Array<{
    run_id: string;
    status: "pending" | "running" | "completed" | "failed";
    mcp_mode: string;
  }>;
  
  pairs: Array<{
    pair_id: string;
    status: "pending" | "completed";
    mcp_mode: string;  // The non-baseline mode in the pair
  }>;
}
```

---

## Resource Requirements

### GCP VM Specifications

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| CPU | 8 vCPU | 16 vCPU |
| RAM | 32 GB | 64 GB |
| Disk | 200 GB SSD | 500 GB SSD |
| Docker | 20.10+ | Latest |

### Expected Duration

| Configuration | Tasks | Duration (estimated) |
|---------------|-------|---------------------|
| Single task test | 1 | 15-30 minutes |
| Minimal ablation (1 task × 2 modes) | 2 runs | 30-60 minutes |
| 10-task comparison | 20 runs | 4-8 hours |
| 50-task full ablation | 100 runs | 24-48 hours |

### Parallelization Approach

- **Concurrency 1**: Sequential execution, lowest resource usage
- **Concurrency 2**: Recommended for production runs, balances speed and stability
- **Concurrency 3-4**: Faster but may cause resource contention

```yaml
execution:
  concurrency: 2  # Recommended for 50-task runs
  timeout_seconds: 7200
```

---

## Troubleshooting

### Common Issues

**"Waiting for permission" hangs**
- The `--dangerously-skip-permissions` flag must be set
- Check that `claude_baseline_agent.py` includes this flag

**Node.js installation fails**
- The install script uses NodeSource apt repository
- If using nvm-based approach, it may fail in Docker
- Update `agents/install-claude-code.sh.j2` if needed

**MCP not being used (hybrid mode)**
1. Ensure `BASELINE_MCP_TYPE=deepsearch_hybrid` is set
2. Verify `SOURCEGRAPH_ACCESS_TOKEN` is valid
3. Check logs for "Deep Search MCP configured" message

**Task timeout**
- Increase `timeout_seconds` in config
- Reduce concurrency if resource-constrained

**Version mismatch in Deep Search results**
- Ensure sg-benchmarks repos are properly indexed
- Verify `SWEBENCH_REPO_COMMIT` environment variable is set
- Check MCP config includes org/repo/commit hints

**Token counts showing null in Harbor result.json**
- This is expected - Harbor's `agent_result.n_input_tokens` may be null
- Token usage IS tracked in `claude-code.txt` (JSON lines format)
- Use `python agents/metrics_extractor.py <trial_dir>` to extract token data
- Look for `"usage": {"input_tokens": ...}` entries in the trace

### Debugging Steps

1. **Check verifier output**:
   ```bash
   cat jobs/<job>/<trial>/verifier/test-stdout.txt
   ```

2. **Check agent trace**:
   ```bash
   cat jobs/<job>/<trial>/agent/claude-code.txt
   ```

3. **Check MCP config**:
   ```bash
   cat jobs/<job>/<trial>/agent/.mcp.json
   ```

4. **Check CLAUDE.md**:
   ```bash
   cat jobs/<job>/<trial>/agent/CLAUDE.md
   ```

---

## Related Links

- [Anthropic: Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- [Harbor Framework](https://harborframework.com/)
- [SWE-bench Pro](https://www.swebench.com/)
- [sg-benchmarks Organization](https://github.com/sg-benchmarks/)
