# Running CodeContextBench on Daytona

This guide covers running the CodeContextBench benchmark suite on [Daytona](https://daytona.io) cloud sandboxes. Daytona handles Docker image builds and sandbox lifecycle remotely, so you do not need Docker installed locally.

## Prerequisites

1. **Daytona account** at [app.daytona.io](https://app.daytona.io)
2. **Python 3.12+**
3. **Daytona SDK**:
   ```bash
   pip install daytona-sdk
   ```
4. **Anthropic API key** or **Claude Code OAuth credentials** (for the AI agent)
5. **Sourcegraph access token** (only for MCP configs that use Sourcegraph search)

## Credential Setup

The runner loads credentials from environment variables first, falling back to config files.

### Daytona API Key (required)

Get your key from [Daytona Dashboard > Settings > API Keys](https://app.daytona.io).

```bash
# Option A: environment variable
export DAYTONA_API_KEY="your-key-here"

# Option B: config file at ~/.config/daytona/env.sh
echo 'DAYTONA_API_KEY="your-key-here"' > ~/.config/daytona/env.sh
```

### Anthropic API Key (for `--auth api-key` mode, the default)

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Or place it in `~/.claude/credentials.json`:
```json
{"apiKey": "sk-ant-..."}
```

### Claude Code OAuth (for `--auth oauth` mode)

OAuth mode uses pre-authenticated Claude Code credentials stored in `~/.claude-homes/accountN/.claude/.credentials.json`. Each account directory represents one authenticated session. Use this when running against Anthropic's Max plan or when API key billing is not preferred.

Set up by running `claude` (the Claude Code CLI) in each account home:
```bash
CLAUDE_CONFIG_DIR=~/.claude-homes/account1/.claude claude
# Complete the OAuth login flow in browser
```

List configured accounts:
```bash
python3 scripts/daytona_runner.py --list-accounts
```

### Sourcegraph Token (for MCP configs only)

Required only for `mcp-remote-direct` and `mcp-remote-artifact` configs:
```bash
export SRC_ACCESS_TOKEN="sgp_..."
```

## Quick Start

```bash
# 1. Verify setup
python3 scripts/daytona_runner.py --list-suites

# 2. Dry-run a single task (no sandboxes created)
python3 scripts/daytona_runner.py --task cgen-deps-install-001 --dry-run

# 3. Run a single task
python3 scripts/daytona_runner.py --task cgen-deps-install-001

# 4. Run a full suite
python3 scripts/daytona_runner.py --suite ccb_build --parallel 4

# 5. Run all 283 tasks
python3 scripts/daytona_runner.py --all --parallel 8
```

## Configs

Each config determines which Dockerfile and instruction file are used, and whether MCP tools (Sourcegraph) are available to the agent.

| Config | Dockerfile | Instruction | MCP | Description |
|--------|-----------|-------------|-----|-------------|
| `baseline-local-direct` | `Dockerfile` | `instruction.md` | No | Agent uses only local repo context |
| `mcp-remote-direct` | `Dockerfile.sg_only` | `instruction_mcp.md` | Yes | Empty workspace, agent uses Sourcegraph MCP |
| `baseline-local-artifact` | `Dockerfile.artifact_only` | `instruction.md` | No | Full source + artifact-based verifier |
| `mcp-remote-artifact` | `Dockerfile.artifact_only` | `instruction_mcp.md` | Yes | Artifact verifier + Sourcegraph MCP |

Select with `--config`:
```bash
python3 scripts/daytona_runner.py --suite ccb_mcp_onboarding --config mcp-remote-direct
```

## Task Selection

The runner supports several ways to select which tasks to run:

```bash
# Single task
--task cgen-deps-install-001

# Multiple tasks
--tasks cgen-deps-install-001,flipt-dep-refactor-001

# Full suite (only Daytona-ready tasks)
--suite ccb_build

# All ready tasks across all suites
--all

# From a JSON file (array of task ID strings)
--tasks-file my_tasks.json
```

Browse available tasks:
```bash
# List all suites with readiness counts
python3 scripts/daytona_runner.py --list-suites

# List tasks in a suite
python3 scripts/daytona_runner.py --list-tasks --suite ccb_build

# List all tasks
python3 scripts/daytona_runner.py --list-tasks
```

## Execution Options

| Flag | Default | Description |
|------|---------|-------------|
| `--parallel N` | 1 | Max concurrent Daytona sandboxes |
| `--model NAME` | `claude-haiku-4-5-20251001` | Claude model for the agent |
| `--max-turns N` | 30 | Max agent conversation turns |
| `--timeout N` | per-task default | Override agent timeout (seconds) |
| `--retries N` | 1 | Retry count for errored tasks |
| `--auth api-key\|oauth` | `api-key` | Authentication mode |
| `--account N` | 1 | OAuth account number (with `--auth oauth`) |
| `--run-id ID` | auto-generated | Custom identifier for this run |
| `--output-dir PATH` | `runs/daytona/{run_id}` | Custom output directory |
| `--verbose` | off | Debug-level logging |
| `--dry-run` | off | Validate task selection without creating sandboxes |

## Output Structure

Each run produces results under `runs/daytona/{run_id}/`:

```
runs/daytona/{run_id}/
  manifest.json                           # Run-level summary
  {task_id}/{config}/
    result.json                           # Full task result
    agent_output.txt                      # Claude Code stdout (truncated to 10KB)
    verification_output.txt               # test.sh output (truncated to 5KB)
```

### manifest.json

The manifest includes aggregate statistics:

```json
{
  "run_id": "daytona_baseline-local-direct_20260228_143000",
  "config": "baseline-local-direct",
  "model": "claude-haiku-4-5-20251001",
  "platform": "daytona",
  "total_tasks": 24,
  "completed": 24,
  "passed": 18,
  "failed": 4,
  "errored": 2,
  "mean_reward": 0.75,
  "tasks": { ... }
}
```

### result.json (per-task)

```json
{
  "task_id": "cgen-deps-install-001",
  "config": "baseline-local-direct",
  "status": "success",
  "reward": 1.0,
  "agent_elapsed_sec": 45.2,
  "verify_elapsed_sec": 3.1,
  "total_elapsed_sec": 180.5,
  "cost_usd": 0.02,
  "num_turns": 5
}
```

## How It Works

For each task the runner:

1. **Creates a sandbox** from the task's Dockerfile using `Image.from_dockerfile()` (Daytona builds remotely)
2. **Sets up the environment**: installs Node.js 22, Claude Code CLI, creates a `claude` user
3. **Configures authentication**: writes API key or OAuth credentials into the sandbox
4. **Configures MCP** (if applicable): writes Sourcegraph MCP server config
5. **Uploads test files** from the task's `tests/` directory
6. **Runs the agent**: executes Claude Code with the task instruction, model, and turn limit
7. **Verifies results**: runs `bash /tests/test.sh` and reads the reward from `/logs/verifier/reward.txt`
8. **Collects output**: saves agent output, verification output, and result metadata
9. **Deletes the sandbox** (always, even on failure)

With `--parallel N`, steps 1-9 run concurrently across N sandboxes using a thread pool.

## Task Readiness

All 283 tasks across 19 suites are Daytona-ready. Base images are sourced from:

- **Standard public images** (197 tasks): `python:*`, `golang:*`, `gcc:*`, `ubuntu:*`, etc. from Docker Hub
- **Pre-built repo images** (70 tasks): `ghcr.io/sourcegraph/ccb-repo-*` on GitHub Container Registry
- **SWEAP images** (21 tasks): `jefzda/sweap-images:*` on Docker Hub
- **TAC images** (4 tasks): `ghcr.io/theagentcompany/*` on GitHub Container Registry
- **Linux kernel tasks** (5 tasks): Build from `gcc:13` with inline kernel source clone

## Environment Variable Reference

| Variable | Required | Description |
|----------|----------|-------------|
| `DAYTONA_API_KEY` | Yes | Daytona platform API key |
| `ANTHROPIC_API_KEY` | For api-key auth | Anthropic API key for Claude |
| `SRC_ACCESS_TOKEN` | For MCP configs | Sourcegraph access token |
| `DAYTONA_API_URL` | No | Override Daytona API endpoint (default: `https://app.daytona.io/api`) |
| `DAYTONA_TARGET` | No | Override Daytona target region (default: `us`) |
| `CLAUDE_OAUTH_CLIENT_ID` | No | Override OAuth client ID |
| `CLAUDE_OAUTH_TOKEN_URL` | No | Override OAuth token endpoint |

## Troubleshooting

**"Missing DAYTONA_API_KEY"**: Set the env var or create `~/.config/daytona/env.sh`.

**Sandbox creation timeout**: Some tasks have large Docker images (multi-GB repo clones). Increase timeout with `--timeout` or retry with `--retries 2`.

**"Missing Dockerfile" or "Missing instruction"**: The task may not have the Dockerfile variant required by your chosen config. Check with `--dry-run` first.

**OAuth token expired**: Re-run `claude` in the account home directory to refresh credentials, or switch to `--auth api-key`.

**MCP config errors**: Verify `SRC_ACCESS_TOKEN` is set and valid. Test with `curl -H "Authorization: token $SRC_ACCESS_TOKEN" https://sourcegraph.com/.api/graphql`.
