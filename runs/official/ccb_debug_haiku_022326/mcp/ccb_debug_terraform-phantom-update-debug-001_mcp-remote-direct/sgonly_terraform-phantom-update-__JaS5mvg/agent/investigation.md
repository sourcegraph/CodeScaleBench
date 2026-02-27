# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place updates for resources with provider-schema-defined sensitive attributes due to an asymmetry in how sensitivity marks are applied across the planning pipeline. The root cause is that sensitivity marks from the provider schema are only applied during expression evaluation (GetResource), not when state is initially stored or refreshed, creating a mismatch between the before and after values in the plan comparison.

## Root Cause

The phantom updates stem from an incomplete sensitivity mark workflow that spans four critical junctions:

1. **State Serialization Gap** (`internal/states/instance_object.go:98`): When a resource value is encoded to state, only existing sensitivity marks are captured via `UnmarkDeepWithPaths()`. Provider schema-defined sensitivity marks are never applied at this point, so `AttrSensitivePaths` in the stored state is incomplete.

2. **Refresh Mark Reapplication** (`internal/terraform/node_resource_abstract_instance.go:717-720`): After a provider refresh, only the marks that existed in the prior state are reapplied. Since schema marks were never stored, they don't get restored.

3. **Compensating Workaround in Evaluation** (`internal/terraform/evaluate.go:714-723`): The only place where schema-defined marks are applied to resource values is in `GetResource()` during config expression evaluation. For existing instances, the code unmasks the value, combines existing marks with schema marks via `schema.ValueMarks()`, then reapplies all marks.

4. **Asymmetric Mark Comparison in Planning** (`internal/terraform/node_resource_abstract_instance.go:1208`): The plan method compares sensitivity marks between `plannedNewVal` (which has schema marks added during config evaluation) and `priorPaths` (which only has variable-reference marks from stored state). When these don't match, a NoOp action is changed to Update.

## Evidence

### 1. State Serialization (instance_object.go)

**File:** `internal/states/instance_object.go:94-137`

```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    // Line 98: Only saves marks that are currently on the value
    val, pvm := o.Value.UnmarkDeepWithPaths()

    // Lines 111-114: Schema marks are never captured here
    src, err := ctyjson.Marshal(val, ty)
    ...
    // Line 131: AttrSensitivePaths only has variable-reference marks
    return &ResourceInstanceObjectSrc{
        SchemaVersion:      schemaVersion,
        AttrsJSON:          src,
        AttrSensitivePaths: pvm,  // <-- INCOMPLETE: missing schema marks
        ...
    }, nil
}
```

### 2. Refresh Mark Reapplication (node_resource_abstract_instance.go)

**File:** `internal/terraform/node_resource_abstract_instance.go:620-722`

```go
// Lines 620-626: Unmarked prior value before sending to provider
priorVal := state.Value
var priorPaths []cty.PathValueMarks
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()
}

// Lines 636-642: Provider returns unmarked response
resp = provider.ReadResource(providers.ReadResourceRequest{
    PriorState:   priorVal,  // unmarked
    ...
})
// resp.NewState also comes back unmarked

// Lines 717-720: Only priorPaths are reapplied (schema marks missing)
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)  // <-- INCOMPLETE MARKS
}
```

### 3. Compensating Marks in GetResource (evaluate.go)

**File:** `internal/terraform/evaluate.go:714-723`

```go
// Only location where schema marks are applied to resource values
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(val, nil)...)  // <-- ADDS SCHEMA MARKS
    val = val.MarkWithPaths(marks)
}
instances[key] = val
```

This is called during config evaluation for resource references, creating schema marks that don't exist in state.

### 4. Asymmetric Mark Comparison in Plan (node_resource_abstract_instance.go)

**File:** `internal/terraform/node_resource_abstract_instance.go:1199-1210`

```go
// Line 1208: The exact mechanism of phantom updates
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update  // <-- TRIGGERED BY MARK MISMATCH
}
```

Where:
- `plannedNewVal`: Has marks from config evaluation (includes schema marks via GetResource)
- `priorPaths`: Only has marks from prior state (no schema marks, because they were never stored)
- `unmarkedPaths`: Config-level marks captured before sending to provider

### 5. JSON Output with Incomplete Sensitivity (jsonstate/state.go)

**File:** `internal/command/jsonstate/state.go:402-411`

```go
// Lines 402-406: Attempts to compensate for incomplete state marks
value, marks := riObj.Value.UnmarkDeepWithPaths()
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(value, nil)...)  // <-- ADDS SCHEMA MARKS
}
s := SensitiveAsBool(value.MarkWithPaths(marks))
v, err := ctyjson.Marshal(s, s.Type())
current.SensitiveValues = v
```

While this code correctly adds schema marks for JSON output, it cannot retroactively fix the incomplete `AttrSensitivePaths` stored in state, which is what the plan phase uses for comparison.

## Affected Components

1. **`internal/terraform/node_resource_abstract_instance.go`**
   - `refresh()` method: Reapplies only captured marks, not schema marks
   - `plan()` method: Compares marks between refreshed state and planned value (line 1208)

2. **`internal/terraform/evaluate.go`**
   - `GetResource()` method: Only location that applies schema marks during evaluation (lines 714-723, 689-695)
   - Creates asymmetry by applying marks that aren't in state

3. **`internal/states/instance_object.go`**
   - `Encode()` method: Captures incomplete sensitivity marks at serialization time

4. **`internal/states/statefile/`**
   - State reading layer: Applies only captured marks from `AttrSensitivePaths`

5. **`internal/command/jsonstate/state.go`**
   - JSON output layer: Attempts to compensate for incomplete marks (lines 403-405)

6. **`internal/plans/objchange/`**
   - Diff comparison machinery: Unmarked comparisons work correctly, but mark equality check fails

## Causal Chain

### Symptom: Phantom In-Place Updates
1. User runs `terraform plan` after successful `terraform apply` with no configuration changes
2. Plan shows resource "will be updated in-place" despite identical before/after values
3. Diff shows only "(1 unchanged attribute hidden)" but action is Update, not NoOp

### Causal Chain (root → symptom)

**Layer 1 - State Serialization** → **Incomplete Sensitivity Record**
- Provider response comes back unmarked (line 636-642)
- Value is stored in state with only variable-reference marks (instance_object.go:98)
- Schema-defined sensitivity marks are never recorded in `AttrSensitivePaths`

**Layer 2 - Refresh Cycle** → **Marks Not Restored**
- Prior state is read with only variable-reference marks (node_resource_abstract_instance.go:625-626)
- Provider refresh returns unmarked value (line 636-642)
- Only prior marks are reapplied (line 718-720), perpetuating the incomplete mark set

**Layer 3 - Config Evaluation** → **Compensating Marks Applied**
- During plan phase, config expressions are evaluated
- `GetResource()` is called for resource references
- Schema marks are applied to the value being used in config (evaluate.go:714-723)
- These marks did NOT come from state, only from schema

**Layer 4 - Plan Comparison** → **Mark Mismatch Detected**
- Before value (from refreshed state): has variable-reference marks only
- After value (from config evaluation + provider response): has variable-reference marks + schema marks
- Comparison at line 1208: `!marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths)` returns true
- NoOp action is upgraded to Update action
- Phantom update is generated

**Layer 5 - JSON Output** → **Incomplete Sensitivity Map**
- `terraform show -json` reads `AttrSensitivePaths` from state (incomplete)
- `sensitive_values` in JSON reflects only variable-reference marks, not schema marks
- Missing sensitivity marks for schema-defined sensitive attributes

## Recommendation

### Root Fix Strategy

The fundamental issue is the timing and scope of sensitivity mark application. Schema-defined sensitivity marks must be applied **when the value is first stored to state**, not just during evaluation. This requires:

1. **Apply Schema Marks During State Serialization**
   - Modify `instance_object.go:Encode()` to also apply schema marks before capturing `UnmarkDeepWithPaths()`
   - Requires passing schema context to the `Encode()` method
   - Ensures `AttrSensitivePaths` contains the complete set of sensitivity marks

2. **Eliminate Compensating Marks in GetResource**
   - Once schema marks are properly stored, `GetResource()` can be simplified
   - Marks would be correctly restored from state instead of reapplied from schema
   - Removes the asymmetry that triggers phantom updates

3. **Simplify Mark Comparison**
   - Once both before and after values have consistent schema marks, the comparison at line 1208 will naturally be equal
   - No spurious Update actions from mark mismatches

### Diagnostic Steps

To confirm this issue in any Terraform instance:

1. **Verify State Incompleteness:**
   ```bash
   terraform state show -json | jq '.values.root_module.resources[].instances[].sensitive_attributes'
   # Schema-defined sensitive attributes will be missing
   ```

2. **Check Before/After Marks in Plan:**
   - Add debug logging to `node_resource_abstract_instance.go:1208`
   - Log the result of `marksEqual()` comparison
   - Confirm mismatch is due to schema marks only

3. **Trace GetResource Application:**
   - Search for `schema.ValueMarks()` calls in `evaluate.go`
   - Confirm these marks don't exist in state's `AttrSensitivePaths`
   - These marks are being applied "late" (during evaluation) instead of "early" (during storage)
