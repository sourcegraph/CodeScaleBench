# Fix Plan Renderer Crash on Null-to-Unknown Attribute Update

**Repository:** hashicorp/terraform
**Difficulty:** MEDIUM
**Category:** cross_module_bug_fix

## Description

Terraform's plan renderer crashes when displaying a resource update where a computed attribute transitions from `null` to `(known after apply)`. The crash occurs because the renderer in `unknown.go` assumes that if the action is not `plans.Create`, the `renderer.before.Renderer` field is always non-nil. However, a provider can return `null` for a computed attribute on the current state and then declare it will recompute the attribute as part of the update. In this case, `before.Renderer` is nil even though the action is `plans.Update`, causing a nil pointer dereference.

A second related issue is in `block.go`, where unknown blocks during an update are always rendered with `plans.Create` instead of passing through the actual `diff.Action`. This causes the plan output to show `+` (create) markers instead of `~` (update) markers for recomputed blocks.

## Task

Changes:
- 4 files modified (block.go, unknown.go, renderer_test.go, plan_test.go)
- 22 additions, 10 deletions

Tasks:
1. Fix `unknown.go` to handle nil `renderer.before.Renderer` by treating it the same as a Create action
2. Fix `block.go` to pass `diff.Action` instead of hardcoded `plans.Create` when rendering unknown blocks (3 locations)
3. Add `computed_update_from_null` test case in `renderer_test.go`
4. Update expected output in `plan_test.go` from `+` to `~` for unknown blocks during updates (6 locations)

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 4 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes
**Estimated Context:** 6000 tokens
