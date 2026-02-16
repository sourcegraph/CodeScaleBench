# Investigation: Prometheus Scrape Config Hot Reload Regression

**Repository:** prometheus/prometheus
**Task Type:** Regression Hunt (investigation only — no code fixes)

## Scenario

After upgrading Prometheus from v2.54 to v3.0, users report that hot-reloading the configuration (via SIGHUP or `/-/reload` endpoint) no longer applies changes to the `always_scrape_classic_histograms` and `convert_classic_histograms_to_nhcb` scrape configuration options. These settings work correctly on initial startup but are ignored during config reload.

The symptom: operators change these histogram-related configs in `prometheus.yml` and trigger a reload, but scrape targets continue using the old histogram behavior. Restarting Prometheus entirely makes the new config take effect.

The bug was introduced sometime between the 2.x and 3.0 release cycles, likely during refactoring of the scrape pool configuration system or the native histogram feature development.

## Your Task

Use commit history search to find when and why this regression was introduced. Produce a report at `/logs/agent/investigation.md`.

Your report MUST cover:
1. **The regressing commit SHA** — which specific commit introduced the bug
2. **The changed function(s)** — what code change broke hot reload for these configs
3. **The mechanism** — why do these configs work on startup but not during reload?
4. **The affected code paths** — which functions handle initial startup vs. reload differently?
5. **Evidence from commit history** — what PR/issue context explains the regression?

## Hints

- The bug affects `scrape_configs[].always_scrape_classic_histograms` and `scrape_configs[].convert_classic_histograms_to_nhcb`
- The configs ARE applied during `scrapePool.sync()` (startup path)
- The configs are NOT applied during `scrapePool.restartLoops()` (reload path)
- The regression was fixed in PR #15489 (commit e10bbf0a84d59a9f20144ed578c9afa7079dbacd) — work backward from there
- Key files to investigate: `scrape/manager.go`, `scrape/scrape.go`, `config/config.go`

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding with regressing commit SHA>

## Root Cause
<Specific commit, file, function, and mechanism>

## Evidence
<Code references and commit history showing when/why the regression was introduced>

## Affected Components
<List of packages/modules/functions impacted>

## Recommendation
<Fix strategy — how was it eventually fixed?>
```

## Constraints

- Do NOT write any code fixes
- Do NOT modify any source files
- Your job is investigation and analysis only
- Focus on using commit search, diff search, and blame to find the regressing commit
- The fix commit is e10bbf0a84 — you must find the commit that INTRODUCED the bug
