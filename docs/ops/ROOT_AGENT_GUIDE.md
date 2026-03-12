# CodeScaleBench Agent Router

This file is the root entrypoint for AI agents working in this repository.
Keep it small. Use it to route to the right workflow and local guide, not as the
full operations manual.

## Non-Negotiables
- All work happens on `main` by default. If you use feature branches, keep them small, short-lived, and easy to fast-forward back into `main`.
- Every `harbor run` must be gated by interactive confirmation.
- Before commit/push, run `python3 scripts/repo_health.py` (or `--quick` for docs/config-only changes).
- Prefer a **remote execution environment** (e.g., Daytona) for large benchmark runs; use local Docker only when a task’s image or registry is incompatible with your cloud environment. See `docs/DAYTONA.md`.
- Set **parallelism based on your own account and model limits**. Avoid exceeding documented concurrency or rate caps for your environment or provider.
- Before launching any benchmark batch, check account readiness with `python3 scripts/check_infra.py` or `python3 scripts/account_health.py status`. Do not assume OAuth accounts are usable just because credentials exist.

## Beads Prerequisite and Usage
- Keep the Beads CLI (`bd`, alias `beads`) up to date before running agent workflows that rely on task graphs.
- Install or update with the official installer:
```bash
curl -fsSL https://raw.githubusercontent.com/steveyegge/beads/main/scripts/install.sh | bash
```
- Verify install/version with `bd --version` (or `beads --version`).
- Do not use `bd edit`; use non-interactive `bd create/update/close --json` or stdin-based `--description=-`.
- Typical flow: `bd ready --json`, `bd create ... --json`, `bd update <id> --claim`, `bd close <id> --reason "Done"`.

## Minimal Loading Policy
- Default load order: this file + one relevant skill + one relevant doc.
- Do not open broad catalogs (`docs/TASK_CATALOG.md`, large script lists, full reports) unless required.
- Prefer directory-local `AGENTS.md` / `CLAUDE.md` when working under `scripts/`, `configs/`, `tasks/`, or `docs/`.

## Fast Routing By Intent
- Launch or rerun benchmarks: `docs/DAYTONA.md` (Daytona, preferred) or `docs/START_HERE_BY_TASK.md`
- Monitor / status: `docs/START_HERE_BY_TASK.md` -> "Monitor Active Runs"
- Triage failures: `docs/START_HERE_BY_TASK.md` -> "Triage Failed Tasks"
- Compare configs / MCP impact / IR: `docs/START_HERE_BY_TASK.md` -> "Analyze Results"
- Repo policy / health gate: `docs/REPO_HEALTH.md`, `docs/ops/WORKFLOWS.md`
- Script discovery: `docs/ops/SCRIPT_INDEX.md`

## Local Guides
- `scripts/AGENTS.md` - script categories, safe usage, one-off handling
- `configs/AGENTS.md` - run launcher wrappers and confirmation gate policy
- `docs/AGENTS.md` - documentation IA and canonical vs archive guidance

## Compaction / Handoff
- Compact after exploration, after launching a batch, and after triage/report passes.
- Use `/handoff` skill for session handoffs (inline prompt, not a markdown file unless asked).
- Use `docs/ops/HANDOFF_TEMPLATE.md` as checklist.

## Landing the Plane
- Run `python3 scripts/repo_health.py` (or `--quick` for docs/config-only).
- `git pull --rebase && git push && git status` -- work is not done until push succeeds.
- Track follow-ups in issues or beads. Update status.

## Canonical Maps
- `docs/START_HERE_BY_TASK.md` - task-based read order
- `docs/ops/WORKFLOWS.md` - operational workflow summaries
- `docs/ops/TROUBLESHOOTING.md` - escalation and common failure routing
- `docs/ops/SCRIPT_INDEX.md` - generated script registry index
- `docs/reference/README.md` - stable specs and reference docs
- `docs/explanations/README.md` - rationale and context docs

## Common Gotchas (from session history)

### Documentation Generation
- **NEVER edit root `CLAUDE.md` or `AGENTS.md` directly.** Edit canonical sources under `docs/ops/` and regenerate. Direct edits cause `agent_guides_drift` failures in `repo_health.py`.
- After removing directories from the repo, also clean references from `scripts/sync_agent_guides.py` (`LOCAL_SOURCES`) and `scripts/docs_consistency_check.py` (`LOCAL_AGENT_TARGET_DIRS`).

### Daytona / Harbor
- Daytona builds from Dockerfiles at sandbox creation. Fixes on `main` take effect next run (exception: pre-built GHCR base images need separate rebuild).
- Harbor+Daytona (`harbor run --environment-type daytona`) is recommended. `scripts/daytona_runner.py` is for quick validation only.
- `BASELINE_MCP_TYPE` env var: `none`, `sourcegraph`, `deepsearch`.
- Use Daytona SDK (`daytona_sdk`) over CLI (CLI is interactive-only for SSH).
- GHCR packages default **private** for personal accounts; visibility change requires GitHub web UI.
- Snapshot names are **positional**: `daytona snapshot create ccb-name`, NOT `--name`.
- CLI/API version mismatch causes "Forbidden" errors. Keep CLI version in sync.
- Registry types enum: `internal`, `organization`, `transient`, `backup`. Use `organization` for GHCR/Docker Hub.

### Docker / Build
- `uv tool install` segfaults on ARM64/QEMU emulation. Use `pip install` instead, or switch to Daytona (native x86_64).
- Build-push-clean pattern when building Docker images with limited disk (~45GB): build one image, push, then clean locally before the next.
- Colons in agent names (e.g., `module:ClassName`) break Docker volume mounts. Sanitize paths: replace `:` with `__`.
- Add `|| git init` fallback to all `git clone` commands in Dockerfiles for network resilience. Applied to 269 Dockerfiles.
- Add `chown claude:claude /logs` and `adduser claude` to Dockerfiles for cross-harness (OH) permission compatibility.

### MCP Configuration (inside sandboxes)
- `.mcp.json` at `$CLAUDE_CONFIG_DIR` (typically `/logs/agent/sessions/`), not `/app/` or `/root/`.
- Claude Code needs `--mcp-config` flag; it does not auto-detect. Inject MCP usage instructions into the task prompt.
- `NODE_TLS_REJECT_UNAUTHORIZED=0` for Node.js SSL in containers.
- Sourcegraph: **stdio transport** (`npx @sourcegraph/cody --stdio`), NOT HTTP. HTTP 405 = wrong protocol.
- Sourcegraph skills show empty in headless mode. Embed prompt content in CLAUDE.md.
- Sourcegraph env vars: `SOURCEGRAPH_URL` and `SOURCEGRAPH_ACCESS_TOKEN` (NOT `_ENDPOINT` or `_TOKEN`).

### Harbor Result Format
- Timing fields (`started_at`, `finished_at`) at **top level** of `result.json`, not nested under `timing`.
- `trajectory.json` generated by Harbor's `_convert_events_to_trajectory()`, not by Claude Code CLI.
- SWE-bench `test.sh` redirects stdout to temp file; Harbor never sees `START_TEST_OUTPUT`/`END_TEST_OUTPUT` markers.
- Token usage in `trajectory.json`; transcript parsers don't see it. Contract: write `/logs/verifier/reward.txt`.

### Security / Credentials
- **Never pass credentials via Docker `-e` flags.** They leak into trajectory HTML when an agent runs `env`. Use file-based injection: write to `/logs/agent/.credentials.json` with `chmod 600`.
- `scripts/sanitize_secrets.py` redacts real API keys (Anthropic, OpenAI, Sourcegraph, GitHub, Daytona) at result generation time. Maintains allowlist for known fake benchmark fixtures.

### Harness-Agnostic Verifiers
- **no_changes_guard** must use `git diff origin/main HEAD` (not `git diff HEAD`) for agents that auto-commit (e.g., OpenHands). Otherwise the guard falsely penalizes normal OH behavior.
- Verifier path fallback chains: use `${TASK_WORKDIR:-/workspace}` for working directory and `${TASK_REPO_ROOT:-${VERIFY_REPO:-/workspace}}` for repo root. Enables same verifier across Harbor and OpenHands.
- Set `GOWORK=off` in test.sh when sg_only verifier restores full repo. The go.work file may require a newer Go version than the container provides.

### Validation / Scoring
- `validators.py` duplicated across `ccb_build` tasks. Changes must hit **all copies** (verify with `sha256sum`).
- Install scripts printing "INSTALL_SUCCESS" regardless of outcome are common. Verify binary exists.
- Agent completing in **<2s** = never installed/ran. Trial dir names truncated with hash; real name in `config.json` at `task.path`.
- LoCoBench task IDs have multi-word fields. Use 3-digit task number as positional anchor.
- **no_changes_guard**: write `reward.txt` inside Python block, not in bash after it.
- `timeout 600` on all test runners. `--forceExit` for Jest. Jest+TS needs `memory_mb = 8192`.
- **CSB dual-score**: file edits + `answer.json` scored independently. Fallback: `promoted_verifier.py` -> `oracle_checks.py` -> heuristic.
- Rate-limited results (score=0, <30s): `scripts/quarantine_invalid_tasks.py --execute`.
- Bare `$VAR` in `instruction.md` gets expanded. Use `<placeholder>` syntax.

### Git / Auth
- `gh auth refresh` needs explicit `-s <scope>`: `gh auth refresh -h github.com -s write:packages`.
- Env vars must be **exported** for Harbor subprocesses. Use `set -a` before sourcing `.env.local`.
- Account readiness: `runs/state/account_health.json`. Launchers source `configs/_common.sh`.
- GitHub push protection blocks synthetic keys. Squash with `git reset --soft origin/main`.
- Shallow clones fail on push. Some repos use `master`; detect with `git symbolic-ref refs/remotes/origin/HEAD`.
- GitHub secret scanning: unblock via `/security/secret-scanning/unblock-secret/` URL.

### Python / Subprocess
- `dict.get(key, default)` does NOT protect against `None` values. Use `data.get("key") or default_value`.
- `with open(log) as f: subprocess.Popen(stdout=f)` closes the handle. Use `open()` without context manager for long-running subprocesses.
- macOS Bash 3.2 lacks `declare -A`. Use pipe-delimited strings with `IFS='|' read -r`.

### LLM Judge
- Always include "Respond with valid JSON only (escape all quotes and special characters)" in judge prompts. Unescaped quotes in LLM-generated JSON break parsing.
- Judge should use task-type-aware evaluation: different rubrics for code implementation, architectural understanding, and bug fix tasks.
- Tool categorization order matters: check MCP prefix (`mcp__`) before substring checks (e.g., `deep_search`) to avoid miscategorization of `mcp__deep_search`.

### OpenHands
- `sandbox_plugins` is a list (not property). Strip ALL plugins (`= []`) -- `agent_skills` indexes `/workspace` at startup (120s timeout on large repos). TOML config has no effect in v1.4.0.
- `shlex.quote()` breaks on shell metacharacters (0% execution). Base64-encode instructions on host, decode inside container.
- Background daemons outlive the main process and hang Daytona poll. Wrap with `pkill` cleanup; guard with `shutil.which('pkill')` (missing on minimal images).
- Alpine lacks `apt-get` (OH installer requirement). Use `bookworm` variants.
- OH MCP client has ~30s timeout. Block `deepsearch`/`deepsearch_read` in auth proxy; redirect to `keyword_search`/`nls_search`.
- `chown -R /workspace` blocks port binding >120s on large repos. Edit installed `runtime_init.py` source -- monkey-patches don't propagate to action_execution_server subprocess.
- Set `PYTHONSAFEPATH=1` to prevent repo-local packages from shadowing installed deps.

### Pre-commit / Pytest / Ralph
- Secret-detection hooks false-positive on code that _detects_ secrets. Use `--no-verify` when flagged code is detection logic.
- Classes named `TestPlan`/`TestCase`/`TestResult` get auto-collected by pytest. Rename to `EvaluationPlan` etc.
- Ralph sessions write learnings to `progress.txt` on feature branches, not main. Compound back after merge.

## Maintenance
- Root and local `AGENTS.md` / `CLAUDE.md` files are generated from sources in `docs/ops/`.
- `docs/START_HERE_BY_TASK.md` is generated from `docs/ops/task_routes.json`.
- Regenerate after edits (single command):
```bash
python3 scripts/refresh_agent_navigation.py
```
