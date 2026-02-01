# TAC MCP Value Benchmark Conventions

This document outlines the conventions used in this benchmark suite based on analysis
of the existing CodeContextBench patterns and TheAgentCompany (TAC) structure.

---

## 1. Benchmark Directory Layout

CodeContextBench follows a consistent structure for benchmarks:

```
benchmarks/
├── <benchmark_name>/
│   ├── README.md              # Overview, setup, usage
│   ├── <task-id>/             # Individual task directories
│   │   ├── task.toml          # Harbor task configuration
│   │   ├── instruction.md     # Task instruction for agents
│   │   ├── environment/       # Environment setup
│   │   │   └── Dockerfile     # Task container definition
│   │   ├── tests/             # Verification scripts
│   │   │   └── test.sh        # Grading command
│   │   └── solution/          # (optional) Reference solution
│   ├── templates/             # (for adapters) Template files
│   ├── scripts/               # Helper scripts
│   └── *.py                   # (for adapters) Adapter code
```

---

## 2. Harbor Task Schema (task.toml)

Standard Harbor task configuration format:

```toml
version = "1.0"

[metadata]
name = "task-id"
description = "Task description"
license = "MIT"

[task]
id = "task-id"
repo = "repository-name"           # optional
category = "category-name"
language = "primary-language"
difficulty = "easy|medium|hard"
time_limit_sec = 1200              # 20 minutes default

[verification]
type = "test"
command = "bash /workspace/tests/test.sh"

[environment]
build_timeout_sec = 1800.0

[agent]
timeout_sec = 1000.0
```

---

## 3. Condition Switching (baseline vs mcp vs deepsearch)

Conditions are expressed via **agent selection**, NOT task modification:

### Baseline (No MCP)

```bash
harbor run --path benchmarks/<benchmark>/<task> \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

### MCP + Deep Search (Strategic)

```bash
harbor run --path benchmarks/<benchmark>/<task> \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

### MCP (No Deep Search)

```bash
harbor run --path benchmarks/<benchmark>/<task> \
  --agent-import-path agents.mcp_variants:MCPNonDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

### Full MCP Toolkit

```bash
harbor run --path benchmarks/<benchmark>/<task> \
  --agent-import-path agents.mcp_variants:FullToolkitAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

Required environment variables for MCP agents:

- `SOURCEGRAPH_ACCESS_TOKEN` - Sourcegraph API token
- `SOURCEGRAPH_URL` - Sourcegraph instance URL

---

## 4. Environment Images

### Approach A: Harbor Adapter (Complex Environments)

Used by: dibench, repoqa

- Adapter script generates task directories from external dataset
- Template-based generation of task.toml, instruction.md, Dockerfile
- Custom verifiers in Python

### Approach B: Direct Task Directories (Simple Environments)

Used by: big_code_mcp, github_mined

- Pre-built task directories with all files
- Dockerfile directly in task's environment/ folder
- Shell-based test.sh for verification

**For TAC**: We use Approach B (direct task directories) wrapping TAC's pre-built
Docker images. This minimizes translation work while leveraging TAC's existing
evaluators.

---

## 5. TAC Integration Approach

TheAgentCompany provides pre-built task images:

- `ghcr.io/theagentcompany/<task-name>-image:1.0.0`

TAC task structure inside container:

```
/utils/
├── init.sh            # Task initialization
├── eval.py            # Grading entrypoint
├── evaluator.py.enc   # Encrypted evaluator
├── common.py          # Shared utilities
├── scoring.py         # Score calculation
/instruction/
├── task.md            # Task instruction
/workspace/
├── ...                # Task workspace
```

### Our Integration Strategy:

1. **Use TAC Docker images directly** via `docker pull`
2. **Create thin Harbor wrappers** that:
   - Reference TAC images as base
   - Add Sourcegraph MCP configuration capability
   - Expose TAC's eval.py as verification command
3. **No forking or patching** of TAC internals
4. **Keep TAC as git submodule** for easy version tracking

---

## 6. TAC Dependencies

Some TAC tasks require external services (TAC servers):

- GitLab: `http://the-agent-company.com:8929/`
- RocketChat: `http://the-agent-company.com:3000/`
- Plane: Project management
- ownCloud: File storage

**For MCP evaluation**, we prioritize tasks that:

1. Are code-focused (sde-\* tasks primarily)
2. Have deterministic grading (test-based, not LLM-based)
3. Work standalone or with minimal TAC server dependencies
4. Require cross-file reasoning where Sourcegraph adds value

---

## 7. Grading Convention

Harbor expects verification via exit code:

- `exit 0` = pass
- `exit 1` = fail

TAC uses checkpoint-based scoring (partial credit).

### Our Wrapper:

```bash
#!/bin/bash
# Run TAC evaluator
python /utils/eval.py --trajectory_path /logs/trajectory.jsonl --output_path /logs/result.json

# Convert to pass/fail based on score threshold
SCORE=$(jq '.score' /logs/result.json)
if [ "$SCORE" -gt 0 ]; then
  exit 0  # At least partial success
else
  exit 1  # Complete failure
fi
```

For most tasks, we use TAC's evaluator directly and accept any score > 0 as "pass"
for the purposes of MCP comparison studies.

---

## 8. Artifact Collection

Harbor collects artifacts from:

- `/logs/` - Agent logs, trajectories
- `/workspace/` - Modified files

TAC evaluator outputs to specified `--output_path`.

We ensure compatibility by placing TAC evaluator output in `/logs/`.
