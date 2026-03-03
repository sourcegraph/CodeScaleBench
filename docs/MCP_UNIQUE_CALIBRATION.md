# CodeScaleBench-Org Benchmark: Calibration Data

This document records calibration data for the Org starter pack (12 tasks).
It tracks static oracle coverage analysis and actual run results.

## Purpose

The Org tasks are designed so that the baseline agent (local code only)
**cannot** reach the oracle items. This document:
1. Shows expected coverage gaps derived from static fixture analysis
2. Records actual run results once benchmark runs complete
3. Enables threshold calibration for recall/precision scoring

## Task Inventory

| Task ID | Suite | Fixture | Difficulty | Deep Search |
|---------|-------|---------|------------|-------------|
| CCX-dep-trace-001 | csb_org_crossrepo_tracing | kubernetes-ecosystem | medium | No |
| CCX-dep-trace-004 | csb_org_crossrepo_tracing | grafana-observability | hard | No |
| CCX-config-trace-010 | csb_org_crossrepo_tracing | kubernetes-ecosystem | medium | No |
| CCX-vuln-remed-011 | csb_org_security | nodejs-web-stack | medium | No |
| CCX-vuln-remed-014 | csb_org_security | grafana-observability | hard | No |
| CCX-incident-031 | csb_org_incident | multi-org-go | hard | No |
| CCX-onboard-041 | csb_org_onboarding | python-ml-stack | medium | No |
| CCX-onboard-050-ds | csb_org_onboarding | kubernetes-ecosystem | hard | Yes |
| CCX-explore-042-ds | csb_org_onboarding | python-ml-stack | hard | Yes |
| CCX-crossorg-061 | csb_org_crossorg | multi-org-go | hard | No |
| CCX-crossorg-066 | csb_org_crossorg | multi-org-go | medium | No |
| CCX-explore-091-ds | csb_org_platform | kubernetes-ecosystem | hard | Yes |

## Static Oracle Coverage Analysis

This analysis derives expected oracle coverage from fixture access modes.
**Expected baseline coverage** = oracle items in local_checkout repos / total oracle items.
**Expected MCP-Full coverage** = 100% (all oracle items are in repos indexed in Sourcegraph).

### Per-Task Analysis

| Task ID | Oracle Type | Total Items | Items in Local | Expected Baseline % | Expected MCP-Full % |
|---------|------------|-------------|----------------|---------------------|---------------------|
| CCX-dep-trace-001 | file_set_match | 8 | 0 | 0% | ~100% |
| CCX-dep-trace-004 | dependency_chain | 2 | 1 | 50% | ~100% |
| CCX-config-trace-010 | symbol_resolution | 1 | 0 | 0% | ~100% |
| CCX-vuln-remed-011 | file_set_match | 1 | 0 | 0% | ~100% |
| CCX-vuln-remed-014 | file_set_match | 1 | 0 | 0% | ~100% |
| CCX-incident-031 | file_set_match | 2 | 0 | 0% | ~100% |
| CCX-onboard-041 | file_set_match | 4 | 0 | 0% | ~100% |
| CCX-onboard-050-ds | dependency_chain | 3 | 1 | 33% | ~100% |
| CCX-explore-042-ds | dependency_chain | 3 | 0 | 0% | ~100% |
| CCX-crossorg-061 | symbol_resolution | 2 | 1 | 50% | ~100% |
| CCX-crossorg-066 | keyword_presence + provenance | 1 | 0 | 0% | ~100% |
| CCX-explore-091-ds | file_set_match | 3 | 0 | 0% | ~100% |

**Key finding:** 10 of 12 tasks have 0% expected baseline oracle coverage.
The remaining 2 tasks (CCX-dep-trace-004 at 50%, CCX-crossorg-061 at 50%)
have partial local coverage but cannot complete without MCP.

### Decoy Pattern Tasks (3 tasks)

Three tasks deliberately include vendored copies in the local repo to test precision:

- **CCX-crossorg-066**: `kubernetes/kubernetes` has `vendor/go.etcd.io/etcd/client/v3/` — the
  vendored copy looks like the oracle but is not authoritative. Correct answer cites `etcd-io/etcd`
  which requires MCP.

- **CCX-config-trace-010**: `kubernetes/kubernetes` has `staging/src/k8s.io/client-go/rest/` —
  vendored copy of the oracle. Correct answer cites `sg-evals/kubernetes-client-go`.

- **CCX-incident-031**: `kubernetes/kubernetes` has `vendor/go.etcd.io/etcd/server/v3/storage/mvcc/` —
  vendored copy. Correct answer cites `etcd-io/etcd`.

These tasks test whether the agent correctly distinguishes the authoritative source from copies,
which is a key use case for MCP (the authoritative source is in an MCP-only repo).

## Pre-run Validation Status

Run date: 2026-02-20

### Validity Gate (oracle_checks.py)
```
All 12/12 tasks: VALID
  Gold answer score: 1.0 (all tasks)
  Empty answer score: 0.0 (all tasks)
```

### Preflight Validation (validate_tasks_preflight.py)
```
csb_org_* tasks: 0 CRITICAL, 0 WARNING
Note: 3 warnings from pre-existing non-csb_org tasks (not related)
```

### Infra Readiness (check_infra.py)
```
OAuth tokens: 3/3 valid
Docker: running
Harbor CLI: available
Disk: 290GB free
```

## Running the Benchmark

### Launch both configs (baseline + MCP-Full)
```bash
# Full starter pack — both configs (all Org tasks)
configs/run_selected_tasks.sh --benchmark csb_org --parallel 8

# Suite-specific run
configs/run_selected_tasks.sh --benchmark csb_org_crossrepo_tracing --parallel 4

# Single task test
configs/run_selected_tasks.sh --task ccx-onboard-041
```

### Monitor progress
```bash
python3 scripts/aggregate_status.py --staging
```

### Extract retrieval metrics after runs complete
```bash
for task_dir in runs/staging/*/sourcegraph_full/*/; do
  python3 scripts/csb_metrics/retrieval.py \
    --task-dir "$task_dir" \
    --task-spec benchmarks/csb_org_*/${task_dir##*/}/tests/task_spec.json \
    --output "$task_dir/retrieval_metrics.json"
done
```

### Generate report
```bash
python3 scripts/generate_eval_report.py
```

## Actual Run Results

*This section will be populated after benchmark runs complete.*

### Reward Scores

| Task ID | Baseline Reward | MCP-Full Reward | Delta |
|---------|-----------------|-----------------|-------|
| CCX-dep-trace-001 | TBD | TBD | TBD |
| CCX-dep-trace-004 | TBD | TBD | TBD |
| CCX-config-trace-010 | TBD | TBD | TBD |
| CCX-vuln-remed-011 | TBD | TBD | TBD |
| CCX-vuln-remed-014 | TBD | TBD | TBD |
| CCX-incident-031 | TBD | TBD | TBD |
| CCX-onboard-041 | TBD | TBD | TBD |
| CCX-onboard-050-ds | TBD | TBD | TBD |
| CCX-explore-042-ds | TBD | TBD | TBD |
| CCX-crossorg-061 | TBD | TBD | TBD |
| CCX-crossorg-066 | TBD | TBD | TBD |
| CCX-explore-091-ds | TBD | TBD | TBD |

### Retrieval Metrics

| Task ID | Baseline Oracle Coverage | MCP-Full Oracle Coverage | BL Repos Touched | MCP Repos Touched |
|---------|--------------------------|--------------------------|------------------|-------------------|
| CCX-dep-trace-001 | TBD | TBD | TBD | TBD |
| CCX-dep-trace-004 | TBD | TBD | TBD | TBD |
| CCX-config-trace-010 | TBD | TBD | TBD | TBD |
| CCX-vuln-remed-011 | TBD | TBD | TBD | TBD |
| CCX-vuln-remed-014 | TBD | TBD | TBD | TBD |
| CCX-incident-031 | TBD | TBD | TBD | TBD |
| CCX-onboard-041 | TBD | TBD | TBD | TBD |
| CCX-onboard-050-ds | TBD | TBD | TBD | TBD |
| CCX-explore-042-ds | TBD | TBD | TBD | TBD |
| CCX-crossorg-061 | TBD | TBD | TBD | TBD |
| CCX-crossorg-066 | TBD | TBD | TBD | TBD |
| CCX-explore-091-ds | TBD | TBD | TBD | TBD |

## Threshold Calibration

*To be set after actual run data is collected.*

### Proposed Threshold Approach

Based on static analysis, the following oracle coverage thresholds are proposed
as a starting point for calibration. Actual results may require adjustment.

| Metric | Proposed Pass Threshold | Rationale |
|--------|------------------------|-----------|
| oracle_coverage (file_set_match) | 0.5 | Agent should find at least half the oracle files |
| oracle_coverage (symbol_resolution) | 0.5 | At least 1 of 2 symbols |
| chain_recall (dependency_chain) | 0.5 | At least half the chain steps |
| unique_orgs_touched | >= 2 (cross-org tasks) | Must touch multiple GitHub orgs |

### Expected MCP Advantage (derived from static analysis)

Predicted mean oracle_coverage delta (MCP-Full vs baseline) per category:

| Category | Expected BL Coverage | Expected MCP Coverage | Expected Delta |
|----------|----------------------|-----------------------|----------------|
| A (cross-repo tracing) | ~17% | ~100% | +83pp |
| B (security) | 0% | ~100% | +100pp |
| D (incident) | 0% | ~100% | +100pp |
| E (onboarding) | ~11% | ~100% | +89pp |
| G (cross-org) | ~25% | ~100% | +75pp |
| J (platform) | 0% | ~100% | +100pp |

Note: These are theoretical upper bounds for MCP-Full. Actual agent performance
will depend on task complexity, LLM capability, and tool usage patterns.

## Notes for Follow-up

1. **Threshold calibration**: After first run, set recall/precision thresholds in
   task_spec.json based on actual MCP-Full scores. Target: threshold = 0.7 × median
   MCP-Full score (leaves room for model variation while excluding total failures).

2. **Deep Search tasks**: CCX-onboard-050-ds, CCX-explore-042-ds, CCX-explore-091-ds
   are designed to benefit from Deep Search synthesis. Compare DS vs keyword_search
   quality using the rubric judge criteria.json scores.

3. **Decoy precision**: For CCX-crossorg-066, CCX-config-trace-010, CCX-incident-031,
   measure how often baseline agents cite vendored copies as authoritative (false
   precision). This is a key differentiating signal.

4. **LLM grader for hybrid tasks**: Run `python3 scripts/run_judge.py --hybrid` on
   E and J Deep Search tasks after results are available.
