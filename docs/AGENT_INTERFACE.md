# Agent Interface Specification

This document describes what an agent receives and must produce when running a CodeContextBench task.

## Input

### Workspace

The agent's working directory is one of:

| Path | Used by |
|------|---------|
| `/workspace/` | Most benchmarks (K8s Docs, LargeRepo, TAC, CodeReview, LinuxFLBench) |
| `/app/` | SWE-bench Pro |
| `/testbed/` | Some SWE-bench variants |

The workspace contains the repository code at a specific commit (the `pre_fix_rev` from `task.toml`). The agent has full read/write access.

### Instruction

The task instruction is delivered as the agent's prompt text. It is read from `instruction.md` in the task directory and includes:

- Problem description (bug report, feature request, or documentation task)
- Repository and difficulty metadata
- Specific files or areas to modify
- Constraints (e.g., "do not modify tests")

### Time Limit

Each task has a `time_limit_sec` field in `task.toml` (typically 300-1800 seconds). The agent process is killed if it exceeds this limit.

### Environment Variables

| Variable | Description |
|----------|-------------|
| `TASK_NAME` | Task identifier (e.g., `sgt-001`, `applyconfig-doc-001`) |
| `TIME_LIMIT_SEC` | Maximum execution time in seconds |

## Output

The agent modifies files in the workspace to solve the task. After the agent finishes (or times out), the verifier runs `tests/test.sh` to evaluate the result.

### Verification

The test script (`tests/test.sh`) is uploaded by Harbor to `/tests/` in the container at runtime. It is **not** present in the workspace directory. The script:

1. Runs inside the container after the agent completes
2. Writes a reward to `/logs/verifier/reward.txt` as a plain decimal float (0.0-1.0)
3. Always exits 0 (Harbor reads the reward value, not the exit code)

### Result Format

Harbor produces a `result.json` for each task containing:

```json
{
  "task_name": "sgt-001",
  "verifier_result": {
    "rewards": {
      "reward": 0.85
    }
  },
  "exception_info": null,
  "started_at": "2026-02-01T12:00:00Z",
  "finished_at": "2026-02-01T12:15:00Z",
  "agent_info": {
    "name": "claude-code",
    "model_info": {
      "name": "anthropic/claude-opus-4-5-20251101"
    }
  },
  "agent_result": {
    "n_input_tokens": 150000,
    "n_output_tokens": 25000
  }
}
```

See `schemas/result.schema.json` for the formal schema.

## Agent Configurations

CodeContextBench evaluates agents under three MCP (Model Context Protocol) configurations:

### Baseline (no MCP)

The agent uses only its built-in tools:

- **Bash** - Run commands (tests, builds, shell operations)
- **Read** - Read files
- **Edit** - Edit files

No external code search tools are available. The agent relies on local tools (Grep, Glob, shell commands) for code discovery.

### SG_base (Sourcegraph keyword + NLS search)

The agent receives Sourcegraph MCP tools for code discovery:

- `mcp__sourcegraph__keyword_search` - Exact string/regex search across indexed repos
- `mcp__sourcegraph__nls_search` - Natural language semantic search
- `mcp__sourcegraph__read_file` - Read files from the Sourcegraph index
- `mcp__sourcegraph__list_files` - Browse directory structure
- `mcp__sourcegraph__list_repos` - Discover available repositories
- `mcp__sourcegraph__go_to_definition` - Jump to symbol definitions
- `mcp__sourcegraph__find_references` - Find all callers/references
- `mcp__sourcegraph__commit_search` - Search commit history
- `mcp__sourcegraph__diff_search` - Search code diffs
- `mcp__sourcegraph__compare_revisions` - Compare revisions
- `mcp__sourcegraph__get_contributor_repos` - Find contributor repositories

Deep Search tools (`deepsearch`, `deepsearch_read`) are blocked in this config. All local tools (Grep, Glob, Bash) remain available.

### SG_full (Sourcegraph + Deep Search)

Same as SG_base plus:

- `mcp__sourcegraph__deepsearch` - Asynchronous semantic code analysis
- `mcp__sourcegraph__deepsearch_read` - Read Deep Search results

Deep Search is asynchronous: it returns a polling link, and the agent must call `deepsearch_read` multiple times (waiting 30-60 seconds between attempts) to retrieve results.

All local tools remain available.

## Constraints

### Network Access

Varies by task. Most tasks run in Docker containers with full network access for package installation during environment setup. Some tasks (e.g., TAC benchmarks) require network access to external services (RocketChat).

### Resource Limits

Defined in `task.toml` under the `[environment]` section:

```toml
[environment]
build_timeout_sec = 1200.0
```

### Container Environment

Tasks run in Docker containers built from `environment/Dockerfile` in each task directory. The container includes all dependencies needed to build and test the project.

## Minimal Agent Example

A minimal agent that reads the instruction and creates a placeholder file:

```bash
#!/bin/bash
# Read the instruction
cat /workspace/instruction.md

# Make a change (real agents would analyze and implement)
echo "// TODO: implement fix" > /workspace/fix.txt

# Run tests to check
bash /tests/test.sh 2>&1 || true
```

Real agents should:
1. Read and understand the instruction
2. Explore the codebase to locate relevant code
3. Implement the required changes
4. Run the test suite to verify correctness
