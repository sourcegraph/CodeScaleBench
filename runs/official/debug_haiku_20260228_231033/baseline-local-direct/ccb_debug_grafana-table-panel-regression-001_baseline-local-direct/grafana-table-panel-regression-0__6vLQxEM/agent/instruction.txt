# Investigation: Dashboard Migration v38 Table Panel Regression

**Repository:** grafana/grafana
**Task Type:** Regression Hunt (investigation only — no code fixes)

## Scenario

After upgrading Grafana from v10.3 to v10.4, some dashboards with table panels fail to render correctly. The table panel's field override configuration is silently dropped during dashboard import. Users see tables with missing column formatting (column widths, text alignment, cell display modes).

The bug only affects dashboards where `fieldConfig.defaults.custom` was not explicitly set in the saved dashboard JSON. Dashboards with explicit custom config render correctly.

## Your Task

Investigate the root cause and produce a report at `/logs/agent/investigation.md`.

Your report MUST cover:
1. Which migration function is responsible for the regression
2. The exact conditional logic that fails for dashboards without explicit `defaults.custom`
3. Why dashboards with explicit `defaults.custom` are unaffected
4. Which dashboard schema version triggers the issue
5. The files and functions involved in the migration chain

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding>

## Root Cause
<Specific file, function, and mechanism>

## Evidence
<Code references with file paths and line numbers>

## Affected Components
<List of packages/modules impacted>

## Recommendation
<Fix strategy>
```

## Constraints

- Do NOT write any code fixes
- Do NOT modify any source files
- Your job is investigation and analysis only
- Focus on the dashboard migration pipeline, particularly schema version handlers
