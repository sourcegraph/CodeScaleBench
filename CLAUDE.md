# CodeContextBench

## Project Structure

```
configs/
  _common.sh                 # Shared infra: token refresh, parallel execution, multi-account
  *_3config.sh               # Per-benchmark run scripts (12 total; DependEval has no 3config yet)
  selected_benchmark_tasks.json  # Task selection with metadata, difficulty, MCP scores

benchmarks/
  ccb_{benchmark}/{task}/    # Task definitions
    task.toml                # Harbor config (difficulty, language, time limit)
    instruction.md           # Agent prompt
    tests/test.sh            # Verification script

runs/official/               # Run output directories
  MANIFEST.json              # Canonical run tracking

scripts/
  generate_manifest.py       # Rebuild MANIFEST from on-disk results
  validate_task_run.py       # Post-run validation
  select_benchmark_tasks.py  # Task selection logic
  aggregate_status.py        # Core run scanner (status, errors, watch mode)
  status_fingerprints.py     # Error classification (10 regex patterns)
  compare_configs.py         # Cross-config divergence analysis
  validate_tasks_preflight.py # Pre-flight task validation
  check_infra.py             # Infrastructure readiness checker
  cost_report.py             # Token/cost aggregation
  sync_task_metadata.py      # task.toml vs selection registry reconciliation
  archive_run.py             # Archive old runs to save disk
  rerun_failed.py            # Generate rerun commands for failed tasks

docs/
  TASK_SELECTION.md          # Selection criteria, difficulty calibration, MCP scoring
  ERROR_CATALOG.md           # Known error fingerprints, causes, fixes
```

## Benchmarks (13)

| Benchmark | Tasks | Language(s) | Focus |
|-----------|-------|-------------|-------|
| SWE-bench Pro | 36 | Go, TS, Python | Real-world SWE across repos |
| DependEval | 32 | Java, JS, Python, TS | Dependency ordering |
| PyTorch | 12 | Python | PyTorch PR-level tasks |
| LoCoBench | 25 | Mixed | Long-context understanding |
| RepoQA | 10 | Mixed | Repository Q&A |
| K8s Docs | 5 | Go | Kubernetes documentation |
| CrossRepo | 4-5 | Mixed | Cross-repository reasoning |
| LargeRepo | 4 | Go, Rust, Python, TS | Large codebase tasks |
| TAC | 6 | Mixed | Tool-augmented coding |
| DIBench | 8 | Mixed | Dependency installation |
| SWE-Perf | 3 | Python | Performance optimization |
| CodeReview | 3 | TS, C#, Mixed | AI code review: find & fix injected PR defects |
| LinuxFLBench | 5 | C | Linux kernel fault localization |

## Running Tasks

```bash
# Run a single benchmark (3 configs: baseline, SG_base, SG_full)
./configs/pytorch_3config.sh

# Run with parallel execution
./configs/pytorch_3config.sh --parallel

# Override parallelism
./configs/pytorch_3config.sh --parallel 4
```

See [AGENTS.md](AGENTS.md) for parallel execution details and multi-account setup.

## Authentication

Uses Claude Max subscription OAuth tokens (not API keys).

- Credentials: `~/.claude/.credentials.json` (single account) or `~/.claude-homes/accountN/.claude/.credentials.json` (multi-account)
- Auto-refresh: 30-minute margin before expiry via `refresh_claude_token()` in `_common.sh`
- Multi-account: Round-robin distribution across Max-plan accounts for parallel runs

### Headless Token Refresh

When automated token refresh fails (e.g., Cloudflare 1010 block), use the headless login script to re-authenticate via browser:

```bash
# Refresh all accounts (account1, account2, account3)
python3 scripts/headless_login.py --all-accounts

# Refresh a single account
python3 scripts/headless_login.py --home ~/.claude-homes/account1
```

The script generates an OAuth URL — open it in your local browser, log in, paste the authorization code back into the terminal. Skip account2 (team plan, not used) by entering a blank code.

## Key Commands

```bash
# Regenerate MANIFEST from on-disk results
python3 scripts/generate_manifest.py

# Generate evaluation report
python3 scripts/generate_report.py

# Select benchmark tasks
python3 scripts/select_benchmark_tasks.py
```

## Operational Skills (13)

Slash commands for the full benchmark lifecycle. Use these in Claude Code sessions.

### Workflow by Phase

```
PRE-RUN                DURING RUN           POST-RUN              ANALYSIS              QA
───────                ──────────           ────────              ────────              ──
/check-infra      -->  /run-status     -->  /watch-benchmarks --> /compare-configs  --> /benchmark-audit
/validate-tasks        (lightweight)        (full scan)           /cost-report          /score-tasks
                                            /whats-next           /generate-report
                                            /triage-failure
                                            /quick-rerun

MAINTENANCE
───────────
/sync-metadata
/archive-run
```

### Pre-Run

| Skill | Script | Purpose |
|-------|--------|---------|
| `/check-infra` | `scripts/check_infra.py` | Verify OAuth tokens (all accounts), API keys, Docker, disk space, harbor CLI |
| `/validate-tasks` | `scripts/validate_tasks_preflight.py` | Catch truncated instructions, template placeholders, metadata mismatches, missing test.sh |

### During Run

| Skill | Script | Purpose |
|-------|--------|---------|
| `/run-status` | `aggregate_status.py --since` | Lightweight check on active run progress |

### Post-Run

| Skill | Script | Purpose |
|-------|--------|---------|
| `/watch-benchmarks` | `scripts/aggregate_status.py` | Full scan of runs/official/ with error fingerprinting, --watch mode, per-task status.json |
| `/whats-next` | (uses aggregate_status + compare_configs) | Analyze current state and recommend next actions |
| `/triage-failure` | (reads logs + fingerprints) | Investigate a specific failed task: read logs, classify error, suggest fix |
| `/quick-rerun` | (harbor run wrapper) | Rerun a single task with haiku model for fast verification |

### Analysis

| Skill | Script | Purpose |
|-------|--------|---------|
| `/compare-configs` | `scripts/compare_configs.py` | Show divergent tasks across baseline/SG_base/SG_full, "MCP helps" vs "MCP hurts" |
| `/cost-report` | `scripts/cost_report.py` | Token usage and estimated cost by suite/config, most expensive tasks |
| `/generate-report` | `scripts/generate_report.py` | Aggregate CCB evaluation report from completed runs |

### QA

| Skill | Script | Purpose |
|-------|--------|---------|
| `/benchmark-audit` | `scripts/abc_audit.py` | Audit benchmark against ABC framework (Task/Outcome/Reporting validity) |
| `/score-tasks` | `scripts/abc_score_task.py` | Score task quality (instruction clarity, verifier quality, reproducibility) |

### Maintenance

| Skill | Script | Purpose |
|-------|--------|---------|
| `/sync-metadata` | `scripts/sync_task_metadata.py` | Reconcile task.toml vs selected_benchmark_tasks.json, `--fix` to auto-update |
| `/archive-run` | `scripts/archive_run.py` | Move old runs to archive/, optional compression, dry-run by default |

### Supporting Scripts

| Script | Purpose |
|--------|---------|
| `scripts/status_fingerprints.py` | Error classification with 10 regex patterns (token_refresh_403, api_500, mcp_connection, etc.) |
| `scripts/rerun_failed.py` | Generate harbor run commands for failed tasks, filterable by fingerprint/suite/config |
| `docs/ERROR_CATALOG.md` | Living catalog of known errors with fingerprints, causes, fixes, auto-retry guidance |

### Architecture Notes

- All operational scripts reuse constants from `aggregate_status.py` (RUNS_DIR, SKIP_PATTERNS, DIR_PREFIX_TO_SUITE, CONFIGS)
- Error fingerprinting via `status_fingerprints.py` handles both Harbor key conventions (`exception_type`/`exception_message`) and generic (`type`/`message`)
- `aggregate_status.py` handles two directory layouts: `config/batch_timestamp/task__hash/` and `config/task__hash/`

## Known Issues

- **SWE-Perf**: Scaffolding only. Dockerfiles create empty workspaces. Needs repo clones + benchmark infra.
- **CrossRepo**: Verifier fixed but ~80% task failure rate due to task difficulty.
- **K8s Docs SG_full**: API 500 error on applyconfig-doc-001 (not MCP-related).
- **LoCoBench**: Template weights updated but 25 task verify.py files still reference old weights.

## MCP Benefit Scoring

4-component weighted formula: `cc(0.25) + cfd(0.30) + ssp(0.20) + tcw(0.25)`

- `cc` = context_complexity (codebase size, LOC)
- `cfd` = cross_file_deps (number of files/packages involved)
- `ssp` = semantic_search_potential (how much search helps)
- `tcw` = tool_chain_weight (fixed per benchmark)

Per-task features extracted from task.toml metadata, instruction.md, and config.json. See `docs/TASK_SELECTION.md` for methodology.

## Difficulty Labels

| Benchmark | Metric | Thresholds |
|-----------|--------|------------|
| SWE-bench Pro | files_changed | 1-3=medium, 4-10=hard, 10+=very_hard |
| PyTorch | LOC (additions+deletions) | <50=medium, 50-200=hard, >200=very_hard |
| LoCoBench | task category | architectural=expert, others=hard |
| RepoQA | source file count | <100=medium, 100+=hard |
| CrossRepo | manual | easy to hard |

## Task Tracking (Beads)

Use `bd` (beads) for ALL task/issue tracking. Do NOT use TodoWrite, TaskCreate, or markdown task lists.

```bash
bd ready                    # Find available work (no blockers)
bd create --title="..." --type=task --priority=2  # Create issue
bd update <id> --status=in_progress               # Claim work
bd close <id> --reason="done"                     # Mark complete
bd sync                     # Sync with git (run at session end)
```

Priority: 0-4 (0=critical, 4=backlog). Never use "high"/"medium"/"low".

**WARNING**: Do NOT use `bd edit` — it opens $EDITOR which blocks agents. Use `bd update` with flags.

## Landing the Plane (Session Completion)

**When ending a work session**, you MUST complete ALL steps below. Work is NOT complete until `git push` succeeds.

**MANDATORY WORKFLOW:**

1. **File beads issues for remaining work** — `bd create` for anything that needs follow-up
2. **Run quality gates** (if code changed) — tests, linters, builds; file P0 issues if broken
3. **Update beads issues** — `bd close` finished work, update in-progress items
4. **PUSH TO REMOTE (non-negotiable)**:
   ```bash
   git pull --rebase
   # If conflicts in .beads/issues.jsonl: git checkout --theirs .beads/issues.jsonl && bd import
   bd sync
   git push
   git status   # MUST show "up to date with origin"
   ```
5. **Clean up** — `git stash clear`, `git remote prune origin`
6. **Verify** — all changes committed AND pushed, no untracked files
7. **Hand off** — provide context for next session: summary of completed work, filed issues, recommended next prompt

**CRITICAL RULES:**
- The plane has NOT landed until `git push` completes successfully
- NEVER stop before pushing — that leaves work stranded locally
- NEVER say "ready to push when you are" — YOU must push, not the user
- If push fails, resolve the issue and retry until it succeeds
- The user manages multiple agents — unpushed work breaks coordination

## Progress Tracking

User stories tracked in `progress.txt` (US-001 through US-022 completed). Codebase patterns are documented at the top of that file.
