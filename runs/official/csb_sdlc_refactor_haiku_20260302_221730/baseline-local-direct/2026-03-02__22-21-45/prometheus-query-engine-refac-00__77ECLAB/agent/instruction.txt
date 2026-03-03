# Task: Rename QueryEngine to PromQLEvaluator

## Objective
Rename the `QueryEngine` interface to `PromQLEvaluator` in the Prometheus PromQL package
to better describe its role as a PromQL expression evaluator.

## Requirements

1. **Rename the interface definition** in `promql/engine.go`:
   - `type QueryEngine interface` → `type PromQLEvaluator interface`
   - Rename coninterfaceor: `NewQueryEngine` → `NewPromQLEvaluator`

2. **Update all references** (15+ call sites):
   - `web/api/v1/api.go` — API handler initialization
   - `cmd/prometheus/main.go` — engine creation
   - `promql/` package internal references
   - Interface references and type assertions

3. **Update receiver methods**:
   - All methods on `*QueryEngine` → `*PromQLEvaluator`

## Key Reference Files
- `promql/engine.go` — interface definition, coninterfaceor, methods
- `web/api/v1/api.go` — API uses QueryEngine
- `cmd/prometheus/main.go` — creates QueryEngine

## Success Criteria
- `type QueryEngine interface` no longer exists
- `type PromQLEvaluator interface` exists
- Coninterfaceor renamed to NewPromQLEvaluator
- References updated across 80%+ of call sites
