# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place updates for resources with provider-schema-defined sensitive attributes because provider schema sensitivity marks are never stored in state, creating an asymmetry where the evaluator adds these marks during expression evaluation but the plan comparison uses incomplete marks from the state file.

## Root Cause

**Core Issue**: Schema-defined sensitive attribute marks are not persisted in the state file, but they ARE applied during expression evaluation. This causes the mark sets to differ between what's stored in state and what's used during planning, triggering spurious update actions.

**Mechanism**:
- When resource values are encoded for state storage (`instance_object.go`), only marks already present on the value are extracted. Schema-defined sensitivity is never added to values before encoding, so it never makes it into `AttrSensitivePaths`.
- During plan operations, the comparison checks both value equality and mark equality (`node_resource_abstract_instance.go:1208`). When the mark sets differ (because schema marks are absent from the prior state's `priorPaths`), Terraform changes the action from NoOp to Update, even though the actual attribute values are identical.
- The compensating workaround in `evaluate.go:GetResource()` adds schema marks during expression evaluation, but this only masks the problem for expression evaluation—not for plan comparison.

## Evidence

### 1. State Encoding without Schema Marks
**File**: `internal/states/instance_object.go:94-137`

```go
// Line 98: Extract marks from the value (but schema marks were never added)
val, pvm := o.Value.UnmarkDeepWithPaths()

// Lines 129-131: Only extracted marks are stored
return &ResourceInstanceObjectSrc{
    // ...
    AttrSensitivePaths: pvm,  // <- Only contains marks that were on the value
    // ...
}
```

**Problem**: Schema marks are never added to the value before encoding, so only variable-reference marks make it into the state file.

### 2. State Decoding without Schema Marks
**File**: `internal/states/instance_object_src.go:77-104`

```go
// Lines 89-91: Only apply marks that are stored in state
if os.AttrSensitivePaths != nil {
    val = val.MarkWithPaths(os.AttrSensitivePaths)
}
```

**Problem**: Schema marks are not reapplied because they're not in the state file.

### 3. Compensating Workaround in Expression Evaluation
**File**: `internal/terraform/evaluate.go:714-723`

```go
// Lines 718-722: Schema marks ARE added during expression evaluation
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    // <- Schema marks are explicitly computed here
    marks = append(marks, schema.ValueMarks(val, nil)...)
    val = val.MarkWithPaths(marks)
}
```

**Critical Insight**: This is the ONLY place where schema marks are applied to values read from state. It creates an asymmetry where:
- Values stored IN STATE lack schema marks
- Values used FOR EVALUATION have schema marks

### 4. Incomplete Marks in Refresh Path
**File**: `internal/terraform/node_resource_abstract_instance.go:578-723`

```go
// Lines 620-626: Extract marks from prior state
priorVal := state.Value
var priorPaths []cty.PathValueMarks
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()
}

// Lines 636-642: Call provider with unmarked value
resp = provider.ReadResource(providers.ReadResourceRequest{
    TypeName:   n.Addr.Resource.Resource.Type,
    PriorState: priorVal,  // <- Unmarked, no schema marks
    // ...
})

// Lines 718-720: Reapply only the extracted marks
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)
}
```

**Problem**: `priorPaths` only contains marks from the state file, which lacks schema-defined marks. The refreshed state is returned without schema marks.

### 5. Phantom Update Detection in Plan
**File**: `internal/terraform/node_resource_abstract_instance.go:1199-1210`

```go
// Lines 1199-1210: THE PHANTOM UPDATE TRIGGER
// If our prior value was tainted then we actually want this to appear
// as a replace change, even though so far we've been treating it as a
// create.
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update
}
```

**This is where phantom updates are created**:
- Line 1082: `eqV := unmarkedPlannedNewVal.Equals(unmarkedPriorVal)` passes (values are identical)
- Line 1090: Action would normally be `plans.NoOp`
- Line 1208: But the mark comparison fails because:
  - `filterMarks(plannedNewVal, unmarkedPaths)` = marks from config (which may include no schema marks)
  - `priorPaths` = marks from prior state (which definitely lacks schema marks)
  - If they differ, action changes to Update
- **Result**: Phantom Update even though values are identical

### 6. Incomplete Sensitivity in JSON Output
**Files**: `internal/command/jsonplan/plan.go:410-455` and `internal/command/jsonstate/state.go:400-460`

```go
// Lines 418-420 (jsonplan/plan.go): Schema marks ARE added for JSON output
marks := rc.BeforeValMarks
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.Before, nil)...)
}

// Lines 447-449: Schema marks added for after value too
marks := rc.AfterValMarks
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.After, nil)...)
}
```

**Manifestation**:
- JSON plan output shows schema-defined sensitivity marks (via explicit `schema.ValueMarks()` call)
- But these marks are not stored in the state file
- `terraform show -json` on state shows incomplete `sensitive_values` (missing schema-defined paths)
- This creates a mismatch between what users see in JSON output and what's actually in state

## Affected Components

1. **`internal/states/`** - State serialization
   - `instance_object.go` - Value encoding for state storage
   - `instance_object_src.go` - Value decoding from state

2. **`internal/terraform/`** - Graph evaluation and planning
   - `node_resource_abstract_instance.go` - Resource instance graph node, handles refresh and plan operations
   - `evaluate.go` - Expression evaluation with compensating workaround
   - `marks.go` - Mark comparison utilities

3. **`internal/command/`** - CLI output generation
   - `jsonplan/plan.go` - Plan JSON serialization with explicit schema mark addition
   - `jsonstate/state.go` - State JSON serialization with explicit schema mark addition

## Causal Chain

1. **Provider Response** → Value without any marks (providers don't add marks)
2. **Plan Processing** → Marks are extracted from config expressions via `UnmarkDeepWithPaths()`
3. **State Encoding** → Value with only extracted marks is persisted (schema marks never added before encoding)
4. **State File Storage** → `AttrSensitivePaths` contains only variable-reference marks, not schema marks
5. **State Decoding** → Only stored marks (variable-reference) are reapplied to value
6. **Refresh Operation** → Prior marks extracted from state (incomplete, missing schema marks)
7. **Plan Operation** → Marks comparison in line 1208 finds `priorPaths` incomplete
8. **Sensitivity Check** → Mark mismatch triggers action change from NoOp to Update
9. **Phantom Update** → User sees "will be updated in-place" despite identical values
10. **JSON Output** → Explicit schema mark addition for JSON masks the issue partially, but state lacks marks

## Recommendation

**Fix Strategy**: Add schema-defined sensitivity marks to resource values BEFORE they are encoded to state.

**Implementation Steps**:

1. **In state encoding** (`instance_object.go:Encode`):
   - Before calling `UnmarkDeepWithPaths()` (line 98), add schema marks to the value
   - This requires passing the schema to the Encode method
   - Ensure schema marks are included in the extracted `pvm`

2. **Schema availability**:
   - The Encode method needs access to the resource schema to determine which attributes should be marked as sensitive
   - This requires changes to the method signature or context

3. **State compatibility**:
   - Once schema marks are stored in state files, old state files (without these marks) will need to be handled gracefully during decoding
   - The current code in `instance_object_src.go` should be forward-compatible since it applies any marks found in `AttrSensitivePaths`

4. **Remove compensating workaround**:
   - Once schema marks are properly stored in state, the workaround in `evaluate.go:GetResource()` (lines 718-722) can be simplified or removed
   - Values read from state will already have the correct marks

**Diagnostic Steps**:

1. Enable detailed logging in the mark comparison (line 1208 of `node_resource_abstract_instance.go`)
2. Compare `priorPaths` and `filterMarks(plannedNewVal, unmarkedPaths)` to confirm the difference
3. Verify that schema-defined attribute paths are missing from `priorPaths`
4. Check that the same attributes appear in JSON output sensitivity marks (via `schema.ValueMarks()`)

**Testing**:

1. Create test resources with provider-schema-defined sensitive attributes
2. After successful apply, immediately run plan and verify no phantom updates
3. Verify state file contains the complete set of sensitive paths
4. Confirm JSON output matches state sensitivity information
