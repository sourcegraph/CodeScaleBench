# Handoff: Trace Audit Fixes → Rerun Setup

## Goal
Set up and launch reruns for tasks identified by the trace audit. Three categories:
1. **Promote** staging batches that contain successful feature/refactor runs
2. **Local Docker** reruns for sweap-images and fixed ccb_fix tasks (Daytona-incompatible)
3. **Daytona** reruns for remaining gap tasks

## Current Status
- **Trace audit complete**: 804 MANIFEST entries audited, 115 zero-reward classified
- **Fixes applied this session** (committed, not yet run):
  - `navidrome-windows-log-fix-001/tests/test.sh` — pytest→go test (Go/Ginkgo project)
  - `nodebb-notif-dropdown-fix-001/tests/test.sh` — pytest→npx mocha + Mocha reward parsing
  - `nodebb-plugin-validate-fix-001/tests/test.sh` — pytest→npx mocha + Mocha reward parsing
  - `openlibrary-solr-boolean-fix-001/environment/Dockerfile.sg_only` — Node.js 22 + Claude Code pre-install
  - `scripts/generate_manifest.py` — model fallback fix (was defaulting to opus)
  - `configs/selected_benchmark_tasks.json` — 2 llamacpp TAC tasks removed (414→412)
- **MANIFEST regenerated** with correct model attribution
- **2 llamacpp TAC tasks dropped** to `benchmarks/backups/ccb_test_tac/` (need external RocketChat server)

## Files Changed This Session
- `scripts/generate_manifest.py` — model extraction fallback to result.json
- `benchmarks/ccb_fix/navidrome-windows-log-fix-001/tests/test.sh`
- `benchmarks/ccb_fix/nodebb-notif-dropdown-fix-001/tests/test.sh`
- `benchmarks/ccb_fix/nodebb-plugin-validate-fix-001/tests/test.sh`
- `benchmarks/ccb_fix/openlibrary-solr-boolean-fix-001/environment/Dockerfile.sg_only`
- `configs/selected_benchmark_tasks.json`
- `runs/official/MANIFEST.json` (regenerated)
- `benchmarks/ccb_test/llamacpp-*` → `benchmarks/backups/ccb_test_tac/`

## Action Items (in priority order)

### 1. Promote Staging Batches (feature/refactor errored tasks)
12 feature/refactor tasks errored due to premature promotion (staging dir moved while Harbor still writing). Successful runs exist in later staging batches.

```bash
# Check these batches have the previously-errored tasks with valid results:
python3 scripts/promote_run.py --dry-run feature_haiku_20260301_031848
python3 scripts/promote_run.py --dry-run feature_haiku_20260301_071229
python3 scripts/promote_run.py --dry-run refactor_haiku_20260301_031849

# Promote (may need --force if warning count is high):
python3 scripts/promote_run.py --execute feature_haiku_20260301_031848
python3 scripts/promote_run.py --execute feature_haiku_20260301_071229
python3 scripts/promote_run.py --execute --max-warnings 21 refactor_haiku_20260301_031849
```

After promotion, regenerate MANIFEST:
```bash
python3 scripts/generate_manifest.py
```

### 2. Local Docker Reruns (sweap-images — Daytona-incompatible)
These tasks use `jefzda/sweap-images:*` base images from Docker Hub. Daytona can't pull from Docker Hub.

#### 2a. Fixed ccb_fix tasks (3 tasks, both configs)
These had broken verifiers (now fixed). Need fresh baseline + MCP runs:
- `navidrome-windows-log-fix-001` (Go test fix)
- `nodebb-notif-dropdown-fix-001` (Mocha fix)
- `nodebb-plugin-validate-fix-001` (Mocha fix)

```bash
# Use the ccb_fix 2-config launcher with just these 3 tasks
# Edit a targeted config or use run_selected_tasks.sh with task filtering
source .env.local
export HARBOR_ENV=local

# Run each task with both configs:
configs/run_selected_tasks.sh --suite ccb_fix \
  --tasks "navidrome-windows-log-fix-001,nodebb-notif-dropdown-fix-001,nodebb-plugin-validate-fix-001" \
  --full-config
```

#### 2b. 9 debug sweap-images tasks (variance)
These always fail on Daytona. Need local runs for variance:
- All `ccb_debug` tasks using sweap-images base (check Dockerfiles for `jefzda/sweap-images`)

```bash
# Identify them:
grep -l 'sweap-images' benchmarks/ccb_debug/*/environment/Dockerfile | sed 's|/environment/Dockerfile||' | xargs -I{} basename {}
```

### 3. Daytona Reruns (cloud — preferred)

#### 3a. openlibrary MCP rerun (1 task)
The Dockerfile.sg_only was fixed (Node.js 22 pre-installed). Need fresh MCP run:
- `openlibrary-solr-boolean-fix-001` — MCP config only

```bash
source .env.local
export HARBOR_ENV=daytona
export DAYTONA_OVERRIDE_STORAGE=10240

configs/run_selected_tasks.sh --suite ccb_fix \
  --tasks "openlibrary-solr-boolean-fix-001" \
  --mcp-only
```

#### 3b. flipt-dep-refactor-001 baseline rerun (1 task)
One-off Harbor extraction failure. Just needs a simple rerun:
- `flipt-dep-refactor-001` — baseline config only

```bash
configs/run_selected_tasks.sh --suite ccb_refactor \
  --tasks "flipt-dep-refactor-001" \
  --baseline-only
```

#### 3c. ccb_fix variance: 17 tasks need +1 MCP run
ccb_fix has 3 complete passes for baseline but only 2 for MCP on 17 tasks.

```bash
# Launch MCP-only pass for ccb_fix variance:
configs/run_selected_tasks.sh --suite ccb_fix --mcp-only
```

#### 3d. MCP-unique gap tasks (211 tasks across 11 suites)
Priority split:
- **77 tasks**: Have baseline results, need MCP runs only
- **134 tasks**: Need both baseline AND MCP runs

The gap is documented in the run-gap context below. Use `configs/run_selected_tasks.sh` with per-suite filtering.

**Suites with MCP-unique gaps** (task counts — both/mcp-only):
| Suite | Both needed | MCP only needed |
|-------|------------|----------------|
| ccb_mcp_compliance | 11 | 9 |
| ccb_mcp_crossorg | 14 | 6 |
| ccb_mcp_crossrepo | 13 | 6 |
| ccb_mcp_crossrepo_tracing | 12 | 7 |
| ccb_mcp_dependency | 8 | 12 |
| ccb_mcp_domain | 14 | 6 |
| ccb_mcp_incident | 13 | 7 |
| ccb_mcp_migration | 12 | 8 |
| ccb_mcp_onboarding | 14 | 6 |
| ccb_mcp_search | 10 | 5 |
| ccb_mcp_security | 13 | 5 |

```bash
# For suites needing both configs:
configs/run_selected_tasks.sh --suite ccb_mcp_compliance --full-config

# For suites needing MCP only:
configs/run_selected_tasks.sh --suite ccb_mcp_compliance --mcp-only
```

### 4. SDLC Variance Promotions
Multiple staging batches exist for all 9 SDLC suites. Check and promote as needed:
```bash
ls runs/staging/ | grep -E '^(debug|design|document|feature|refactor|secure|test|understand|fix)_haiku' | sort
```

## Findings / Decisions
- **3 broken verifiers fixed**: navidrome (Go), 2x nodebb (Mocha) — were using pytest on non-Python projects
- **MANIFEST model bug fixed**: ccb_feature/ccb_refactor now correctly show haiku (was defaulting to opus)
- **openlibrary Dockerfile.sg_only fixed**: sweap-images Node.js 16 → pre-install Node.js 22 + Claude Code
- **2 llamacpp TAC tasks permanently dropped**: Need external RocketChat/GitLab servers, incompatible with single-container benchmark
- **12 errored feature/refactor**: Root cause was premature `promote_run.py` execution; valid runs exist in staging
- **flipt-dep-refactor-001**: One-off Harbor extraction failure; needs simple baseline rerun

## Open Risks / Unknowns
- openlibrary Dockerfile.sg_only fix is untested — first MCP run will validate the Node.js 22 pre-install approach
- flipt-dep-refactor-001 passed with 0 trajectory entries — rerun will determine if this is reproducible
- 9 debug sweap-images tasks consistently fail on Daytona — must always use local Docker
- DAYTONA_OVERRIDE_STORAGE=10240 required (39 tasks have storage="20G" in task.toml)

## Environment Setup
```bash
# Daytona (default for most tasks):
source .env.local
export HARBOR_ENV=daytona
export DAYTONA_OVERRIDE_STORAGE=10240

# Local Docker (sweap-images only):
source .env.local
export HARBOR_ENV=local
```

## Next Best Command
```bash
# Start with promoting completed staging batches:
python3 scripts/promote_run.py --dry-run feature_haiku_20260301_031848
```
