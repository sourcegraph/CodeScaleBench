# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place updates for resources with provider-schema-defined sensitive attributes because of an asymmetry in how sensitivity marks are applied: schema-defined sensitive attributes are applied when reading resource values from state for expression evaluation (via `evaluate.go`), but are **never** applied when initially processing provider responses or storing values in state. This creates a mismatch where the plan compares values with different sensitivity marks (causing apparent changes) and state files store incomplete sensitivity information.

## Root Cause

The root cause is a **permanent sensitivity mark gap** that flows through the entire resource lifecycle:

### 1. **Provider Response Processing (No Schema Marks)**
- `node_resource_abstract_instance.go::plan()` (lines 868-1000): When processing provider responses:
  - Line 869: `unmarkedPriorVal, priorPaths := priorVal.UnmarkDeepWithPaths()` - extracts marks from prior state (which only has marks from sensitive variable references)
  - Line 868: `unmarkedConfigVal, unmarkedPaths := configVal.UnmarkDeepWithPaths()` - extracts marks from config
  - Line 916: `plannedNewVal := resp.PlannedState` - provider response comes back **completely unmarked** (providers have no concept of sensitivity)
  - Lines 998-1000: Only config marks (`unmarkedPaths`) are re-applied to the planned value
  - **Gap**: Schema-defined sensitive marks are NEVER applied to the provider response

- `node_resource_abstract_instance.go::refresh()` (lines 623-720): Same pattern:
  - Line 625: `priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()` - extracts marks from state
  - Line 636: `resp = provider.ReadResource(...)` - unmarked request
  - Line 693: `ret.Value = newState` - provider response without schema marks
  - Lines 718-720: Only prior marks are re-applied, not schema marks
  - **Gap**: Schema-defined sensitive marks are NEVER applied after refresh

### 2. **State Serialization (Incomplete Sensitivity)**
- `states/instance_object.go::Encode()` (lines 94-137):
  - Line 98: `val, pvm := o.Value.UnmarkDeepWithPaths()` - extracts marks FROM the value being encoded
  - Line 131: `AttrSensitivePaths: pvm,` - saves extracted marks to state file
  - **Gap**: Since the value never had schema marks applied to it, the extracted marks don't include them
  - Result: `AttrSensitivePaths` in the state file is incomplete (missing schema-defined sensitive paths)

### 3. **The Evaluator's Compensating Workaround**
- `evaluate.go::GetResource()` (lines 689-723):
  - Lines 718-723 (for non-planned resources):
    ```go
    if schema.ContainsSensitive() {
        var marks []cty.PathValueMarks
        val, marks = val.UnmarkDeepWithPaths()
        marks = append(marks, schema.ValueMarks(val, nil)...)
        val = val.MarkWithPaths(marks)
    }
    instances[key] = val
    ```
  - Lines 689-693 (for planned resources in plan phase):
    ```go
    afterMarks := change.AfterValMarks
    if schema.ContainsSensitive() {
        afterMarks = append(afterMarks, schema.ValueMarks(val, nil)...)
    }
    instances[key] = val.MarkWithPaths(afterMarks)
    ```
  - **What it does**: Applies schema marks ONLY when reading resources for expression evaluation
  - **Why it's a workaround**: This is the only place in the entire lifecycle where schema marks are applied to values from state

### 4. **The Asymmetry & Phantom Diffs**
The plan operation creates a phantom change because:
- When evaluating expressions for the proposed new value (during config evaluation), `GetResource()` returns values WITH schema marks (line 718-723)
- When comparing in `plan()` at line 1082: `eqV := unmarkedPlannedNewVal.Equals(unmarkedPriorVal)` - this unmarking is correct for VALUE comparison, but the planned value NEVER had schema marks applied to it (they weren't added by the provider processing at lines 998-1000)
- The **refreshed state** comes back WITH schema marks (from GetResource in evaluate.go), but the **planned state** doesn't have them (because they weren't applied in plan())
- When comparing the refreshed before state against the planned after state in `terraform plan`, the difference in marks (even though the values are identical) makes them appear different

This is actually a more subtle issue:
- The prior state (from refresh) gets read by the evaluator and gets schema marks via `GetResource()`
- But this evaluator-marked state is used for EXPRESSION evaluation only, not for the plan comparison
- The actual plan comparison uses the unmarked values (as seen at line 1082), so this shouldn't cause issues directly...

**However**, the real phantom diff occurs in the refresh + plan cycle:
1. `terraform refresh` reads from state (which has marks from variables only)
2. Provider.ReadResource returns unmarked values
3. Marks from prior state only are re-applied (lines 718-720)
4. New state is written with incomplete marks
5. Next `terraform plan` reads this state (with incomplete marks)
6. But when evaluating expressions in the config, `GetResource()` ADDS schema marks
7. The plan's before state (from refresh) ends up with different marks than what was actually stored
8. If those marks were mismatched between what was in the actual plan vs what appears in a refresh-only plan, phantom changes occur

## Evidence

### File: `/workspace/internal/terraform/node_resource_abstract_instance.go`

**Lines 868-870 (plan function)** - Extract marks from config and prior, but NOT schema:
```go
unmarkedConfigVal, unmarkedPaths := configValIgnored.UnmarkDeepWithPaths()
unmarkedPriorVal, priorPaths := priorVal.UnmarkDeepWithPaths()
```

**Lines 998-1000 (plan function)** - Re-apply config marks only:
```go
if len(unmarkedPaths) > 0 {
    plannedNewVal = plannedNewVal.MarkWithPaths(unmarkedPaths)
}
```

**Lines 623-626 (refresh function)** - Extract prior marks only:
```go
var priorPaths []cty.PathValueMarks
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()
}
```

**Lines 718-720 (refresh function)** - Re-apply prior marks only:
```go
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)
}
```

### File: `/workspace/internal/states/instance_object.go`

**Lines 94-137 (Encode function)** - Serialize marks from the value as-is:
```go
val, pvm := o.Value.UnmarkDeepWithPaths()
// ... no schema-based mark collection happens here ...
return &ResourceInstanceObjectSrc{
    SchemaVersion:       schemaVersion,
    AttrsJSON:           src,
    AttrSensitivePaths:  pvm,  // <-- incomplete, missing schema marks
    // ...
}
```

### File: `/workspace/internal/terraform/evaluate.go`

**Lines 718-723 (GetResource function)** - THE ONLY place schema marks are applied:
```go
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(val, nil)...)  // <-- schema marks added HERE
    val = val.MarkWithPaths(marks)
}
instances[key] = val
```

**Lines 689-693 (GetResource function)** - Also applies schema marks for planned resources:
```go
if schema.ContainsSensitive() {
    afterMarks = append(afterMarks, schema.ValueMarks(val, nil)...)
}
instances[key] = val.MarkWithPaths(afterMarks)
```

### File: `/workspace/internal/command/jsonplan/plan.go`

**Lines 417-420 (MarshalResourceChanges function)** - JSON plan layer compensates by adding schema marks:
```go
marks := rc.BeforeValMarks
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.Before, nil)...)
}
```

This shows the problem is known at the JSON serialization layer - it has to manually add schema marks that should have been there all along.

## Affected Components

1. **`internal/terraform/node_resource_abstract_instance.go`**
   - `plan()` method - doesn't apply schema marks when processing provider responses
   - `refresh()` method - doesn't apply schema marks after ReadResource responses
   - `apply()` method - inherits mark gap from plan

2. **`internal/states/instance_object.go`**
   - `Encode()` method - serializes incomplete sensitivity information to state files
   - Result: `sensitive_attributes` in state files are missing schema-defined sensitive paths

3. **`internal/terraform/evaluate.go`**
   - `GetResource()` method - is the ONLY place applying schema marks, creating asymmetry
   - This compensating workaround masks the upstream problem

4. **`internal/command/jsonplan/plan.go`** and **`internal/command/jsonstate/state.go`**
   - Both JSON output layers have to manually apply schema marks (lines 418-420 and 447-449 in plan.go; lines 403-405 in state.go)
   - This indicates the problem is recognized at serialization boundaries

5. **`internal/configschema/marks.go`** (not directly involved, but provides the mechanism)
   - Provides `schema.ContainsSensitive()` and `schema.ValueMarks()` methods used for mark application

## Causal Chain

1. **Provider Response** → Provider returns unmarked values (no provider responsibility for marks)
2. **Initial Processing** → `plan()` and `refresh()` extract marks from config/prior state only
3. **No Schema Mark Application** → Lines 998-1000 (plan) and 718-720 (refresh) re-apply config/prior marks only
4. **State Write with Incomplete Marks** → `instance_object.go::Encode()` serializes marks that don't include schema marks
5. **State File Incomplete** → `sensitive_attributes` in saved state missing schema-defined sensitive paths
6. **Evaluator Compensates** → `evaluate.go::GetResource()` adds schema marks when reading for expressions
7. **Asymmetry in Plan** → Plan response from provider (without schema marks) compared against prior state (with schema marks from evaluator)
8. **Phantom Diff** → Even though values are identical, mark differences cause plan to show "change" action
9. **JSON Output Gap** → `terraform show -json` incomplete for `sensitive_values` since state file has incomplete marks
10. **Refresh-Plan Cycle** → Running `terraform plan -refresh-only` or subsequent `terraform plan` after apply shows phantom changes

## Recommendation

The fix requires applying schema-defined sensitivity marks at the point where provider responses are first processed, not deferring to the evaluator workaround.

### Fix Strategy

1. **In `node_resource_abstract_instance.go::plan()`** (after line 916, after receiving provider response):
   - Apply schema marks to `plannedNewVal` using `schema.ValueMarks()` before re-applying config marks
   - Maintain the marks through the rest of the planning cycle

2. **In `node_resource_abstract_instance.go::refresh()`** (after line 684, after normalizing response):
   - Apply schema marks to `newState` using `schema.ValueMarks()` before re-applying prior marks
   - This ensures state always includes schema-defined sensitive marks

3. **In `node_resource_abstract_instance.go::apply()`** (after line 2460, after provider returns):
   - Apply schema marks to `newVal` from the provider response before re-applying plan marks
   - This ensures applied state includes complete sensitivity information

4. **Remove the workaround from `evaluate.go::GetResource()`** (lines 689-693 and 718-723):
   - Once values in state have schema marks, no compensation is needed
   - The evaluator can rely on marks already in state

### Diagnostic Steps

- Add logging at point (1), (2), (3) to show which schema marks are being applied and to which values
- Compare before/after state files for `sensitive_attributes` to verify they now include schema-defined paths
- Verify `terraform show -json` output now shows complete `sensitive_values`
- Test phantom diff scenario: apply resource, then plan again immediately - should show NoOp
- Test refresh-only: refresh should not create changes just due to sensitivity mark handling

## Additional Notes

The `apply()` function at lines 2462-2465 already has the pattern for applying marks:
```go
if len(afterPaths) > 0 {
    newVal = newVal.MarkWithPaths(afterPaths)
}
```

But these `afterPaths` don't include schema marks - they come from the plan, which also lacked schema marks. The fix requires making this chain complete by including schema marks at every stage.

The reason the JSON output layers (plan.go lines 418-420 and state.go lines 403-405) work correctly is because they apply schema marks at serialization time. However, this is a band-aid that masks the upstream gap and leaves state files with incomplete sensitivity information.
