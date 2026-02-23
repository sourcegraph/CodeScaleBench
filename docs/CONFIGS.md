# Agent Configuration Matrix

This document describes the agent configurations used in the CodeContextBench
evaluation. Each configuration controls tools, source access, and verification
mode.

## Three-Dimensional Config Naming

Config names encode three independent dimensions:

```
{agent}-{source}-{verifier}
```

| Dimension | Values | Meaning |
|---|---|---|
| **agent** | `baseline` / `mcp` | Whether Sourcegraph MCP tools are available |
| **source** | `local` / `remote` | Whether source code is in `/workspace` (`local`) or deleted (`remote`) |
| **verifier** | `direct` / `artifact` | Whether verifier checks git changes (`direct`) or a `review.json` artifact (`artifact`) |

### Config Matrix

| Config Name | Agent | Source | Verifier | Internal `mcp_type` | Dockerfile |
|---|---|---|---|---|---|
| `baseline-local-direct` | No MCP | Full source | Git changes | `none` | Original |
| `mcp-remote-direct` | MCP | Source deleted | Git changes | `sourcegraph_full` | `Dockerfile.sg_only` |
| `baseline-local-artifact` | No MCP | Full source | `review.json` | `none` | `Dockerfile.artifact_only` |
| `mcp-remote-artifact` | MCP | Source deleted | `review.json` | `artifact_full` | `Dockerfile.artifact_only` |

**Standard SDLC suites** use `baseline-local-direct` + `mcp-remote-direct`.
**Artifact evaluation** uses `baseline-local-artifact` + `mcp-remote-artifact`
(set via `FULL_CONFIG=mcp-remote-artifact`).

### Legacy Names

Existing run directories may use older names. Analysis scripts accept both:

| Legacy Name | New Name |
|---|---|
| `baseline` | `baseline-local-direct` |
| `sourcegraph_full` | `mcp-remote-direct` |
| `artifact_full` | `mcp-remote-artifact` |

## Tool Lists

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
3. `Dockerfile.sg_only` creates an empty or truncated workspace (no usable
   source code) and writes a **clone manifest** to
   `/tmp/.sg_only_clone_manifest.json` telling the verifier which sg-benchmarks
   mirror(s) to clone at verification time.
4. A sentinel file `/tmp/.sg_only_mode` is written at build time.
5. The agent runs with empty/truncated source — local `Read`, `Grep`, `Glob`
   return empty/useless results, forcing reliance on MCP tools.
6. At verification time, `test.sh` detects `/tmp/.sg_only_mode` and sources
   `sgonly_verifier_wrapper.sh`, which clones the mirror repo(s) from the
   manifest, optionally re-runs defect injection, overlays agent-written files,
   and then hands off to the verifier.

**Clone manifest format** (`/tmp/.sg_only_clone_manifest.json`):

```json
{"workdir":"/workspace","repos":[{"mirror":"sg-benchmarks/django--674eda1c","target_dir":"."}]}
```

Multi-repo tasks list multiple entries; code-review tasks add `"inject_defects"`.

**Key paths inside the container:**

| Path | Contents |
|---|---|
| `/workspace/` (or `/app/`) | Empty or truncated source (agent sees this) |
| `/tmp/.sg_only_clone_manifest.json` | Clone manifest — verifier clones mirrors from here |
| `/tmp/.sg_only_mode` | Sentinel that activates verifier restoration |
| `/tests/` | Harbor-uploaded test harness (verifier scripts, ground truth) |
| `/logs/agent/` | Agent output (solution.md, patches) |

**Write-only tasks** (docgen, nlqa, onboarding, investigation, linuxflbench)
have verifiers that only check agent-written output files, not compiled code.
Their `Dockerfile.sg_only` provides an empty workspace with no clone manifest.

**Build-requiring tasks** (largerepo, codereview, swebenchpro, pytorch,
enterprise, etc.) need the full repo for compilation/test execution.
`sgonly_verifier_wrapper.sh` reads the clone manifest, clones mirrors with
`--depth 1`, and overlays agent changes before the verifier runs.

### Build-requiring subcategories

| Type | FROM base | Clone strategy |
|---|---|---|
| ccb-repo-* tasks | Underlying base (e.g. `golang:1.23-bookworm`) | Empty workspace + clone manifest |
| SWE-bench tasks | `jefzda/sweap-images:*` (preserves test venv) | Truncate source + clone manifest (restores `.py` files) |
| Code-review tasks | `ubuntu:22.04` | Empty workspace + manifest + `inject_defects` |
| Multi-repo tasks | `ubuntu:22.04` or language base | Multiple repos in manifest with `target_dir` |
| Inline-clone tasks | Various | Empty workspace + clone manifest |

### Adding sg_only support to a new task

Prefer using the generator: `python3 scripts/generate_sgonly_dockerfiles.py`.
To add manually:

1. Create `environment/Dockerfile.sg_only` — write sentinel, write clone
   manifest JSON, and leave workspace empty or truncated.
2. The generator automatically copies `tests/sgonly_verifier_wrapper.sh`.
3. Add the sg_only hook at the top of `tests/test.sh`:
   ```bash
   [ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh
   ```
4. Use `/tests/` paths (not `/workspace/tests/`) for ground truth and shared
   libraries — Harbor uploads `tests/` to `/tests/` at runtime.

## Implementation Details

The configuration is controlled by the `BASELINE_MCP_TYPE` environment variable in `claude_baseline_agent.py`:

- **Baseline (`none`):** No MCP config is loaded. Uses the task's regular `Dockerfile`. The system prompt contains only the evaluation context. No `--tools` or `--disallowedTools` flags are applied.
- **MCP-Full (`sourcegraph_full`):** Uses `Dockerfile.sg_only` (empty or truncated local source). The Sourcegraph MCP config is loaded (`.api/mcp/v1` endpoint). All local tools remain available but return empty results for source files. The verifier clones mirrors at verification time via clone manifest. The system prompt instructs MCP-first usage with all 13 Sourcegraph MCP tools.

Both configs use `--dangerously-skip-permissions` for autonomous operation and deliver evaluation context via `--append-system-prompt`.

Source: `agents/claude_baseline_agent.py` lines 97-480

## Multi-Harness Costing Caveat

OpenHands install and Gemini model setup (including openhands-tools dependency and API key model list): see **docs/OPENHANDS_SETUP.md**.

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

## Running MCP-Unique Tasks

MCP-unique tasks use a separate selection file and support category filtering.

### Selection File

```bash
# Run all 14 MCP-unique starter tasks (both configs)
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json

# Dry run to preview
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json \
  --dry-run
```

The `--selection-file` flag accepts any path to a selection JSON file. The
file format is compatible with `configs/selected_benchmark_tasks.json` but
uses `mcp_suite` instead of `benchmark` for suite identification.

### Category Filter

```bash
# Run only category A (cross-repo tracing)
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json \
  --use-case-category A

# Run only Deep Search relevant tasks (E and J categories)
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json \
  --use-case-category E
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json \
  --use-case-category J
```

The `--use-case-category` flag filters tasks by the `use_case_category` field in
the selection file (values: A through J, corresponding to the 10 ccb_mcp_* suites).
This flag is only meaningful when used with `--selection-file`.

### MCP-Unique vs Standard Suites

| Feature | Standard suites | MCP-unique suites |
|---------|----------------|-------------------|
| Selection file | `selected_benchmark_tasks.json` | `selected_mcp_unique_tasks.json` |
| Suite prefix | `ccb_<phase>` | `ccb_mcp_<category>` |
| Verifier script | `tests/test.sh` | `tests/eval.sh` |
| Oracle format | task-specific | `oracle_answer.json` + `oracle_checks.py` |
| Local repo | full workspace | 1 local_checkout repo only |
| MCP-Full behavior | truncated source | no source clone |

See `docs/MCP_UNIQUE_TASKS.md` for full task authoring and evaluation details.
