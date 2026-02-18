# Agent Configuration Matrix

This document describes the 2 agent configurations (Baseline and MCP-Full) used in the CodeContextBench evaluation. Each configuration controls which tools the Claude Code agent can use for code navigation and discovery during benchmark tasks.

## Configuration Summary

| Paper Config Name | `BASELINE_MCP_TYPE` value | MCP Endpoint | Local Search Tools | Sourcegraph MCP Tools |
|---|---|---|---|---|
| Baseline | `none` | None | All (Bash, Read, Edit, Write, Grep, Glob, Task, etc.) | None |
| MCP-Full | `sourcegraph_full` | Sourcegraph `/.api/mcp/v1` | All (hybrid -- no restrictions) | 13 tools (full Sourcegraph MCP) |

## Detailed Tool Lists

### Baseline (`BASELINE_MCP_TYPE=none`)

No MCP connection. The agent uses only Claude Code's built-in local tools:

- **Bash** -- Shell command execution
- **Read** -- Read file contents
- **Edit** -- Edit files with search/replace
- **Write** -- Write new files
- **Grep** -- Content search (ripgrep)
- **Glob** -- File pattern matching
- **Task** -- Launch sub-agents
- **TaskOutput** -- Read sub-agent output
- **WebFetch** -- Fetch web content
- **WebSearch** -- Web search
- **NotebookEdit** -- Edit Jupyter notebooks

No tool restrictions are applied. No `--disallowedTools` flag is set.

### MCP-Full (`BASELINE_MCP_TYPE=sourcegraph_full`)

Connects to the Sourcegraph MCP endpoint with all local tools available (hybrid mode). No tools are blocked.

**Local tools:** All standard Claude Code tools (same as Baseline, no restrictions)

**Sourcegraph MCP tools available (13):**

| Tool | Purpose |
|---|---|
| `mcp__sourcegraph__sg_keyword_search` | Find exact symbol/string matches |
| `mcp__sourcegraph__sg_nls_search` | Conceptual/semantic search |
| `mcp__sourcegraph__sg_deepsearch` | Deep semantic code analysis |
| `mcp__sourcegraph__sg_deepsearch_read` | Read deep search results |
| `mcp__sourcegraph__sg_read_file` | Read a file from the Sourcegraph index |
| `mcp__sourcegraph__sg_list_files` | Browse directory structure |
| `mcp__sourcegraph__sg_list_repos` | Discover available repositories |
| `mcp__sourcegraph__sg_go_to_definition` | Jump to symbol definition |
| `mcp__sourcegraph__sg_find_references` | Find all references to a symbol |
| `mcp__sourcegraph__sg_commit_search` | Search commit history |
| `mcp__sourcegraph__sg_diff_search` | Search diffs for changes |
| `mcp__sourcegraph__sg_compare_revisions` | Compare code between revisions |
| `mcp__sourcegraph__sg_get_contributor_repos` | Get contributor repository info |

## MCP-Full Docker Environment (sg_only mode)

MCP-Full runs use a modified Docker environment so that the agent cannot
explore the codebase locally and must rely on Sourcegraph MCP tools for code
discovery. This is the standard execution model for all `*_2config.sh` runs.

**How it works:**

1. Each task provides a `Dockerfile.sg_only` alongside its regular `Dockerfile`.
2. The config script copies `Dockerfile.sg_only` over `Dockerfile` before the
   MCP-Full run (baseline uses the original `Dockerfile`).
3. `Dockerfile.sg_only` clones the repo, backs up the full workspace to
   `/repo_full/`, then **truncates all source files** in `/workspace/`
   (zero-byte files preserve directory structure but contain no code).
4. A sentinel file `/tmp/.sg_only_mode` is written at build time.
5. The agent runs with truncated source — local `Read`, `Grep`, `Glob` return
   empty/useless results, forcing reliance on MCP tools.
6. At verification time, `test.sh` detects `/tmp/.sg_only_mode` and sources
   `sgonly_verifier_wrapper.sh`, which restores the full repo from `/repo_full/`
   and overlays any files the agent wrote, so the verifier runs against the
   correct codebase.

**Key paths inside the container:**

| Path | Contents |
|---|---|
| `/workspace/` | Truncated source (agent sees this) |
| `/repo_full/` | Full repo backup (verifier restores from here) |
| `/tests/` | Harbor-uploaded test harness (verifier scripts, ground truth) |
| `/tmp/.sg_only_mode` | Sentinel that activates verifier restoration |
| `/logs/agent/` | Agent output (solution.md, patches) |

**Write-only suites** (docgen, nlqa, onboarding, investigation, linuxflbench)
have verifiers that only check agent-written output files, not compiled code.
Their `Dockerfile.sg_only` typically omits the repo clone entirely.

**Build-requiring suites** (largerepo, codereview, swebenchpro, pytorch,
enterprise, etc.) need the full repo for compilation/test execution.
`sgonly_verifier_wrapper.sh` handles the restore-and-overlay cycle.

### Adding sg_only support to a new task

1. Create `environment/Dockerfile.sg_only` — clone repo, `cp -a /workspace /repo_full`,
   truncate source, write sentinel.
2. Create `tests/sgonly_verifier_wrapper.sh` (or use the standard template).
3. Add the sg_only hook at the top of `tests/test.sh`:
   ```bash
   [ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
   ```
4. Use `/tests/` paths (not `/workspace/tests/`) for ground truth and shared
   libraries — Harbor uploads `tests/` to `/tests/` at runtime.

## Implementation Details

The configuration is controlled by the `BASELINE_MCP_TYPE` environment variable in `claude_baseline_agent.py`:

- **Baseline (`none`):** No MCP config is loaded. Uses the task's regular `Dockerfile`. The system prompt contains only the evaluation context. No `--tools` or `--disallowedTools` flags are applied.
- **MCP-Full (`sourcegraph_full`):** Uses `Dockerfile.sg_only` (truncated local source). The Sourcegraph MCP config is loaded (`.api/mcp/v1` endpoint). All local tools remain available but return empty results for source files. The system prompt instructs MCP-first usage with all 13 Sourcegraph MCP tools.

Both configs use `--dangerously-skip-permissions` for autonomous operation and deliver evaluation context via `--append-system-prompt`.

Source: `~/evals/custom_agents/agents/claudecode/agents/claude_baseline_agent.py` lines 97-480

## Multi-Harness Costing Caveat

For non-Anthropic harnesses (Codex, Cursor, Gemini, Copilot, OpenHands), token
cost extraction depends on `scripts/ccb_metrics/extractors.py` model pricing
keys. Official Codex runs should use `gpt-5.3-codex` so pricing is explicit.
If a model identifier is unknown to `MODEL_PRICING`, extraction falls back to
`claude-opus-4-5-20250514` rates and emits a warning.

## Codex Harness Auth and Model Policy

Codex authentication is separate from Claude OAuth refresh automation in
`configs/_common.sh`. Codex operators must configure Codex credentials directly
using either ChatGPT login or an API key; Claude token refresh helpers are not
reused for Codex harness execution.

Official Codex benchmark runs require model `gpt-5.3-codex` and should
fail-fast if that model is unavailable in the configured Codex environment.

For this rollout, Codex MCP policy is sourcegraph_full-only for MCP-enabled
runs, with baseline comparisons using `none`. No other MCP modes are allowed.
