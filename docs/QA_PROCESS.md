# CodeContextBench Quality Assurance Process

End-to-end quality assurance and validation infrastructure for CodeContextBench benchmark runs. This document describes each pipeline stage, the scripts involved, and the audit methodology.

---

## Pipeline Overview

```
PRE-FLIGHT                    DURING RUN              POST-RUN                    AUDIT
──────────                    ──────────              ────────                    ─────
validate_tasks_preflight.py   aggregate_status.py     validate_task_run.py        QA audit (6-dimension)
check_infra.py                (--since / --watch)     aggregate_status.py
                                                      status_fingerprints.py
                                                      sync_task_metadata.py
```

---

## 1. Pre-Flight Validation

**Script:** `scripts/validate_tasks_preflight.py`

Runs before any benchmark execution to catch task definition errors that would waste compute time.

**Checks performed:**
- **Truncated instructions** -- `instruction.md` must be at least 200 characters
- **Template placeholders** -- Detects unresolved `#ISSUE_NUMBER`, `#REPO_NAME`, `{{}}`, `<PLACEHOLDER>` tokens
- **Language/difficulty mismatch** -- Cross-references `task.toml` fields against `selected_benchmark_tasks.json`
- **Missing test scripts** -- Verifies `tests/test.sh` is present and executable
- **Missing tasks** -- Detects tasks in the selection registry that have no corresponding benchmark directory

### Runtime Smoke (No Agent)

Pre-flight now also supports a **runtime smoke mode** that validates task runtime wiring without spending model tokens:
- Builds the task Docker image
- Runs verifier script (`/tests/test.sh`) in-container
- Checks reward file creation (`/logs/verifier/reward.txt` or `.json`)
- Tries both common Docker build contexts automatically (`task root` then `environment/`)

Use this for new/modified tasks and before large reruns involving task-definition changes.

Interpretation notes:
- `WARNING smoke_verifier_nonzero_with_reward` is acceptable for no-agent smoke (dummy solution expected to fail tests but verifier wiring is healthy).
- `CRITICAL smoke_build_timeout` means Docker image build exceeded timeout.
- `CRITICAL smoke_verify_timeout` means verifier execution exceeded timeout.

**Quick sweep helper (one task per benchmark):**
```bash
# No-agent runtime smoke across one representative task per benchmark
bash configs/validate_one_per_benchmark.sh --smoke-runtime --smoke-timeout-sec 300

# Override timeout-heavy suites (format: suite=seconds,suite=seconds)
bash configs/validate_one_per_benchmark.sh --smoke-runtime --smoke-timeout-sec 300 \
  --smoke-timeout-overrides "ccb_pytorch=900,ccb_tac=900,ccb_crossrepo=900"
```

**Usage:**
```bash
# Validate all tasks (static checks)
python3 scripts/validate_tasks_preflight.py --all

# Validate a specific suite
python3 scripts/validate_tasks_preflight.py --suite ccb_pytorch

# Validate a single task
python3 scripts/validate_tasks_preflight.py --task benchmarks/ccb_pytorch/sgt-005

# Runtime smoke for a single task (no agent)
python3 scripts/validate_tasks_preflight.py --task benchmarks/ccb_largerepo/big-code-k8s-001 --smoke-runtime

# Runtime smoke for a suite (expensive)
python3 scripts/validate_tasks_preflight.py --suite ccb_largerepo --smoke-runtime --smoke-timeout-sec 900

# Separate build/verifier timeouts (for phase-level diagnosis)
python3 scripts/validate_tasks_preflight.py --task benchmarks/ccb_pytorch/sgt-001 \
  --smoke-runtime --smoke-build-timeout-sec 900 --smoke-verify-timeout-sec 900
```

---

## 2. Infrastructure Checks

**Script:** `scripts/check_infra.py`

Verifies that the execution environment is ready before launching runs.

**Checks performed:**
- **OAuth tokens** -- Validates tokens for all configured accounts with 30-minute expiry margin; auto-refreshes if needed
- **Docker** -- Confirms Docker daemon is running and accessible
- **Disk space** -- Warns if available space is below threshold
- **Harbor CLI** -- Verifies `harbor` command is available and functional

**Usage:**
```bash
python3 scripts/check_infra.py
```

**Multi-account support:** When using `~/.claude-homes/accountN/` directories for parallel execution, the script validates OAuth credentials for each account independently.

---

## 3. Error Fingerprinting

**Script:** `scripts/status_fingerprints.py`

Classifies task failures into known categories using 12 regex patterns. Each pattern includes severity level and auto-retry guidance.

**Fingerprint patterns:**

| Pattern | Description | Auto-Retry |
|---------|-------------|------------|
| `token_refresh_403` | OAuth token refresh failure | Yes |
| `api_500` | API 500 server error | Yes |
| `api_rate_limit` | API rate limit / overloaded | Yes (with backoff) |
| `context_window_exceeded` | Context window exceeded | No |
| `timeout` | Task timeout | No |
| `mcp_connection` | MCP server connection failure | Yes |
| `verifier_parse_error` | Verifier output parse error | No |
| `import_error` | Python import error | No |
| `docker_compose_fail` | Docker/container failure | No |
| `permission_denied` | Permission denied | No |
| `git_error` | Git operation failure | No |
| `deep_search_polling_only` | Deep Search returned polling-only response | Yes (with retry instructions) |

**Integration:** Used by `aggregate_status.py` to annotate per-task status and by `rerun_failed.py` to generate targeted rerun commands.

See [ERROR_CATALOG.md](ERROR_CATALOG.md) for the full catalog with root causes, affected benchmarks, and fixes.

---

## 4. Post-Run Validation

**Script:** `scripts/validate_task_run.py`

Validates individual task run output after execution completes.

**Checks performed:**
- Task completed without crashing (non-zero exit codes)
- MCP tool usage anomalies (tools configured but never called, or vice versa)
- Suspicious scoring patterns (reward=1.0 with 0 tokens spent)
- Result.json structure and required fields

**Usage:**
```bash
python3 scripts/validate_task_run.py <run_dir>
```

---

## 5. Run Analysis & Status Scanning

**Script:** `scripts/aggregate_status.py`

Core run scanner that processes all run directories under `runs/official/`.

**Capabilities:**
- Scans for `result.json` files in all run directories
- Classifies task status (success, failure, error, in-progress)
- Applies error fingerprinting from `status_fingerprints.py`
- Writes per-task `status.json` files for downstream tooling
- Supports `--watch` mode for continuous monitoring during active runs
- Supports `--since` for lightweight scoping to recent activity

**Directory layout support:** Handles both `config/batch_timestamp/task__hash/` and `config/task__hash/` layouts.

**Usage:**
```bash
# Full scan
python3 scripts/aggregate_status.py

# Watch mode (re-scans every 30s)
python3 scripts/aggregate_status.py --watch

# Recent activity only
python3 scripts/aggregate_status.py --since 2h
```

---

## 6. Metadata Reconciliation

**Script:** `scripts/sync_task_metadata.py`

Keeps `task.toml` fields in sync with the canonical `selected_benchmark_tasks.json` registry.

**Detects drift in:**
- Language field
- Difficulty field
- Time limit
- Repository name
- MCP benefit score

**Usage:**
```bash
# Dry run (report mismatches)
python3 scripts/sync_task_metadata.py

# Auto-fix mismatches
python3 scripts/sync_task_metadata.py --fix
```

---

## 7. QA Audit Methodology

Periodic full audits use a 6-dimension framework to ensure benchmark integrity:

### Dimension 1: Instruction Contamination

Checks whether `instruction.md` files contain references to MCP tools or Sourcegraph that would leak context into baseline (no-tool) runs. Any MCP-specific instructions should be injected at runtime via the agent harness, not baked into the task definition.

### Dimension 2: Reproducibility

Verifies that task environments produce deterministic results:
- Dockerfiles use pinned base images and dependency versions
- Git clones specify exact commits (no `--depth 1` with floating HEAD)
- No external network dependencies during verification

### Dimension 3: Verifier Correctness

Validates that test scripts and scoring functions produce accurate rewards:
- Tests that always pass (reward=1.0 regardless of agent output) indicate broken verifiers
- Tests that always fail may indicate missing dependencies or mount issues
- Cross-references expected rewards against agent behavior

### Dimension 4: Ghost & False-Positive Detection

Identifies anomalous runs:
- **Ghost runs** -- 0 tokens spent but result.json exists (Harbor scaffolding artifacts)
- **False positives** -- reward=1.0 with 0 tokens (verifier passed without agent work)
- **Duplicate runs** -- Same task with divergent rewards across duplicate executions

### Dimension 5: Error Misclassification

Reviews whether task failures are correctly attributed:
- Context window exhaustion misclassified as task failure
- Infrastructure errors (token refresh, API 500) counted as task inability
- MCP connection failures attributed to task difficulty

### Dimension 6: Tool Effectiveness

Analyzes whether MCP tools are being used effectively:
- Deep Search compliance rate (new instruction format vs old)
- Polling success rate (percentage of Deep Search calls that return actual results)
- Tool utilization patterns per config (are MCP tools actually invoked?)

---

## Related Documentation

- [ERROR_CATALOG.md](ERROR_CATALOG.md) -- Known error fingerprints with root causes and fixes
- [CONFIGS.md](CONFIGS.md) -- 3-config evaluation matrix details
- [TASK_SELECTION.md](TASK_SELECTION.md) -- Task selection methodology and MCP benefit scoring
- [TASK_CATALOG.md](TASK_CATALOG.md) -- Detailed per-task reference
