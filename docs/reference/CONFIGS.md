# Agent Configuration Matrix

## Agent Navigation
- `docs/reference/README.md` is the reference index for agent navigation.
- `docs/reference/CONFIGS.md` is the canonical location for this spec.
- `docs/CONFIGS.md` is a compatibility stub for legacy references.
- If you are launching or triaging runs, start with `docs/START_HERE_BY_TASK.md` before reading this full spec.

This document describes the agent configurations used in the CodeScaleBench
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
| `mcp-scip-remote-direct` | MCP + SCIP | Source deleted | Git changes | `sourcegraph_full` | `Dockerfile.sg_only` |
| `baseline-local-artifact` | No MCP | Full source | `review.json` | `none` | `Dockerfile.artifact_only` |
| `mcp-remote-artifact` | MCP | Source deleted | `review.json` | `artifact_full` | `Dockerfile.artifact_only` |
| `mcp-scip-remote-artifact` | MCP + SCIP | Source deleted | `review.json` | `artifact_full` | `Dockerfile.artifact_only` |

**Standard SDLC suites** (`csb_sdlc_feature`, `csb_sdlc_refactor`, `csb_sdlc_debug`, etc.) use
`baseline-local-direct` + `mcp-remote-direct`. The agent produces code changes
and the verifier checks git diffs / test results.

**Org suites** (`csb_org_*`) default to `baseline-local-artifact` +
`mcp-remote-artifact`. The agent produces `/workspace/answer.json` and the
verifier scores it against an oracle. Tasks with `"verification_modes":
["artifact", "direct"]` in `configs/use_case_registry.json` additionally
support `baseline-local-direct` + `mcp-remote-direct`. The verifier
auto-dispatches: if the `.artifact_only_mode` sentinel exists, it runs the
oracle verifier (`eval.sh`); otherwise it runs the direct verifier
(`direct_verifier.sh`).

**SCIP ablation** uses `mcp-scip-remote-direct` or `mcp-scip-remote-artifact`
(requires branch swap pre-flight; see SCIP Ablation section below).

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
   `/tmp/.sg_only_clone_manifest.json` telling the verifier which sg-evals
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
{"workdir":"/workspace","repos":[{"mirror":"sg-evals/django--674eda1c","target_dir":"."}]}
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
cost extraction depends on `scripts/csb_metrics/extractors.py` model pricing
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

## Running CodeScaleBench-Org Tasks

All tasks (SDLC and Org) are in the unified `configs/selected_benchmark_tasks.json`. Filter by suite with the `--benchmark` flag.

### Running Org Tasks

```bash
# Run all 220 Org tasks (both configs)
configs/run_selected_tasks.sh --benchmark csb_org

# Run only a specific Org suite
configs/run_selected_tasks.sh --benchmark csb_org_security

# Dry run to preview
configs/run_selected_tasks.sh --benchmark csb_org --dry-run
```

### CodeScaleBench-Org vs SDLC Suites

| Feature | SDLC suites | Org suites |
|---------|-------------|------------|
| **Config pair** | `baseline-local-direct` + `mcp-remote-direct` | `baseline-local-direct` + `mcp-remote-direct` |
| Selection file | `selected_benchmark_tasks.json` | `selected_benchmark_tasks.json` (unified) |
| Suite prefix | `csb_sdlc_<phase>` | `csb_org_<category>` |
| Verifier script | `tests/test.sh` | `tests/test.sh` (dispatches to eval.sh or direct_verifier.sh) |
| Oracle format | task-specific | `oracle_answer.json` + `oracle_checks.py` |
| Baseline Dockerfile | `Dockerfile` (full repo clone) | `Dockerfile` (full repo clone) |
| MCP Dockerfile | `Dockerfile.sg_only` (truncated source) | `Dockerfile.sg_only` (truncated source) |

See `docs/MCP_UNIQUE_TASKS.md` for full task authoring and evaluation details.

## SCIP Precise Indexing Ablation

The `mcp-scip-*` configs measure the impact of SCIP precise code intelligence
on MCP-enabled benchmark runs. SCIP provides compiler-accurate go-to-definition
and find-references (vs search-based heuristics on the control branch).

### How It Works

At the **agent/Harbor level**, `mcp-scip-remote-direct` is identical to
`mcp-remote-direct` — same Dockerfile, same MCP tools, same internal
`mcp_type=sourcegraph_full`. The difference is purely **server-side**: the
Sourcegraph instance has SCIP auto-indexing enabled for one branch and disabled
for another.

Two Sourcegraph configuration policies control indexing:

| Policy | Branch | `indexingEnabled` | ID |
|--------|--------|-------------------|-----|
| Benchmarks: Main (No SCIP) | `main` | `false` | `...MTA2Ng==` |
| Benchmarks: SCIP Enabled | `scip-enabled` | `true` | `...MTA2Nw==` |

Both policies target `github.com/sg-evals/*` with `GIT_TREE` type.

### Deep Search Limitation

Deep Search only indexes the **default branch HEAD**. It cannot be pointed at a
specific branch. To ensure Deep Search uses the SCIP-indexed code, the default
branch must be swapped before running benchmarks.

### Pre-Flight: Branch Swap

Before running SCIP-enabled benchmarks, swap the default branch on all
sg-evals repos:

```bash
# Before SCIP runs (mcp-scip-remote-direct):
./scripts/swap_default_branch.sh scip-enabled
# Wait for Sourcegraph to re-index (~30-60 min for full org)

# Before control runs (mcp-remote-direct) or to restore:
./scripts/swap_default_branch.sh main
```

The swap script:
- Patches all 1,592 sg-evals repos via GitHub API (`--parallel 10`)
- Skips repos already set to the target branch
- Skips empty repos without the target branch
- Logs results to `/tmp/scip_branch_swap/`
- Supports `--dry-run` for previewing

### Running the Ablation

```bash
# 1. Swap to SCIP-enabled
./scripts/swap_default_branch.sh scip-enabled
# 2. Wait for indexing to complete
# 3. Run SCIP config
FULL_CONFIG=mcp-scip-remote-direct configs/run_selected_tasks.sh

# 4. Swap back to control
./scripts/swap_default_branch.sh main
# 5. Wait for re-index
# 6. Run standard MCP config
FULL_CONFIG=mcp-remote-direct configs/run_selected_tasks.sh
```

### Comparing Results

Use `compare_configs.py` with both config names to see where SCIP helps/hurts:

```bash
python3 scripts/compare_configs.py --run <run_dir> \
  --configs mcp-remote-direct mcp-scip-remote-direct
```

### SCIP Indexing Coverage

Sourcegraph auto-indexing detects languages and runs the appropriate SCIP
indexer per repo:

| Language | Indexer | Example repos |
|----------|---------|---------------|
| Python | `scip-python` | ansible, django, astropy |
| Go | `scip-go` | cilium, autoscaler, argo-cd |
| TypeScript/JS | `scip-typescript` | vscode, cal.com, copilot-arena |
| Java | `scip-java` | camel |
| C++ | `scip-clang` | bustub, curl, log4cxx |
| C# | `scip-dotnet` | aspnetcore, CodeCoverageSummary |

Not all repos may successfully index (complex build setups). Check indexing
status in the Sourcegraph admin UI after swapping branches.

### Branch Creation Script

If new repos are added to sg-evals, create `scip-enabled` branches:

```bash
./scripts/create_scip_branches.sh [--dry-run] [--parallel N]
```

This creates a `scip-enabled` branch pointing to the same commit as `main` HEAD
for all repos in the org. Empty repos are skipped.
