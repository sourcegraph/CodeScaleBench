# Task: Implement CompactDiffFormatter for Terraform

## Objective
Create a `CompactDiffFormatter` in `internal/command/format/` that produces a condensed,
summary-style diff output for `terraform plan`, showing only resource-level changes
without attribute-level detail.

## Requirements

1. **Create `internal/command/format/compact.go`** with:
   - `CompactDiffFormatter` struct implementing a plan formatter
   - `Format(plan *plans.Plan, schemas *terraform.Schemas)` method returning string
   - Outputs one line per resource change: `[action] resource_type.name`
   - Groups changes by action type (create/update/delete/replace)
   - Shows summary counts at the end

2. **Create `internal/command/format/compact_test.go`** with tests

3. **Follow Terraform patterns**:
   - Study the existing `DiffFormatter` in the format package
   - Use `plans.Action` constants (Create, Update, Delete, etc.)
   - Use `addrs.AbsResourceInstance` for resource addressing

## Key Reference Files
- `internal/command/format/diff.go` — existing diff formatter
- `internal/command/format/state.go` — state formatter pattern
- `internal/plans/changes.go` — plan change types
- `internal/plans/plan.go` — Plan struct definition
- `internal/addrs/resource.go` — resource addressing

## Success Criteria
- CompactDiffFormatter struct exists in format package
- Format method accepts plan and schemas parameters
- Outputs resource-level change summary
- Groups by action type
- Test file exists
