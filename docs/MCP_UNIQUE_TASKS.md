# MCP-Unique / Org-Scale Context Retrieval Tasks

This document covers the MCP-unique benchmark extension — tasks that measure what
local-only agents *cannot* do: cross-repo discovery, symbol resolution, dependency
tracing, and deep-search-driven investigation in polyrepo environments.

## Overview

Traditional CCB tasks give the agent full local code access. MCP-unique tasks
deliberately restrict the baseline agent to **one local repo** while placing all
oracle-relevant files in **MCP-only repos** — repos that only Sourcegraph can reach.

This creates a clean measurement of MCP's *unique capability*:

```
Baseline agent:  local_checkout_repo only
                 → can find items in 1 repo
                 → oracle coverage ≈ 0-50%

MCP-Full agent:  local_checkout_repo + Sourcegraph MCP (5-20 repos)
                 → can find items across all repos
                 → oracle coverage ≈ 100%
```

**Key differentiators vs existing cross-repo tasks:**
- **Org-scale quantity**: 3-20 repos per task (vs 2 in old CrossRepo suite)
- **Closed-world oracle**: exhaustive oracle files/symbols auto-curated via SG queries
- **Customer-framed prompts**: from 100 GTM use cases grounded in real customer pain
- **Cross-org scope**: repos from different GitHub organizations
- **Deep Search variants**: tasks that specifically benefit from DS synthesis

## Architecture

```
┌────────────────────────────────────────────────────────────┐
│                  MCP-Unique Task System                     │
│                                                             │
│  configs/use_case_registry.json        (100 use cases)     │
│         │                                                   │
│         ▼                                                   │
│  fixtures/repo_sets/*.json             (polyrepo fixtures)  │
│         │                                                   │
│         ▼                                                   │
│  scripts/generate_mcp_unique_tasks.py  (task generator)    │
│         │                                                   │
│         ▼                                                   │
│  benchmarks/ccb_mcp_<suite>/<task>/                        │
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
│  scripts/ccb_metrics/retrieval.py      (KPI extractor)     │
│  scripts/curate_oracle.py              (oracle auto-curator)│
│  scripts/validate_mcp_task_instance.py (validity gate)     │
└────────────────────────────────────────────────────────────┘
```

## Suite Structure

Ten suites map to use case categories A-J:

| Suite | Category | Description | Tasks |
|-------|----------|-------------|-------|
| `ccb_mcp_crossrepo_tracing` | A | Cross-repo dependency tracing + symbol resolution | 3 |
| `ccb_mcp_security` | B | Vulnerability + security remediation at scale | 2 |
| `ccb_mcp_migration` | C | Framework upgrades across repos | 0 |
| `ccb_mcp_incident` | D | On-call / incident debugging across microservices | 1 |
| `ccb_mcp_onboarding` | E | Architecture comprehension + API discovery | 5 |
| `ccb_mcp_compliance` | F | Compliance / audit / provenance | 0 |
| `ccb_mcp_crossorg` | G | Cross-org discovery (repos from different GitHub orgs) | 2 |
| `ccb_mcp_domain` | H | Domain-specific lineage (deferred) | 0 |
| `ccb_mcp_org` | I | Agentic coding correctness using org-wide context | 0 |
| `ccb_mcp_platform` | J | Platform / DevTools / tribal knowledge | 1 |

**Current starter pack: 14 tasks across 6 active suites.** See
`configs/selected_mcp_unique_tasks.json` for the canonical list.

## Repo-Set Fixtures

Each task uses a **repo-set fixture** defining which repos are local vs MCP-only:

| Fixture | Local Repo | MCP-Only Repos | Cross-Org |
|---------|-----------|----------------|-----------|
| `kubernetes-ecosystem` | kubernetes/kubernetes | kubernetes-client-go, kubernetes-api, etcd-io/etcd | Yes |
| `nodejs-web-stack` | nodejs/node | expressjs-express, lodash, prisma-prisma | Yes |
| `python-ml-stack` | scikit-learn/scikit-learn | numpy, pandas-dev/pandas, scipy | Yes |
| `grafana-observability` | grafana/grafana | grafana-loki, grafana-mimir | No |
| `multi-org-go` | kubernetes/kubernetes | etcd-io/etcd, grafana/grafana | Yes |

Fixtures are in `fixtures/repo_sets/*.json` and validate against
`schemas/repo_set_fixture.schema.json`. SG mirror repos (`sg-benchmarks/*`)
are tracked in `configs/sg_mirror_revisions.json`.

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

The generator reads `configs/use_case_registry.json` and `fixtures/repo_sets/`
to fill `templates/mcp_unique_task/*.j2` templates.

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
This creates `benchmarks/ccb_mcp_crossrepo_tracing/ccx-dep-trace-001/` with all
files from the template.

**Step 3: Curate the oracle using Sourcegraph MCP**
```bash
python3 scripts/curate_oracle.py \
  --task-dir benchmarks/ccb_mcp_crossrepo_tracing/ccx-dep-trace-001 \
  --verbose
```
The curator uses `mcp__sourcegraph__keyword_search` and `mcp__sourcegraph__find_references`
to discover all files matching the task's `seed_prompt`. It writes:
- `tests/oracle_answer.json`: the gold answer (what a perfect agent would output)
- `tests/oracle_curation_log.json`: the full trace of SG queries

**Step 4: Validate the oracle (fail2pass gate)**
```bash
python3 scripts/validate_mcp_task_instance.py \
  --task-dir benchmarks/ccb_mcp_crossrepo_tracing/ccx-dep-trace-001 \
  --verbose
```
Expected: `ccx-dep-trace-001: VALID` (gold=1.0, empty=0.0)

**Step 5: Register in selection file**
Add an entry to `configs/selected_mcp_unique_tasks.json`.

**Step 6: Run preflight**
```bash
python3 scripts/validate_tasks_preflight.py --suite ccb_mcp_crossrepo_tracing
```

### Manual Oracle Authoring

For tasks where automated curation misses items:

1. Search Sourcegraph using `mcp__sourcegraph__keyword_search` with the task's
   target pattern
2. Verify file paths are real with `mcp__sourcegraph__read_file`
3. Edit `tests/oracle_answer.json` directly:
   ```json
   {
     "files": [{"repo": "sg-benchmarks/kubernetes-client-go", "path": "dynamic/scheme.go"}],
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

`scripts/ccb_metrics/oracle_checks.py` provides 7 deterministic check functions:

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
`docs/MCP_UNIQUE_CALIBRATION.md` for threshold guidance after first runs.

### Agent Answer Format

Agents write `/workspace/answer.json`:

```json
{
  "files": [
    {"repo": "sg-benchmarks/kubernetes-client-go", "path": "dynamic/scheme.go"}
  ],
  "symbols": [
    {"repo": "kubernetes/kubernetes", "path": "pkg/foo.go", "name": "Config"}
  ],
  "chain": [
    {"repo": "grafana/grafana", "path": "pkg/tsdb/loki/api.go", "symbol": "LokiAPI"},
    {"repo": "sg-benchmarks/grafana-loki", "path": "pkg/loghttp/query.go", "symbol": "ParseInstantQuery"}
  ],
  "text": "The Config struct is defined at rest/config.go in kubernetes-client-go..."
}
```

### PRD-Centered Task Spec

Each task has `tests/task_spec.json` with explicit criteria:

```json
{
  "id": "CCX-dep-trace-001",
  "mcp_suite": "ccb_mcp_crossrepo_tracing",
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

### Full Starter Pack

```bash
# Both configs (baseline + MCP-Full)
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json \
  --parallel 8

# Dry run to preview
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json \
  --dry-run
```

### Category-Filtered Run

```bash
# Run only Category A (cross-repo tracing)
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json \
  --use-case-category A

# Run only Category E (onboarding) with Deep Search tasks
configs/run_selected_tasks.sh \
  --selection-file configs/selected_mcp_unique_tasks.json \
  --use-case-category E
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

`scripts/ccb_metrics/retrieval.py` extracts context retrieval KPIs from agent transcripts.

**Works for both configs**: counts oracle items found via any tool (local grep OR MCP).

```python
from scripts.ccb_metrics.retrieval import extract_retrieval_metrics, load_oracle_items

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

**Key metric**: `oracle_coverage` of `mcp_only` repos shows MCP's unique value.
Baseline agents score near 0% on MCP-only repos; MCP-Full agents score near 100%.

## Deep Search Tasks

Three tasks are designed specifically for Deep Search synthesis:

| Task | Suite | Question Type |
|------|-------|--------------|
| `CCX-onboard-050-ds` | onboarding | End-to-end flow across 3 repos |
| `CCX-explore-042-ds` | onboarding | Data flow architecture map |
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
2. Ensure a repo-set fixture exists in `fixtures/repo_sets/`
3. Run the generator:
   ```bash
   python3 scripts/generate_mcp_unique_tasks.py --use-case-ids <N> --curate-oracle --validate
   ```
4. Verify with the validity gate
5. Add to `configs/selected_mcp_unique_tasks.json`

### Add a New Category (C, F, G, H, I, J)

1. Create the use case entries in `configs/use_case_registry.json`
   (set `oracle_type` from `"tbd"` to a real type)
2. Create or reuse a repo-set fixture
3. The suite directory `benchmarks/ccb_mcp_<suite>/` is created automatically
   by the generator
4. Add the suite prefix to `DIR_PREFIX_TO_SUITE` in:
   - `scripts/aggregate_status.py`
   - `scripts/generate_manifest.py`
   - `scripts/run_judge.py`

### Add sg-benchmarks Mirrors for New Repos

If a required repo is not natively indexed in Sourcegraph, create a mirror:

```bash
# Shallow clone at stable tag, orphan commit, push to sg-benchmarks
git clone --depth 1 --branch v1.0.0 https://github.com/org/repo /tmp/repo
cd /tmp/repo
git checkout --orphan orphan-v1.0.0
git add -A
git commit -m "Mirror: org/repo @ v1.0.0"
git remote add sg https://github.com/sg-benchmarks/org-repo
git push sg orphan-v1.0.0:main --force
```

Wait for SG indexing (~hours), then verify:
```python
mcp__sourcegraph__keyword_search("repo:^github.com/sg-benchmarks/org-repo$")
```

Record the SHA in `configs/sg_mirror_revisions.json`.

### Cross-Host (GitHub + GitLab) — Deferred

Cross-host support requires a multi-host Sourcegraph instance. The current
design uses `cross_org` (different GitHub orgs) instead. To add cross-host:

1. Add `host` field to repo objects in fixtures (currently only `github.com`)
2. Update fixture schema `schemas/repo_set_fixture.schema.json`
3. Add cross_host suite `ccb_mcp_crosshost` to `suiteMapping` in the PRD
4. Ensure SG instance indexes the new host

## Design Decisions

These decisions are recorded in `ralph-mcp-unique/prd.json` under `designDecisions`:

- **Q1**: Use sg-benchmarks mirrors for 7 repos not natively indexed
- **Q2**: Focus on org-scale quantity (3-20 repos), structured oracle, customer-framed prompts
- **Q3**: Cross-org instead of cross-host (cross-host deferred until multi-host SG available)
- **Q4**: Closed-world exhaustive oracles via automated SG queries (no human curation)
- **Q5**: 10 per-category suites (ccb_mcp_crossrepo_tracing, ccb_mcp_security, etc.)
- **Q6**: Category I uses hybrid: test_ratio + context verification
- **Q7**: Deep Search-specific tasks as variants within suites (E and J families)
- **Q8**: No score thresholds initially — calibrate after first runs
- **Q9**: Separate selection file `configs/selected_mcp_unique_tasks.json`
- **Q10**: Oracle coverage counts items found via any tool (baseline and MCP comparable)

## See Also

- `docs/MCP_UNIQUE_CALIBRATION.md` — Static oracle analysis + threshold calibration
- `docs/CONFIGS.md` — Run configs including `--selection-file` and `--use-case-category`
- `docs/SCORING_SEMANTICS.md` — Oracle check scoring and hybrid rubric scoring
- `docs/EXTENSIBILITY.md` — Adding new suites and tasks
- `ralph-mcp-unique/prd.json` — Full PRD with 23 user stories
- `ralph-mcp-unique/progress.txt` — Implementation log
