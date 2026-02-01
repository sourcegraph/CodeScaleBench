# SWE-Agent MCP Ablation Setup

**Date:** 2024-12-28
**Status:** ✅ Complete and Ready for Testing

## Summary

Fixed SWE-agent MCP configuration to use correct HTTP endpoints (matching Claude Code baseline) and added dashboard integration for easy ablation testing.

## Changes Made

### 1. Updated `mini_swe_agent_mcp.py` (+78 lines)

**Added HTTP MCP Support:**
- Updated `_create_mcp_config_file()` to support both HTTP and command-based MCP
- HTTP format: `{"type": "http", "url": "...", "headers": {...}}`
- Command format: `{"command": "...", "args": [...], "env": {...}}`

**Added Three Agent Variants:**
1. `MiniSweAgentBaseline` - No MCP (pure baseline)
2. `MiniSweAgentSourcegraphMCP` - Full Sourcegraph MCP
   - Endpoint: `{SOURCEGRAPH_URL}/.api/mcp/v1`
   - Tools: `sg_keyword_search`, `sg_nls_search`, `sg_deepsearch`, `sg_read_file`
3. `MiniSweAgentDeepSearchMCP` - Deep Search only
   - Endpoint: `{SOURCEGRAPH_URL}/.api/mcp/deepsearch`
   - Tools: `deepsearch` (semantic search)

### 2. Fixed SWE-Bench Config Files

**Before (Wrong - Command-based):**
```yaml
agent:
  kwargs:
    mcp_servers:
      sourcegraph:
        command: "npx"
        args: ["-y", "@sourcegraph/cody-context-filters-mcp"]
```

**After (Correct - HTTP-based):**
```yaml
agent:
  import_path: "mini_swe_agent_mcp:MiniSweAgentSourcegraphMCP"
  # MCP auto-configured from environment variables
```

### 3. Added Dashboard Integration

Added `swebench_ablation` profile to `configs/benchmark_profiles.yaml`:
- Runs all three agents on same tasks
- Easy ablation comparison
- Accessible via `python scripts/benchmark_profile_runner.py swebench_ablation`

## Correct MCP Endpoints

### Sourcegraph MCP (Full Intelligence)
```json
{
  "mcpServers": {
    "sourcegraph": {
      "type": "http",
      "url": "https://sourcegraph.com/.api/mcp/v1",
      "headers": {"Authorization": "token YOUR_TOKEN"}
    }
  }
}
```

**Tools Available:**
- `mcp__sourcegraph__sg_keyword_search` - Fast exact string matching
- `mcp__sourcegraph__sg_nls_search` - Natural language semantic search
- `mcp__sourcegraph__sg_deepsearch` - Deep semantic search with context
- `mcp__sourcegraph__sg_read_file` - Read files from indexed repos

### Deep Search MCP (Focused Semantic)
```json
{
  "mcpServers": {
    "deepsearch": {
      "type": "http",
      "url": "https://sourcegraph.com/.api/mcp/deepsearch",
      "headers": {"Authorization": "token YOUR_TOKEN"}
    }
  }
}
```

**Tools Available:**
- `mcp__deepsearch__deepsearch` - Deep semantic code search

## Usage

### Quick Test (Single Task)

```bash
# Source environment
source .env.local
export ANTHROPIC_API_KEY SOURCEGRAPH_ACCESS_TOKEN SOURCEGRAPH_URL

# Pick a test task
TASK="benchmarks/swebench_pro/tasks/instance_ansible-ansible-0ea40e09d1b35bcb69ff4d9cecf3d0defa4b36e8-v30a923fb5c164d6cd18280c02422f75e611e8fb2"

# Test baseline
harbor trials start \
  -c swe_bench_configs/baseline.yaml \
  -p "$TASK"

# Test Sourcegraph MCP
harbor trials start \
  -c swe_bench_configs/sourcegraph_mcp.yaml \
  -p "$TASK"

# Test Deep Search MCP
harbor trials start \
  -c swe_bench_configs/deepsearch_mcp.yaml \
  -p "$TASK"
```

### Dashboard Ablation Study

```bash
# Run all three agents on defined tasks
python scripts/benchmark_profile_runner.py swebench_ablation
```

## Ablation Matrix

| Agent | MCP Server | Endpoint | Tools |
|-------|------------|----------|-------|
| **Baseline** | None | - | Local tools only |
| **Sourcegraph MCP** | sourcegraph | `/.api/mcp/v1` | keyword, NLS, Deep Search, read_file |
| **Deep Search MCP** | deepsearch | `/.api/mcp/deepsearch` | Deep Search only |

## Why This Matters

1. **Correct Infrastructure**: Now uses same HTTP MCP as Claude Code baseline (proven to work)
2. **Clean Ablation**: Three distinct agent classes for clear comparison
3. **Dashboard Ready**: Integrated into `benchmark_profiles.yaml` for easy selection
4. **Generalized Agent**: Uses mini-swe-agent (more general than Claude Code)
5. **Model Agnostic**: Easy to swap models via config

## Testing Checklist

- [ ] Test baseline agent (no MCP)
- [ ] Test Sourcegraph MCP agent (verify HTTP endpoint works)
- [ ] Test Deep Search MCP agent (verify HTTP endpoint works)
- [ ] Verify MCP tools are available in agent environment
- [ ] Run dashboard profile (`swebench_ablation`)

## Files Modified

1. `mini_swe_agent_mcp.py` - Added HTTP MCP support + 3 agent variants
2. `swe_bench_configs/baseline.yaml` - Fixed to use MiniSweAgentBaseline
3. `swe_bench_configs/sourcegraph_mcp.yaml` - Fixed to use HTTP endpoint
4. `swe_bench_configs/deepsearch_mcp.yaml` - Fixed to use HTTP endpoint
5. `swe_bench_configs/README.md` - Updated documentation
6. `configs/benchmark_profiles.yaml` - Added swebench_ablation profile

## Related Documentation

- `swe_bench_configs/README.md` - Full usage guide
- `swe_bench_configs/TEST_RESULTS.md` - Previous test results (pre-HTTP fix)
- `agents/claude_baseline_agent.py` - Reference for HTTP MCP config
- `agents/mcp_variants.py` - Alternative agent implementations
