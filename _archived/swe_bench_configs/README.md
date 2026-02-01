# SWE-Bench MCP Ablation Study Configurations

This directory contains configurations for running ablation studies on SWE-bench tasks
with and without MCP (Model Context Protocol) servers using mini-swe-agent.

## Configurations

All configurations use **HTTP-based MCP endpoints** (not command-based).

### 1. Baseline (No MCP)
- **File**: `baseline.yaml`
- **Agent**: `mini_swe_agent_mcp:MiniSweAgentBaseline`
- **Tools**: Local tools only (bash, file I/O, etc.)
- **Use case**: Baseline performance measurement

### 2. Sourcegraph MCP (Full Code Intelligence)
- **File**: `sourcegraph_mcp.yaml`
- **Agent**: `mini_swe_agent_mcp:MiniSweAgentSourcegraphMCP`
- **MCP Endpoint**: `{SOURCEGRAPH_URL}/.api/mcp/v1` (HTTP)
- **Tools**: `sg_keyword_search`, `sg_nls_search`, `sg_deepsearch`, `sg_read_file`
- **Use case**: Full code intelligence with all Sourcegraph tools

### 3. Deep Search MCP (Focused Semantic Search)
- **File**: `deepsearch_mcp.yaml`
- **Agent**: `mini_swe_agent_mcp:MiniSweAgentDeepSearchMCP`
- **MCP Endpoint**: `{SOURCEGRAPH_URL}/.api/mcp/deepsearch` (HTTP)
- **Tools**: `deepsearch` (semantic code search only)
- **Use case**: Focused semantic search ablation

## Usage

### Prerequisites

Set environment variables for MCP-enabled agents:

```bash
export SOURCEGRAPH_URL="https://sourcegraph.com"
export SOURCEGRAPH_ACCESS_TOKEN="your-token-here"
export ANTHROPIC_API_KEY="your-anthropic-key"
```

### Command-Line (Quick Tests)

```bash
# Baseline (no MCP)
harbor trials start \
  --agent-import-path mini_swe_agent_mcp:MiniSweAgentBaseline \
  -m anthropic/claude-haiku-4-5-20251001 \
  -p benchmarks/swebench_pro/tasks/instance_xxx

# With Sourcegraph MCP (full code intelligence)
harbor trials start \
  --agent-import-path mini_swe_agent_mcp:MiniSweAgentSourcegraphMCP \
  -m anthropic/claude-haiku-4-5-20251001 \
  -p benchmarks/swebench_pro/tasks/instance_xxx

# With Deep Search MCP (focused semantic search)
harbor trials start \
  --agent-import-path mini_swe_agent_mcp:MiniSweAgentDeepSearchMCP \
  -m anthropic/claude-haiku-4-5-20251001 \
  -p benchmarks/swebench_pro/tasks/instance_xxx
```

### Using Config Files (Recommended)

```bash
# Source environment
source .env.local
export ANTHROPIC_API_KEY SOURCEGRAPH_ACCESS_TOKEN SOURCEGRAPH_URL

# Baseline
harbor trials start -c swe_bench_configs/baseline.yaml \
  -p benchmarks/swebench_pro/tasks/instance_xxx

# Sourcegraph MCP
harbor trials start -c swe_bench_configs/sourcegraph_mcp.yaml \
  -p benchmarks/swebench_pro/tasks/instance_xxx

# Deep Search MCP
harbor trials start -c swe_bench_configs/deepsearch_mcp.yaml \
  -p benchmarks/swebench_pro/tasks/instance_xxx
```

### Using Dashboard (Recommended for Ablation Studies)

The `swebench_ablation` profile is available in `configs/benchmark_profiles.yaml`:

```bash
# Run via dashboard/profile runner
python scripts/benchmark_profile_runner.py swebench_ablation
```

This runs all three variants (baseline, Sourcegraph MCP, Deep Search MCP) automatically.

### Running Full Benchmark Sweeps

For multiple tasks across all configurations:

```bash
# Source environment
source .env.local
export ANTHROPIC_API_KEY SOURCEGRAPH_ACCESS_TOKEN SOURCEGRAPH_URL

# Run all three configurations on a task set
for config in baseline sourcegraph_mcp deepsearch_mcp; do
  for task in benchmarks/swebench_pro/tasks/instance_*; do
    harbor trials start \
      -c swe_bench_configs/${config}.yaml \
      -p "$task" \
      --trials-dir jobs/swe_ablation_${config}
  done
done
```

## MCP Server Configuration

### HTTP-Based MCP (Used by These Configs)

The agent classes auto-configure HTTP MCP endpoints:

```python
# Sourcegraph MCP endpoint
{
  "mcpServers": {
    "sourcegraph": {
      "type": "http",
      "url": "{SOURCEGRAPH_URL}/.api/mcp/v1",
      "headers": {"Authorization": "token {SOURCEGRAPH_ACCESS_TOKEN}"}
    }
  }
}

# Deep Search MCP endpoint
{
  "mcpServers": {
    "deepsearch": {
      "type": "http",
      "url": "{SOURCEGRAPH_URL}/.api/mcp/deepsearch",
      "headers": {"Authorization": "token {SOURCEGRAPH_ACCESS_TOKEN}"}
    }
  }
}
```

### Command-Based MCP (Also Supported)

The base `MiniSweAgentMCP` class also supports command-based MCP:

```yaml
agent:
  import_path: "mini_swe_agent_mcp:MiniSweAgentMCP"
  kwargs:
    mcp_servers:
      custom_server:
        command: "npx"
        args: ["-y", "package-name"]
        env:
          API_KEY: "${API_KEY}"
```

## Notes

- The baseline configuration is identical to regular mini-swe-agent
- MCP servers run in the agent environment and provide additional context
- Results can be compared to measure the impact of different context sources
- All configurations use the same underlying mini-swe-agent implementation
