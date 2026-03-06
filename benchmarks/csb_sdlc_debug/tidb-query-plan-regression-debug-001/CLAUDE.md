# tidb-query-plan-regression-debug-001

## Task Type: Debug (Query Plan Regression)
Investigate TiDB cost-based optimizer for plan regression root cause.

## Key Directories
- pkg/planner/core/ — optimizer, plan generation
- pkg/planner/cardinality/ — row count estimation
- pkg/statistics/ — stats collection and caching
