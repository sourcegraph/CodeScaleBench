# Task: Debug Query Plan Regression in TiDB Cost-Based Optimizer

## Background
A user reports that after upgrading TiDB, a query that previously used an index scan is now doing a full table scan. The query involves a JOIN between two tables with a WHERE clause on an indexed column.

## Objective
Investigate the cost model in TiDB's query optimizer to identify which component could cause a plan regression where an IndexScan is replaced by a TableFullScan.

## Steps
1. Find the cost model implementation in `pkg/planner/core/` that computes the cost of IndexScan vs TableFullScan
2. Identify the `Stats` struct and how row count estimates feed into the cost calculation
3. Locate where the optimizer compares candidate plans and selects the cheapest
4. Create a file `debug_report.md` in `/workspace/` documenting:
   - The file paths and functions responsible for cost calculation of IndexScan
   - The file paths and functions responsible for cost calculation of TableFullScan
   - The comparison logic that picks the final plan
   - A hypothesis for what parameter change could cause the regression

## Key Reference Files
- `pkg/planner/core/` — optimizer core
- `pkg/planner/cardinality/` — cardinality estimation
- `pkg/statistics/` — statistics framework

## Success Criteria
- debug_report.md exists and contains the relevant file paths
- Report identifies cost model functions for both scan types
- Report includes a plausible regression hypothesis
