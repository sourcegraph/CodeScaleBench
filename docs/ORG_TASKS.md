# CodeScaleBench-Org / Org-Scale Context Retrieval Tasks

This document covers the Org benchmark extension — tasks that measure how
MCP tools help agents with cross-repo discovery, symbol resolution, dependency
tracing, and deep-search-driven investigation in polyrepo environments.

## Overview

Org tasks exercise **org-scale polyrepo** scenarios where the answer
requires information spread across 3-20 repositories. Both baseline and MCP-Full
agents have access to all repos — the only difference is the method of access:

```
Baseline agent:  All repos cloned locally in /workspace
                 → uses built-in tools (grep, read, glob)
                 → full information, local search

MCP-Full agent:  Local code truncated/empty
                 → uses Sourcegraph MCP tools (keyword_search, find_references, etc.)
                 → full information, remote search
```

This measures whether MCP tools help agents work **better or faster** on
cross-repo tasks — not whether MCP can access information the baseline can't.

**Key differentiators vs existing cross-repo tasks:**
- **Org-scale quantity**: 3-20 repos per task (vs 2 in old CrossRepo suite)
- **Closed-world oracle**: exhaustive oracle files/symbols auto-curated via SG queries
- **Customer-framed prompts**: from 100 GTM use cases grounded in real customer pain
- **Cross-org scope**: repos from different GitHub organizations
- **Deep Search variants**: tasks that specifically benefit from DS synthesis

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                  CodeScaleBench-Org Task System                     │
│                                                             │
│  configs/use_case_registry.json        (100 use cases)     │
│         │                                                   │
│         ▼                                                   │
│  scripts/generate_mcp_unique_tasks.py  (task generator)    │
│         │                                                   │
│         ▼                                                   │
│  benchmarks/csb_org_<suite>/<task>/                        │
│    ├── task.toml           (Harbor task definition)         │
│    ├── instruction.md      (customer-framed prompt)         │
│    ├── environment/                                         │
│    │   ├── Dockerfile       (baseline: clones local repo)   │
│    │   └── Dockerfile.sg_only  (MCP-full: no clone)        │
│    └── tests/                                               │
│        ├── eval.sh          (exit-code-first evaluator)     │
│        ├── task_spec.json   (PRD-centered spec)             │
│        ├── oracle_answer.json  (gold agent answer)          │
│        ├── oracle_checks.py    (stdlib eval library)        │
│        └── criteria.json   (rubric for DS tasks, optional)  │
│                                                             │
│  scripts/csb_metrics/retrieval.py      (KPI extractor)     │
│  scripts/curate_oracle.py              (oracle auto-curator)│
│  scripts/validate_mcp_task_instance.py (validity gate)     │
└────────────────────────────────────────────────────────────┘
```

## Suite Structure

Suites map to use case categories A-K. Suite sizes use DOE-driven Neyman-optimal allocation to maximize statistical power per suite:

| Suite | Category | Description | Tasks |
|-------|----------|-------------|------:|
| `csb_org_onboarding` | E | Architecture comprehension + API discovery | 28 |
| `csb_org_migration` | C | Framework upgrades across repos | 26 |
| `csb_org_security` | B | Vulnerability + security remediation at scale | 24 |
| `csb_org_crossrepo_tracing` | A | Cross-repo dependency tracing + symbol resolution | 22 |
| `csb_org_domain` | H | Domain-specific lineage and analysis | 20 |
| `csb_org_incident` | D | On-call / incident debugging across microservices | 20 |
| `csb_org_compliance` | F | Compliance / audit / provenance | 18 |
| `csb_org_platform` | J | Platform / DevTools / tribal knowledge | 18 |
| `csb_org_crossorg` | G | Cross-org discovery (repos from different GitHub orgs) | 15 |
| `csb_org_org` | I | Agentic coding correctness using org-wide context | 15 |
| `csb_org_crossrepo` | K | Cross-repo search, dependency discovery, impact analysis | 14 |
| **Total** | | | **220** |

All 220 Org tasks are registered in the unified `configs/selected_benchmark_tasks.json` alongside the 150 SDLC tasks (370 total).

## Repo Sets

Each task's Dockerfile defines its repo set — all repos are cloned for
baseline, truncated for MCP-Full. Common repo groupings across tasks:

| Repo Set | Repos | Cross-Org | Language |
|----------|-------|-----------|----------|
| Kubernetes ecosystem | kubernetes, client-go, api, etcd | Yes (k8s + etcd-io) | Go |
| Node.js web stack | node, express, lodash, prisma | Yes (4 orgs) | JS/TS |
| Python ML stack | scikit-learn, numpy, pandas, scipy | Yes (4 orgs) | Python |
| Grafana observability | grafana, loki, mimir | No (all grafana) | Go/TS |
| Multi-org Go | kubernetes, etcd, grafana | Yes (3 orgs) | Go |
| Prometheus monitoring | prometheus, alertmanager, client_golang | No (all prometheus) | Go |

Repos not natively indexed in Sourcegraph use `sg-evals` mirrors
(e.g., `sg-evals/kubernetes-client-go`). The Dockerfile is the
source of truth for which repos a task uses and at what version.

## Task Authoring

### Using the Generator (recommended)

```bash
# Generate a task for use case ID 1 (dry run to preview)
python3 scripts/generate_mcp_unique_tasks.py --use-case-ids 1 --dry-run

# Generate with oracle curation
python3 scripts/generate_mcp_unique_tasks.py --use-case-ids 1 --curate-oracle

# Generate all category A tasks
python3 scripts/generate_mcp_unique_tasks.py --category A

# Generate and validate
python3 scripts/generate_mcp_unique_tasks.py --use-case-ids 1 --validate
```

The generator reads `configs/use_case_registry.json` to fill
`templates/csb-org/*.j2` templates.

### Worked Example: CCX-dep-trace-001

**Scenario**: Given the error `k8s.io/apimachinery/pkg/runtime is imported by
the dynamic/ tree of kubernetes-client-go`, find all importing files.

**Step 1: Check the use case registry**
```bash
python3 -c "
import json
reg = json.load(open('configs/use_case_registry.json'))
uc = next(u for u in reg['use_cases'] if u['use_case_id'] == 1)
print(uc['customer_prompt'])
"
```

**Step 2: Generate the task skeleton**
```bash
python3 scripts/generate_mcp_unique_tasks.py \
  --use-case-ids 1 \
  --out benchmarks/ \
  --verbose
```
This creates `benchmarks/csb_org_crossrepo_tracing/ccx-dep-trace-001/` with all
files from the template.

**Step 3: Curate the oracle using Sourcegraph MCP**
```bash
python3 scripts/curate_oracle.py \
  --task-dir benchmarks/csb_org_crossrepo_tracing/ccx-dep-trace-001 \
  --verbose
```
The curator uses `mcp__sourcegraph__keyword_search` and `mcp__sourcegraph__find_references`
to discover all files matching the task's `seed_prompt`. It writes:
- `tests/oracle_answer.json`: the gold answer (what a perfect agent would output)
- `tests/oracle_curation_log.json`: the full trace of SG queries

**Step 4: Validate the oracle (fail2pass gate)**
```bash
python3 scripts/validate_mcp_task_instance.py \
  --task-dir benchmarks/csb_org_crossrepo_tracing/ccx-dep-trace-001 \
  --verbose
```
Expected: `ccx-dep-trace-001: VALID` (gold=1.0, empty=0.0)

**Step 5: Register in selection file**
Add an entry to `configs/selected_benchmark_tasks.json`.

**Step 6: Run preflight**
```bash
python3 scripts/validate_tasks_preflight.py --suite csb_org_crossrepo_tracing
```

### Manual Oracle Authoring

For tasks where automated curation misses items:

1. Search Sourcegraph using `mcp__sourcegraph__keyword_search` with the task's
   target pattern
2. Verify file paths are real with `mcp__sourcegraph__read_file`
3. Edit `tests/oracle_answer.json` directly:
   ```json
   {
     "files": [{"repo": "sg-evals/kubernetes-client-go", "path": "dynamic/scheme.go"}],
     "symbols": [],
     "chain": [],
     "text": ""
   }
   ```
4. Re-run the validity gate to confirm gold=1.0, empty=0.0

## Evaluation Framework

### Exit-Code-First (SWE-Factory Pattern)

Every task's `eval.sh` exits 0 for useful output, 1 for total failure:

```bash
# Agent writes answer to /workspace/answer.json
# eval.sh runs oracle_checks.py and writes score
python3 /tests/oracle_checks.py --answer /workspace/answer.json --spec /tests/task_spec.json
echo "$SCORE" > /logs/verifier/reward.txt
python3 -c "import sys; sys.exit(0 if float('$SCORE') > 0 else 1)"
```

### Oracle Check Types

`scripts/csb_metrics/oracle_checks.py` provides 7 deterministic check functions:

| Check | Returns | Primary Score |
|-------|---------|---------------|
| `check_file_set_match` | `{recall, precision, f1, missing, extra}` | F1 score |
| `check_symbol_resolution` | `{matched, missing, extra, recall, precision}` | Recall |
| `check_dependency_chain` | `{matched_steps, order_correct, chain_recall}` | Chain recall |
| `check_provenance` | `{citations_found, citations_valid, provenance_score}` | Provenance score |
| `check_keyword_presence` | `{found, missing, keyword_recall}` | Keyword recall |
| `check_json_schema` | `{valid, errors}` | 1.0 if valid else 0.0 |
| `check_test_ratio` | `{passed, failed, total, ratio}` | Pass ratio |

**Composite score** = mean of primary scores across all configured checks.

No hardcoded thresholds — raw scores enable calibration. See
`docs/ORG_CALIBRATION.md` for threshold guidance after first runs.

### Agent Answer Format

Agents write `/workspace/answer.json`:

```json
{
  "files": [
    {"repo": "sg-evals/kubernetes-client-go", "path": "dynamic/scheme.go"}
  ],
  "symbols": [
    {"repo": "kubernetes/kubernetes", "path": "pkg/foo.go", "name": "Config"}
  ],
  "chain": [
    {"repo": "grafana/grafana", "path": "pkg/tsdb/loki/api.go", "symbol": "LokiAPI"},
    {"repo": "sg-evals/grafana-loki", "path": "pkg/loghttp/query.go", "symbol": "ParseInstantQuery"}
  ],
  "text": "The Config struct is defined at rest/config.go in kubernetes-client-go..."
}
```

### PRD-Centered Task Spec

Each task has `tests/task_spec.json` with explicit criteria:

```json
{
  "id": "CCX-dep-trace-001",
  "mcp_suite": "csb_org_crossrepo_tracing",
  "prd": {
    "user_story": "As an SRE, I need to find...",
    "seed_prompt": "Find all Go files in dynamic/ that import k8s.io/apimachinery/pkg/runtime"
  },
  "artifacts": {
    "oracle": {
      "required_files": [{"repo": "...", "path": "..."}]
    }
  },
  "evaluation": {
    "checks": [{"type": "file_set_match"}]
  }
}
```

## Running Tasks

### Config Pairing

Org tasks use the standard **direct** configs (same as SDLC):

- `baseline-local-direct` — full repos cloned locally
- `mcp-remote-direct` — local code truncated, agent uses Sourcegraph MCP tools

Some legacy runs used `baseline-local-artifact` + `mcp-remote-artifact` configs; these are handled by analysis scripts but are no longer the default. All Org tasks are registered in the unified `configs/selected_benchmark_tasks.json`.

### Full Starter Pack

```bash
# Both configs (baseline-local-direct + mcp-remote-direct)
configs/run_selected_tasks.sh --benchmark csb_org --parallel 8

# Dry run to preview
configs/run_selected_tasks.sh --benchmark csb_org --dry-run
```

### Category-Filtered Run

```bash
# Run only cross-repo tracing suite
configs/run_selected_tasks.sh --benchmark csb_org_crossrepo_tracing

# Run only onboarding suite
configs/run_selected_tasks.sh --benchmark csb_org_onboarding
```

### Monitoring

```bash
python3 scripts/aggregate_status.py --staging
```

### Generate Report

```bash
python3 scripts/generate_eval_report.py --runs-dir runs/staging
```

The report automatically includes an **MCP Retrieval Performance** section when
`retrieval_metrics.json` files are present.

## Retrieval Metrics

`scripts/csb_metrics/retrieval.py` extracts context retrieval KPIs from agent transcripts.

**Works for both configs**: counts oracle items found via any tool (local grep OR MCP).

```python
from scripts.csb_metrics.retrieval import extract_retrieval_metrics, load_oracle_items

oracle_items = load_oracle_items("tests/task_spec.json")
metrics = extract_retrieval_metrics(task_dir, oracle_items)
# Returns:
# {
#   "oracle_coverage": 0.75,         # fraction of oracle items found
#   "oracle_items_found": 6,
#   "oracle_items_total": 8,
#   "time_to_first_oracle_hit_ms": 3420.0,
#   "unique_repos_touched": 3,
#   "unique_orgs_touched": 2,
#   "mcp_tool_counts": {"keyword_search": 4, "read_file": 2},
#   "local_tool_counts": {"Grep": 1}
# }
```

**Key metric**: `oracle_coverage` measures how many oracle items the agent found.
Both configs have access to all repos; the comparison shows whether MCP tools
help agents discover cross-repo information more effectively.

## Deep Search Tasks

Four tasks are designed specifically for Deep Search synthesis:

| Task | Suite | Question Type |
|------|-------|--------------|
| `CCX-onboard-050-ds` | onboarding | End-to-end flow across 3 repos |
| `CCX-explore-042-ds` | onboarding | Data flow architecture map |
| `CCX-compliance-057-ds` | compliance | Compliance audit across monitoring stack |
| `CCX-explore-091-ds` | platform | Canonical deployment pattern discovery |

**Design principle**: DS variant instructions are open-ended synthesis questions
("Explain how X works end-to-end") rather than precise lookup queries. DS excels
at summarizing across many files where keyword_search + read_file would require
many sequential steps.

**Rubric judge**: DS tasks include `tests/criteria.json` with AAA criteria
(Accurate, Attributed, Actionable). Run hybrid scoring:

```bash
python3 scripts/run_judge.py --hybrid --task CCX-onboard-050-ds
```

Hybrid score = 0.6 × verifier_reward + 0.4 × rubric_score.

## Extending Categories

### Add a Task to an Existing Category

1. Add the use case to `configs/use_case_registry.json` if not present
2. Copy an existing task directory as a template (e.g., `ccx-dep-trace-001/`)
3. Update the Dockerfile to clone all required repos at pinned versions
4. Update `instruction.md`, `task_spec.json`, and `oracle_answer.json`
5. Verify with the validity gate
6. Add to `configs/selected_benchmark_tasks.json`

### Add a New Category (H, I)

1. Create the use case entries in `configs/use_case_registry.json`
   (set `oracle_type` from `"tbd"` to a real type)
2. Copy an existing task as a template, update Dockerfile with the required repos
3. The suite directory `benchmarks/csb_org_<suite>/` must be created manually
4. Add the suite prefix to `DIR_PREFIX_TO_SUITE` in:
   - `scripts/aggregate_status.py`
   - `scripts/generate_manifest.py`
   - `scripts/run_judge.py`

### Add sg-evals Mirrors for New Repos

If a required repo is not natively indexed in Sourcegraph, create a mirror:

```bash
# Shallow clone at stable tag, orphan commit, push to sg-evals
git clone --depth 1 --branch v1.0.0 https://github.com/org/repo /tmp/repo
cd /tmp/repo
git checkout --orphan orphan-v1.0.0
git add -A
git commit -m "Mirror: org/repo @ v1.0.0"
git remote add sg https://github.com/sg-evals/org-repo
git push sg orphan-v1.0.0:main --force
```

Wait for SG indexing (~hours), then verify:
```python
mcp__sourcegraph__keyword_search("repo:^github.com/sg-evals/org-repo$")
```

### Cross-Host (GitHub + GitLab) — Deferred

Cross-host support requires a multi-host Sourcegraph instance. The current
design uses cross-org (different GitHub orgs) instead. To add cross-host:

1. Create tasks with repos from multiple code hosts
2. Ensure SG instance indexes all hosts
3. Add `csb_org_crosshost` suite to `DIR_PREFIX_TO_SUITE` mappings

## Design Decisions

- **Q1**: Use sg-evals mirrors for 7 repos not natively indexed
- **Q2**: Focus on org-scale quantity (3-20 repos), structured oracle, customer-framed prompts
- **Q3**: Cross-org instead of cross-host (cross-host deferred until multi-host SG available)
- **Q4**: Closed-world exhaustive oracles via automated SG queries (no human curation)
- **Q5**: 10 per-category suites (csb_org_crossrepo_tracing, csb_org_security, etc.)
- **Q6**: Category I uses hybrid: test_ratio + context verification
- **Q7**: Deep Search-specific tasks as variants within suites (E and J families)
- **Q8**: No score thresholds initially — calibrate after first runs
- **Q9**: Unified selection file `configs/selected_benchmark_tasks.json` (370 tasks: 150 SDLC + 220 Org)
- **Q10**: Oracle coverage counts items found via any tool (baseline and MCP comparable)

## Dual-Mode Verification (Artifact + Direct)

Some Org tasks support both **artifact** and **direct** verification,
controlled by the `verification_modes` field in `configs/use_case_registry.json`.

### How it works

Each dual-mode task has a dispatcher `test.sh` that checks for the
`.artifact_only_mode` sentinel (set by `Dockerfile.artifact_only`):

- **Artifact mode** (sentinel present): dispatches to `eval.sh` which runs
  `oracle_checks.py` against `answer.json`.
- **Direct mode** (no sentinel): dispatches to `direct_verifier.sh` which
  checks code changes via git diffs, compilation, or test execution.

### File layout for dual-mode tasks

```
tests/
  test.sh                   # Dispatcher (checks sentinel, routes to eval.sh or direct_verifier.sh)
  eval.sh                   # Artifact verifier (oracle checks)
  direct_verifier.sh        # Direct verifier (adapted from parent SDLC task)
  oracle_checks.py          # Oracle library (artifact mode)
  oracle_answer.json        # Ground truth (artifact mode)
  ground_truth.json         # Direct mode ground truth (if applicable)
  verifier_lib.sh           # Shared verifier utilities (if applicable)
```

### Which tasks support direct mode

Tasks with SDLC lineage (adapted from code-change tasks) and agentic
code-generation tasks support both modes. Discovery-only tasks remain
artifact-only since they produce no code changes to verify.

See `configs/use_case_registry.json` — entries with
`"verification_modes": ["artifact", "direct"]` support both modes.

### Adding direct mode to a new task

1. Set `"verification_modes": ["artifact", "direct"]` in the registry entry.
2. Ensure the fixture has `local_checkout_repos` (direct mode needs full repo).
3. Run `generate_mcp_unique_tasks.py` — creates `direct_verifier.sh` placeholder.
4. Run `customize_mcp_skeletons.py` — generates dual-mode `test.sh` and copies
   parent verifier if the task has SDLC lineage.
5. Manually curate `direct_verifier.sh` for task-specific verification logic.

## See Also

- `docs/ORG_CALIBRATION.md` — Static oracle analysis + threshold calibration
- `docs/CONFIGS.md` — Run configs including `--selection-file` and `--use-case-category`
- `docs/SCORING_SEMANTICS.md` — Oracle check scoring and hybrid rubric scoring
- `docs/EXTENSIBILITY.md` — Adding new suites and tasks
- `ralph-mcp-unique/prd.json` — Full PRD with 23 user stories
- `ralph-mcp-unique/progress.txt` — Implementation log
