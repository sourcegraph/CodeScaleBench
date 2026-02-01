# TAC MCP Value Benchmark

Evaluates Sourcegraph MCP (+ Deep Search) value on code-intensive tasks by porting a curated subset of [TheAgentCompany (TAC)](https://github.com/TheAgentCompany/TheAgentCompany) into Harbor.

## Overview

This benchmark suite wraps TheAgentCompany tasks to measure how much Sourcegraph MCP improves agent performance on real-world software engineering tasks.

**Task Count:** 8 curated tasks
**Focus:** Code search, navigation, and understanding
**Expected MCP Value:** High (tasks selected for code intelligence benefit)

## Quick Start

### Prerequisites

1. **Docker** - TAC tasks run in Docker containers
2. **Harbor** - CodeContextBench's evaluation framework
3. **TAC Docker images** - Pre-built images from TheAgentCompany

### Pull TAC Docker Images

```bash
# Pull all task images (requires ~20GB disk space)
cd benchmarks/tac_mcp_value/scripts
python import_tac_tasks.py --verify-images --pull

# Or pull specific task
docker pull ghcr.io/theagentcompany/sde-implement-hyperloglog-image:1.0.0
```

### Verify Tasks

```bash
# Verify all tasks have proper grading configuration
python scripts/verify_grader.py --all
```

### Run a Task

```bash
# Baseline (no MCP)
harbor run --path benchmarks/tac_mcp_value/tac-implement-hyperloglog \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1

# MCP + Strategic Deep Search
source .env.local
export SOURCEGRAPH_ACCESS_TOKEN SOURCEGRAPH_URL

harbor run --path benchmarks/tac_mcp_value/tac-implement-hyperloglog \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1

# MCP without Deep Search (control)
harbor run --path benchmarks/tac_mcp_value/tac-implement-hyperloglog \
  --agent-import-path agents.mcp_variants:MCPNonDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

## Directory Structure

```
benchmarks/tac_mcp_value/
├── README.md                      # This file
├── CONVENTIONS.md                 # Benchmark conventions and patterns
├── task_selection.md              # Task selection criteria and rationale
├── templates/                     # Template files for task generation
│   ├── task.toml.template
│   ├── instruction.md.template
│   ├── Dockerfile.template
│   └── test.sh.template
├── scripts/
│   ├── import_tac_tasks.py        # Import/manage TAC tasks
│   ├── import_tac_tasks.sh        # Shell wrapper
│   ├── verify_grader.py           # Verify task configuration
│   └── verify_grader.sh           # Shell wrapper
├── tac-implement-hyperloglog/     # Task: HyperLogLog implementation
│   ├── task.toml
│   ├── instruction.md
│   ├── environment/
│   │   └── Dockerfile
│   └── tests/
│       └── test.sh
├── tac-buffer-pool-manager/       # Task: Buffer pool manager
├── tac-dependency-change/         # Task: Dependency version update
├── tac-find-in-codebase-1/        # Task: Find PR (context window)
├── tac-find-in-codebase-2/        # Task: Find PR (file change)
├── tac-copilot-arena-endpoint/    # Task: Add API endpoint
├── tac-write-unit-test/           # Task: Write unit test
└── tac-troubleshoot-dev-setup/    # Task: Debug dev environment
```

## Curated Tasks

| Task ID                    | Description                     | Language | MCP Value     | Grading       |
| -------------------------- | ------------------------------- | -------- | ------------- | ------------- |
| tac-implement-hyperloglog  | Implement HyperLogLog in bustub | C++      | High          | Deterministic |
| tac-buffer-pool-manager    | Implement buffer pool manager   | C++      | High          | Deterministic |
| tac-dependency-change      | Update Python dependencies      | Python   | Medium        | Deterministic |
| tac-find-in-codebase-1     | Find PR for context window      | C++      | **Very High** | LLM-based     |
| tac-find-in-codebase-2     | Find PR for file change         | C++      | **Very High** | LLM-based     |
| tac-copilot-arena-endpoint | Add API endpoint                | Python   | Medium-High   | Deterministic |
| tac-write-unit-test        | Write unit test for function    | Python   | High          | Deterministic |
| tac-troubleshoot-dev-setup | Debug broken environment        | Python   | Medium        | Mixed         |

See [task_selection.md](task_selection.md) for detailed selection rationale.

## Environment Variables

### Required for MCP Agents

```bash
SOURCEGRAPH_ACCESS_TOKEN    # Sourcegraph API token
SOURCEGRAPH_URL             # Sourcegraph instance URL (e.g., https://sourcegraph.com)
```

### Optional for TAC Server Dependencies

Some tasks require TAC server infrastructure for full evaluation:

```bash
TAC_SERVER_HOSTNAME         # TAC server hostname (default: localhost)
LITELLM_API_KEY             # LiteLLM API key for LLM-based grading
LITELLM_BASE_URL            # LiteLLM base URL
LITELLM_MODEL               # LiteLLM model name
```

## Agent Conditions

The benchmark compares different agent conditions:

| Condition              | Agent Class                | Description                      |
| ---------------------- | -------------------------- | -------------------------------- |
| Baseline               | `BaselineClaudeCodeAgent`  | Claude Code without MCP          |
| Strategic Deep Search  | `StrategicDeepSearchAgent` | MCP with strategic Deep Search   |
| Aggressive Deep Search | `DeepSearchFocusedAgent`   | MCP with aggressive Deep Search  |
| No Deep Search         | `MCPNonDeepSearchAgent`    | MCP without Deep Search          |
| Full Toolkit           | `FullToolkitAgent`         | All MCP tools, neutral prompting |

### Switching Conditions

Conditions are switched by changing the agent, NOT the task:

```bash
# Same task, different agents
harbor run --path benchmarks/tac_mcp_value/tac-find-in-codebase-1 \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent ...

harbor run --path benchmarks/tac_mcp_value/tac-find-in-codebase-1 \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent ...
```

## TAC Integration

### How It Works

1. We use TAC's pre-built Docker images directly (`ghcr.io/theagentcompany/*`)
2. Each task has a thin Harbor wrapper (task.toml, instruction.md, test.sh)
3. TAC's built-in evaluator (`/utils/eval.py`) runs grading
4. We convert TAC's checkpoint scores to Harbor pass/fail

### TAC Docker Images

All images are from `ghcr.io/theagentcompany/<task-name>-image:1.0.0`.

TAC container structure:

```
/utils/           # TAC evaluation code
  ├── init.sh     # Task initialization
  ├── eval.py     # Grading entrypoint
  └── ...
/instruction/     # Task instructions
  └── task.md
/workspace/       # Agent workspace
```

### TAC Server Dependencies

Some tasks require TAC server infrastructure:

- **GitLab** - `http://the-agent-company.com:8929/` - All tasks
- **RocketChat** - `http://the-agent-company.com:3000/` - Some tasks
- **ownCloud** - `http://the-agent-company.com:8092/` - Rare

**For initial testing without TAC servers:**

- Tasks like `tac-implement-hyperloglog` and `tac-buffer-pool-manager` work with GitLab only
- The code search tasks (`tac-find-in-codebase-*`) require RocketChat for full evaluation

## Adding More Tasks

### 1. Find a Suitable TAC Task

Review [TAC's task list](https://github.com/TheAgentCompany/TheAgentCompany/blob/main/workspaces/README.md) and select tasks that:

- Are code-focused (sde-\* tasks primarily)
- Require cross-file reasoning
- Have deterministic grading (preferred)
- Don't require complex TAC server dependencies

### 2. Add Task Configuration

```bash
# Use the import script
python scripts/import_tac_tasks.py --task sde-new-task --pull

# Or create manually:
mkdir -p tac-new-task/{environment,tests}
# Copy and adapt from existing task
```

### 3. Create Task Files

**task.toml:**

```toml
version = "1.0"

[metadata]
name = "tac-new-task"
description = "Description here"
...
```

**instruction.md:** Task instructions for the agent

**environment/Dockerfile:** Wrap TAC image

```dockerfile
FROM ghcr.io/theagentcompany/sde-new-task-image:1.0.0
...
```

**tests/test.sh:** Grading wrapper

```bash
#!/bin/bash
# Run TAC evaluator and convert to pass/fail
...
```

### 4. Verify and Test

```bash
python scripts/verify_grader.py --task tac-new-task --verbose
```

### 5. Update Documentation

Add the new task to:

- [task_selection.md](task_selection.md) with rationale
- The table in this README

## Known Limitations

1. **TAC Server Requirements** - Some tasks need full TAC infrastructure
2. **LLM-based Grading** - `tac-find-in-codebase-*` tasks use LLM evaluation
3. **Image Size** - TAC images are large (~2-5GB each)
4. **Sourcegraph Indexing** - For optimal MCP value, repositories should be indexed in Sourcegraph

## Troubleshooting

### Docker Image Not Found

```bash
# Check if image exists
docker manifest inspect ghcr.io/theagentcompany/sde-implement-hyperloglog-image:1.0.0

# Pull image
docker pull ghcr.io/theagentcompany/sde-implement-hyperloglog-image:1.0.0
```

### Grader Fails

```bash
# Check grader configuration
python scripts/verify_grader.py --task tac-implement-hyperloglog --verbose

# Ensure test.sh is executable
chmod +x tac-implement-hyperloglog/tests/test.sh
```

### MCP Not Working

```bash
# Verify environment variables are set
echo $SOURCEGRAPH_ACCESS_TOKEN
echo $SOURCEGRAPH_URL

# Check MCP configuration in agent logs
```

## References

- [TheAgentCompany Paper](https://arxiv.org/abs/2412.14161)
- [TAC GitHub Repository](https://github.com/TheAgentCompany/TheAgentCompany)
- [CodeContextBench AGENTS.md](../../AGENTS.md)
- [Benchmark Conventions](CONVENTIONS.md)
