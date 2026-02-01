# SWE-bench Pro → Harbor Adapter

## Overview

This adapter converts [SWE-bench Pro](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro) benchmark instances into **Harbor-compatible tasks**, enabling evaluation of coding agents on long-horizon software engineering tasks.

SWE-bench Pro extends the original SWE-bench with:
- **Multi-language support**: Go, TypeScript, Python, and more
- **Longer horizon tasks**: More complex, real-world issues
- **Larger codebases**: Tasks from production-grade repositories

---

## Key Features

- ✅ Converts ScaleAI/SWE-bench_Pro dataset to Harbor format
- ✅ Multi-language support (Go, TypeScript, Python)
- ✅ Pre-built Docker images from DockerHub (jefzda/sweap-images)
- ✅ Optional Sourcegraph MCP configuration for code intelligence
- ✅ Compatible with SWE-agent as baseline agent

---

## Usage

### 1. Generate Harbor Tasks

```bash
cd benchmarks/swebench_pro

# Install dependencies
pip install datasets

# Generate all instances
python run_adapter.py --all --task-dir ./tasks

# Generate a subset (first 10)
python run_adapter.py --all --limit 10 --task-dir ./tasks

# Generate a single instance
python run_adapter.py --instance-id instance_flipt-io__flipt-xxx --task-dir ./tasks

# Enable MCP configuration
python run_adapter.py --all --enable-mcp --task-dir ./tasks
```

### 2. Run Evaluations with Harbor

```bash
# Using the default agent
harbor run --path benchmarks/swebench_pro/tasks/instance_xxx \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1

# Using MCP-enabled agent
harbor run --path benchmarks/swebench_pro/tasks/instance_xxx \
  --agent-import-path agents.mcp_variants:StrategicDeepSearchAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

---

## Using SWE-agent as Baseline

SWE-bench Pro includes SWE-agent as a submodule. To use it:

### Option 1: Use mini-swe-agent (Recommended)

The SWE-bench Pro repo includes a `mini-swe-agent` that can be used:

```bash
# Clone SWE-bench Pro with submodules
git clone --recursive https://github.com/scaleapi/SWE-bench_Pro-os.git

# Follow mini-swe-agent setup in the repo
cd mini-swe-agent
# ... setup instructions in their README
```

### Option 2: Integrate with Harbor

To use SWE-agent with Sourcegraph MCP:

1. **Create a SWE-agent Harbor adapter**:
   - The agent would wrap SWE-agent's execution
   - Add MCP tools to SWE-agent's available actions

2. **Configure MCP in the task environment**:
   - Set `SOURCEGRAPH_ACCESS_TOKEN` and `SOURCEGRAPH_URL` environment variables
   - The MCP config is automatically created in `/root/.config/claude/mcp.json`

---

## MCP Integration

When `--enable-mcp` is used (default), tasks include Sourcegraph MCP configuration:

```toml
[environment.setup_scripts]
mcp_config = """#!/bin/bash
# Setup Sourcegraph MCP if credentials provided
if [ -n "$SOURCEGRAPH_ACCESS_TOKEN" ] && [ -n "$SOURCEGRAPH_URL" ]; then
  mkdir -p /root/.config/claude
  cat > /root/.config/claude/mcp.json << 'EOF'
{
  "mcpServers": {
    "sourcegraph": {
      "command": "npx",
      "args": ["-y", "@sourcegraph/mcp-server"],
      "env": {
        "SRC_ACCESS_TOKEN": "$SOURCEGRAPH_ACCESS_TOKEN",
        "SOURCEGRAPH_URL": "$SOURCEGRAPH_URL"
      }
    }
  }
}
EOF
fi
"""
```

---

## Comparison: SWE-bench Verified vs SWE-bench Pro

| Feature | SWE-bench Verified | SWE-bench Pro |
|---------|-------------------|---------------|
| Languages | Python only | Python, Go, TypeScript |
| Task complexity | Medium | High (long-horizon) |
| Instances | 500 | ~100 |
| Docker images | swebench images | jefzda/sweap-images |
| Evaluation | swebench harness | Custom run_scripts |

---

## Task Structure

Each generated task follows Harbor format:

```
tasks/{instance_id}/
├── task.toml           # Harbor configuration
├── instruction.md      # Problem statement
├── environment/
│   └── Dockerfile      # Docker environment
├── tests/
│   ├── test.sh         # Test runner
│   └── config.json     # Full instance data
└── solution/
    └── solve.sh        # Oracle patch
```

---

## ⚠️ Important Notes

### Test Environment Services

SWE-bench Pro tasks require external services (Redis, MongoDB, etc.) that are pre-configured in the Docker images but may not be running. The test scripts (`tests/test.sh`) use a generic fallback test runner. For full test execution:

1. The Docker images include the necessary service dependencies
2. Services need to be started before running tests
3. Some projects (NodeBB, qutebrowser, etc.) require specific setup

**Current limitation**: The generic test runner may fail for tasks requiring background services. For production evaluation, consider using the [SWE-bench Pro evaluation harness](https://github.com/scaleapi/SWE-bench_Pro-os) which handles service orchestration.

---

## Troubleshooting

| Issue | Cause | Solution |
|-------|-------|----------|
| Dataset loading fails | Network/HuggingFace issues | Check internet connection |
| Docker build fails | Missing base image | Ensure jefzda/sweap-images is accessible |
| Tests timeout | Complex task | Increase `--timeout` (default: 3600s) |
| MCP not working | Missing credentials | Set `SOURCEGRAPH_ACCESS_TOKEN` and `SOURCEGRAPH_URL` |
| Tests fail with "ECONNREFUSED" | Services not running | The task needs Redis/MongoDB - see notes above |
| Docker image not found | Wrong image tag format | Regenerate tasks with latest adapter |

---

## Citation

```bibtex
@article{swebenchpro2024,
  title={SWE-bench Pro: Can AI Agents Solve Long-Horizon Software Engineering Tasks?},
  author={Scale AI},
  year={2024},
  url={https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro}
}
```

---

## See Also

- [SWE-bench Pro Repository](https://github.com/scaleapi/SWE-bench_Pro-os)
- [HuggingFace Dataset](https://huggingface.co/datasets/ScaleAI/SWE-bench_Pro)
- [Original SWE-bench](https://www.swebench.com/)
