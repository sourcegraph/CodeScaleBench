# CodeScaleBench Agent Router

This file is the root entrypoint for AI agents working in this repository.
Keep it small. Use it to route to the right workflow and local guide, not as the
full operations manual.

## Non-Negotiables
- All work on `main`. Feature branches: small, short-lived, fast-forward merge.
- Every `harbor run` gated by interactive confirmation.
- Before commit/push: `python3 scripts/repo_health.py` (or `--quick` for docs/config-only).
- Prefer **Daytona** for large runs; local Docker only for incompatible tasks. See `docs/DAYTONA.md`.
- Set parallelism to your account/model limits. Don’t exceed documented concurrency caps.
- Pre-launch: `python3 scripts/check_infra.py` or `account_health.py status`. Don’t assume OAuth accounts work.

## Beads Prerequisite and Usage
- Install: `curl -fsSL https://raw.githubusercontent.com/steveyegge/beads/main/scripts/install.sh | bash`
- Verify: `bd --version`. No `bd edit`; use `bd create/update/close --json` or `--description=-`.
- Flow: `bd ready --json`, `bd create ... --json`, `bd update <id> --claim`, `bd close <id> --reason "Done"`.

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
- **NEVER edit root `CLAUDE.md`/`AGENTS.md` directly.** Edit sources in `docs/ops/` and regenerate. Direct edits cause `agent_guides_drift` failures.
- After removing directories from the repo, also clean references from `scripts/sync_agent_guides.py` (`LOCAL_SOURCES`) and `scripts/docs_consistency_check.py` (`LOCAL_AGENT_TARGET_DIRS`).

### Daytona / Harbor
- Daytona builds from Dockerfiles at creation; fixes on `main` take effect next run (GHCR images need separate rebuild). Harbor+Daytona preferred; `daytona_runner.py` for quick validation only.
- `BASELINE_MCP_TYPE` env var: `none`, `sourcegraph`, `deepsearch`.
- Use Daytona SDK (`daytona_sdk`) over CLI (CLI is interactive-only for SSH).
- GHCR packages default **private** for personal accounts; visibility change requires GitHub web UI.
- Snapshots are **positional** (`daytona snapshot create ccb-name`). CLI/API version mismatch → "Forbidden".
- Registry types enum: `internal`, `organization`, `transient`, `backup`. Use `organization` for GHCR/Docker Hub.

### Docker / Build
- `uv tool install` segfaults on ARM64/QEMU. Use `pip install` or Daytona.
- Build-push-clean for limited disk. Colons in agent names break mounts (use `__`).
- Dockerfile: `git clone || git init` fallback, `adduser claude` + `chown claude:claude /logs` for OH.
- `jefzda/` → `ghcr.io/sg-evals/` migration incomplete (33 Dockerfiles).

### MCP Configuration (inside sandboxes)
- `.mcp.json` at `$CLAUDE_CONFIG_DIR` (`/logs/agent/sessions/`), not `/app/`. Needs `--mcp-config` flag.
- `NODE_TLS_REJECT_UNAUTHORIZED=0` for Node.js SSL in containers.
- Sourcegraph: **stdio** (`npx @sourcegraph/cody --stdio`), NOT HTTP. Skills empty in headless — embed in CLAUDE.md.
- Sourcegraph env vars: `SOURCEGRAPH_URL`, `SOURCEGRAPH_ACCESS_TOKEN` (NOT `_ENDPOINT`/`_TOKEN`).

### Harbor Result Format
- Timing fields at **top level** of `result.json` (not under `timing`). `trajectory.json` from Harbor's `_convert_events_to_trajectory()`, not CLI.
- SWE-bench `test.sh` redirects stdout to temp file; Harbor never sees `START_TEST_OUTPUT`/`END_TEST_OUTPUT` markers.
- Token usage in `trajectory.json`; transcript parsers don't see it. Contract: write `/logs/verifier/reward.txt`.

### Security / Credentials
- **Never pass credentials via Docker `-e` flags** (leak into trajectory HTML). Use file-based injection: `/logs/agent/.credentials.json` with `chmod 600`.
- `sanitize_secrets.py` IS integrated into `export_official_results.py` (line 32), but allowlist bypass (`_FAKE_INDICATORS` substring matching too broad) undermines it. Use exact-match `FAKE_KEY_ALLOWLIST`.

### Harness-Agnostic Verifiers
- **no_changes_guard**: use `git diff origin/main HEAD` (not `HEAD`) for auto-committing agents.
- Verifier fallbacks: `${TASK_WORKDIR:-/workspace}`, `${TASK_REPO_ROOT:-${VERIFY_REPO:-/workspace}}`.
- `GOWORK=off` in test.sh when sg_only verifier restores full repo.
- **122 active tasks** hardcode `ANSWER_PATH="/workspace/answer.json"`. Check `ANSWER_JSON` in verifier lib. Zero scores on non-Harbor.
- **Verifier lib duplication**: 401 copies of `answer_json_verifier_lib.sh` (13 suites; task copies diverged with extra funcs). 275 copies of `dual_score_lib.sh` (csb/ only). `benchmarks/_shared/` missing; every fix requires touching 401+ files.

### Scripts / Code Quality
- **abc_audit.py**: 4 functions defined twice (`check_oa_*`, `check_ob_*`, `check_og_*`, `check_t10_*`); Python silently uses last definition.
- **`rerun_failed.py`**: `shell=True` + dynamic commands (injection risk); `sourcegraph_full → deepsearch` mapping wrong (invalid MCP type); contains deprecated model ID.
- **ir_metrics.py `tt_all_r` bug**: Line 749 set comparison may report time-to-first-relevant instead of time-to-all-relevant.
- **`--skip-completed`**: requires both `result.json` + `task_metrics.json`. Fix: check only `result.json`.
- **Task registry header stale**: claims 436, actual 274. `sync_task_metadata.py --fix` doesn't update it.
- **`verification_modes`/`use_case_category` missing from all 274 tasks**: breaks auto-detection + `--use-case-category` filter (silently filters all).

### Validation / Scoring
- `validators.py` duplicated across `ccb_build` tasks. Changes must hit **all copies** (`sha256sum`).
- Agent <2s = never ran. `no_changes_guard`: write `reward.txt` in Python, not bash. `timeout 600` on runners; `--forceExit` for Jest; Jest+TS: `memory_mb = 8192`.
- **CSB dual-score**: file edits + `answer.json` independent. Fallback: `promoted_verifier.py` → `oracle_checks.py` → heuristic.
- Rate-limited (score=0, <30s): `quarantine_invalid_tasks.py --execute`. Bare `$VAR` in `instruction.md` → use `<placeholder>`.
- Pass rate logic duplicated in `generate_eval_report.py` and `csb_metrics/models.py`.
- `cost_report.py`: `defaultdict(int)` + `.get("baseline", 1)` returns `0`. Use `or 1`.
- **TARGET_SUITE**: 55 stale, 220 missing. `dual_score_lib.sh` `scorer_artifact` always `"auto"`.
- **Falsy bugs**: `max_score=0` as false; `None` MCP metrics misclassified. `promote_run.py` crashes on non-dict env. `generate_eval_report.py:147,1005` `mcp_mode or config_name` falls through on empty string (both sites).
- `models.py` `from_dict()` mutates caller's dict via `.pop()`.

### Agent / Runner Robustness
- **Agent `/tmp` race**: `claude_baseline_agent.py:1134` uses fixed `/tmp/claude_system_prompt.txt`, `/tmp/claude_run.sh`. Concurrent tasks cross-contaminate. Use `mktemp`.
- **Token refresh**: `claude_baseline_agent.py:1523` only catches `HTTPError`; add `URLError`/`socket.timeout`.
- **LOCOBENCH path**: `claude_baseline_agent.py:31` `LOCOBENCH_CLAUDE_MD_TEMPLATE` hardcodes `/home/stephanie_jarmak/CodeScaleBench`; crash on other machines.
- **Runner pipefail**: `run_selected_tasks.sh:681` `harbor_run_guarded | tee || echo` -- `||` applies to `tee` (always 0). Add `set -o pipefail`.
- **Runner cleanup**: No `trap` for temp dirs. `mktemp` failure (line 648) silently copies to CWD.
- **`grep -P` macOS**: `run_selected_tasks.sh:726` + 12 task test.sh files silently fail on BSD grep. Use `sed -n` or POSIX alternatives.
- **`_common.sh` sparse array**: `unset` + `pids=("${pids[@]}")` doesn't compact sparse arrays in Bash; gaps persist (lines 1344-1352).

### Schema / Suite Naming
- 3 schemas use deprecated `ccb_mcp_*` enums; 8 have zero consumers. Examples embed legacy names (`ccb_crossrepo`); should be `csb_org_*`/`csb_sdlc_*`.
- **16 copies of `DIR_PREFIX_TO_SUITE`** across 30+ scripts with divergent definitions. Centralize in `csb_metrics/suite_registry.py`.

### Skills / Automation
- **54 stale paths**: 25 skill files hardcode `~/CodeScaleBench` (actual `~/CodeContextBench`). Use `$(git rev-parse --show-toplevel)`.
- **21 stale `sourcegraph_full` refs**: 14 skill files + 5 schemas. Invalid `BASELINE_MCP_TYPE` value (accepts `none`/`sourcegraph`/`deepsearch`).
- **3 deprecated model IDs**: `claude-opus-4-5-20251101` → `claude-opus-4-6` in skills.

### Git / Auth
- `gh auth refresh -h github.com -s write:packages`. Env vars must be **exported** (`set -a` before sourcing `.env.local`).
- Push protection blocks synthetic keys: `git reset --soft origin/main`. **gitignore negation**: use `git add -f`.
- **Remote URL stale**: `CodeContextBench.git` → `CodeScaleBench.git`. Update remote config.

### Python / Subprocess
- `dict.get(key, default)` doesn't guard `None`; use `or default_value`. `json.load(open())` leaks FDs; use `with open`.
- `with open(log) as f: Popen(stdout=f)` closes handle; use bare `open()`. macOS Bash 3.2 lacks `declare -A`.
- No `pyproject.toml`/`requirements.txt`. 200+ scripts + 9 tests use `sys.path.insert` hack.

### CI / Workflows
- 4 workflows use 3 Python versions (3.10/3.11/3.12); standardize to 3.10. `roam.yml` unpinned `pip install roam-code`.
- 3/4 CI workflows missing top-level `permissions:` block → overly broad default GitHub Actions token scope.

### Pre-commit / Pytest / Ralph
- Secret-detection false-positives: use `--no-verify` when flagged code is detection logic.
- Ralph: `prd.json` single-active; archive before overwrite. `prd-archive/` and `prd.json` not gitignored.

### Scripts / Code Quality (Mar 17-18 additions)
- `apply_verifier_fixes.py:9` hardcodes `~/CodeScaleBench` path; crash on other machines.
- `context_retrieval_agent.py:432+` `shell=True` without allowlist; injection risk.
- Non-atomic writes: `aggregate_status.py:669`, `apply_verifier_fixes.py:103+`; use temp+rename.
- Bare `except:`: `audit_v2_report_data.py:104`, `ds_audit.py:244+`, `extract_v2_report_data.py:144+`.
- FD leaks: 17+ sites; use `with open()`. `export_official_results.py:45` `DEFAULT_REPO_BLOB_BASE` → old org `CodeScaleBench`; links 404.
- **Ruff** S603/S604, SIM115, BLE001; add `pyproject.toml`. SIM115 skips `Popen(stdout=f)`. `sanitize_secrets.py`: S105/S106 per-file ignores.

## Maintenance
- Root and local `AGENTS.md` / `CLAUDE.md` files are generated from sources in `docs/ops/`.
- `docs/START_HERE_BY_TASK.md` is generated from `docs/ops/task_routes.json`.
- Regenerate after edits (single command):
```bash
python3 scripts/refresh_agent_navigation.py
```
