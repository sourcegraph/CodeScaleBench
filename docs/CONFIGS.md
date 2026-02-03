# Agent Configuration Matrix

This document describes the 3 agent configurations used in the CodeContextBench evaluation. Each configuration controls which tools the Claude Code agent can use for code navigation and discovery during benchmark tasks.

## Configuration Summary

| Paper Config Name | `BASELINE_MCP_TYPE` value | MCP Endpoint | Local Search Tools | Sourcegraph MCP Tools |
|---|---|---|---|---|
| Baseline | `none` | None | All (Bash, Read, Edit, Write, Grep, Glob, Task, etc.) | None |
| MCP-Base | `sourcegraph_base` | Sourcegraph `/.api/mcp/v1` | All (hybrid -- no restrictions) | 11 tools (all except sg_deepsearch, sg_deepsearch_read) |
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

### MCP-Base (`BASELINE_MCP_TYPE=sourcegraph_base`)

Connects to the Sourcegraph MCP endpoint with all local tools available (hybrid mode). Deep search tools are blocked via `--disallowedTools`.

**Local tools:** All standard Claude Code tools (same as Baseline, no restrictions)

**Sourcegraph MCP tools available (11):**

| Tool | Purpose |
|---|---|
| `mcp__sourcegraph__sg_keyword_search` | Find exact symbol/string matches |
| `mcp__sourcegraph__sg_nls_search` | Conceptual/semantic search |
| `mcp__sourcegraph__sg_read_file` | Read a file from the Sourcegraph index |
| `mcp__sourcegraph__sg_list_files` | Browse directory structure |
| `mcp__sourcegraph__sg_list_repos` | Discover available repositories |
| `mcp__sourcegraph__sg_go_to_definition` | Jump to symbol definition |
| `mcp__sourcegraph__sg_find_references` | Find all references to a symbol |
| `mcp__sourcegraph__sg_commit_search` | Search commit history |
| `mcp__sourcegraph__sg_diff_search` | Search diffs for changes |
| `mcp__sourcegraph__sg_compare_revisions` | Compare code between revisions |
| `mcp__sourcegraph__sg_get_contributor_repos` | Get contributor repository info |
| ~~`mcp__sourcegraph__sg_deepsearch`~~ | **BLOCKED** via `--disallowedTools` |
| ~~`mcp__sourcegraph__sg_deepsearch_read`~~ | **BLOCKED** via `--disallowedTools` |

**Note:** `sourcegraph_base` connects to the same Sourcegraph MCP endpoint as `sourcegraph_full`. The only difference is that `sg_deepsearch` and `sg_deepsearch_read` are excluded from the allowed tools via the `--disallowedTools` CLI flag.

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

## Implementation Details

The configuration is controlled by the `BASELINE_MCP_TYPE` environment variable in `claude_baseline_agent.py`:

- **Baseline (`none`):** No MCP config is loaded. The system prompt contains only the evaluation context. No `--tools` or `--disallowedTools` flags are applied.
- **MCP-Base (`sourcegraph_base`):** The Sourcegraph MCP config is loaded (same `.api/mcp/v1` endpoint). All local tools remain available. `--disallowedTools` blocks `mcp__sourcegraph__sg_deepsearch` and `mcp__sourcegraph__sg_deepsearch_read`. The system prompt instructs MCP-first usage.
- **MCP-Full (`sourcegraph_full`):** Same Sourcegraph MCP config. All local tools remain available. No tools are blocked. The system prompt instructs MCP-first usage with all 13 Sourcegraph MCP tools. (Note: the agent source code references "14 tools" in prompt strings, but only 13 distinct tool names are registered.)

All three configs use `--dangerously-skip-permissions` for autonomous operation and deliver evaluation context via `--append-system-prompt`.

Source: `~/evals/custom_agents/agents/claudecode/agents/claude_baseline_agent.py` lines 97-480
