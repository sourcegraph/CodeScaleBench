# OpenHands Harness

Run CodeScaleBench tasks using the OpenHands agent instead of Claude Code.

## Prerequisites

- Harbor CLI installed (`uv tool install harbor`)
- Docker running locally or `HARBOR_ENV=daytona` for cloud execution
- `.env.local` at project root with credentials (see Auth Setup below)

## Model Configuration

The `MODEL` env var accepts any LiteLLM-format string (`provider/model-name`):

| Model | MODEL value | Short name |
|-------|------------|------------|
| Opus 4.6 (default) | `anthropic/claude-opus-4-6` | `opus46` |
| Sonnet 4.6 | `anthropic/claude-sonnet-4-6` | `sonnet46` |
| Sonnet 4.5 | `anthropic/claude-sonnet-4-5-20241022` | `sonnet45` |
| Haiku 4.5 | `anthropic/claude-haiku-4-5-20251001` | `haiku45` |
| GPT-4o | `openai/gpt-4o` | `gpt4o` |
| Codex | `openai/gpt-5.3-codex` | `gpt53codex` |

The short name determines the run directory name (e.g. `runs/staging/openhands_sonnet46_20260306_120000/`).

## Auth Setup

### Anthropic Models (OAuth Subscription)

The project uses Claude Max subscription tokens, not API keys. The agent reads the OAuth access token from `~/.claude/.credentials.json` and injects it into `ANTHROPIC_API_KEY` so Harbor's resolver can find it.

Ensure tokens are fresh before launching:
```bash
source configs/_common.sh
load_credentials
ensure_fresh_token_all
```

If `ANTHROPIC_API_KEY` is explicitly set in `.env.local`, it takes precedence over OAuth.

### OpenAI Models

Set `OPENAI_API_KEY` in `.env.local`. For Codex models, you can also use `CODEX_API_KEY`.

## Example Commands

```bash
# Full 2-config run (baseline + MCP) with Sonnet 4.6
MODEL=anthropic/claude-sonnet-4-6 ./configs/openhands_2config.sh

# Baseline-only with Opus 4.6 (default model)
./configs/openhands_2config.sh --baseline-only

# Single task
./configs/openhands_2config.sh --benchmark csb_sdlc_fix --task my-task-001

# Override parallelism
./configs/openhands_2config.sh --parallel 4

# GPT-4o run
MODEL=openai/gpt-4o ./configs/openhands_2config.sh --baseline-only
```

## Run Directory Structure

```
runs/staging/openhands_sonnet46_20260306_120000/
  baseline-local-direct/
    task-name__abcd1234/
      result.json
    task-name.log
  mcp-remote-direct/
    task-name__abcd1234/
      result.json
    task-name.log
```

## Architecture

- OpenHands runs **inside the Docker container** (installed by Harbor's template), not on the host
- `agents/harnesses/openhands/agent.py` extends Harbor's built-in `OpenHands` agent + `BaselineHarnessMixin`
- `BaselineHarnessMixin` (`agents/harnesses/base.py`) handles instruction preparation, MCP configuration, and container env propagation
- The 2-config launcher (`configs/openhands_2config.sh`) runs baseline (no MCP) then MCP-Full (Sourcegraph)

## Known Limitations

- Codex models require the `openai/` prefix for LiteLLM; the agent adds this automatically
- OAuth tokens expire after ~8 hours; long runs should call `ensure_fresh_token_all` between batches
- OpenHands agent does not support `CLAUDE_CODE_OAUTH_TOKEN` — it uses `LLM_API_KEY` for all providers
