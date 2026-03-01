# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes in Terraform

## Summary

Terraform generates phantom in-place update actions for resources with schema-defined sensitive attributes due to an asymmetry in how sensitivity marks are handled: schema-derived sensitivity marks are applied only during expression evaluation (in `evaluate.go`), not during the refresh-to-plan comparison phase in `node_resource_abstract_instance.go`. This causes the mark-based action override at line 1208 to incorrectly convert NoOp to Update when schema-sensitive attributes are present, even though the underlying attribute values are identical.

## Root Cause

The root cause is a critical asymmetry in sensitivity mark propagation across three phases:

1. **Refresh Phase** (`node_resource_abstract_instance.go:718-720`): Marks from prior state are extracted, provider is called with unmarked values, and then only the extracted marks are re-applied. Schema-derived marks are NOT applied.

2. **Plan Comparison Phase** (`node_resource_abstract_instance.go:1208`): A mark-equality check compares config marks against refresh marks. Because schema marks were never applied to the refreshed state, the mark sets differ, triggering an erroneous action upgrade from NoOp to Update.

3. **Expression Evaluation Phase** (`evaluate.go:714-723`): Schema-derived marks ARE applied when values are read for expression evaluation, but this happens AFTER planning and is NOT reflected in the plan comparison.

This creates a cascade where:
- State is stored WITHOUT schema marks (line `instance_object.go:131`)
- State is decoded without schema marks (line `instance_object_src.go:90`)
- Refresh doesn't apply schema marks (line `node_resource_abstract_instance.go:718-720`)
- Plan comparison uses incomplete mark information (line `node_resource_abstract_instance.go:1208`)
- Schema marks are only applied later during evaluation (line `evaluate.go:718-723`)

## Evidence

### 1. Refresh Does Not Apply Schema Marks

**File**: `/workspace/internal/terraform/node_resource_abstract_instance.go`
**Lines**: 620-720

```go
// Line 620: Load state value (only has reference marks from decode)
priorVal := state.Value

// Lines 624-626: Extract only reference marks
var priorPaths []cty.PathValueMarks
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()  // priorPaths = reference marks only
}

// Lines 636-641: Send unmarked to provider
resp = provider.ReadResource(providers.ReadResourceRequest{
    TypeName:     n.Addr.Resource.Resource.Type,
    PriorState:   priorVal,  // UNMARKED
    ...
})

// Line 684: Receive unmarked response
newState := objchange.NormalizeObjectFromLegacySDK(resp.NewState, schema)

// Lines 717-720: RE-APPLY ONLY REFERENCE MARKS (NOT SCHEMA MARKS)
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)  // Only reference marks!
}
// Missing: schema marks are NOT applied here
```

**Critical Gap**: The refresh method has access to `schema` (line 598) but never calls `schema.ValueMarks()` to apply schema-derived sensitivity marks.

### 2. State Storage Only Preserves Reference Marks

**File**: `/workspace/internal/states/instance_object.go`
**Lines**: 94-137

```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    // Line 98: Unmark the value to enable JSON serialization
    val, pvm := o.Value.UnmarkDeepWithPaths()  // pvm = all marks from value

    // Lines 128-136: Store only what was marked in the value
    return &ResourceInstanceObjectSrc{
        SchemaVersion:      schemaVersion,
        AttrsJSON:          src,
        AttrSensitivePaths: pvm,  // Stores ONLY marks that were on the value
        Private:            o.Private,
        ...
    }, nil
}
```

**Why This Matters**: The state file stores `AttrSensitivePaths`, which only contains marks that were physically on the cty.Value object. Schema-derived marks are NOT stored because they're applied at evaluation time, not at state serialization time. This is by design—marks should not be double-stored. But it creates a gap when comparing during planning.

### 3. State Decoding Restores Only Reference Marks

**File**: `/workspace/internal/states/instance_object_src.go`
**Lines**: 77-104

```go
func (os *ResourceInstanceObjectSrc) Decode(ty cty.Type) (*ResourceInstanceObject, error) {
    // Line 87: Unmarshal from JSON
    val, err = ctyjson.Unmarshal(os.AttrsJSON, ty)

    // Lines 89-91: Re-apply ONLY stored reference marks
    if os.AttrSensitivePaths != nil {
        val = val.MarkWithPaths(os.AttrSensitivePaths)  // Only reference marks
    }
    // Missing: schema marks NOT applied here

    return &ResourceInstanceObject{
        Value: val,  // Has reference marks only
        ...
    }, nil
}
```

### 4. The Plan Comparison Asymmetry

**File**: `/workspace/internal/terraform/node_resource_abstract_instance.go`
**Lines**: 868-1208

**Step 1: Extract marks from inputs (lines 868-869)**
```go
unmarkedConfigVal, unmarkedPaths := configValIgnored.UnmarkDeepWithPaths()  // Config marks
unmarkedPriorVal, priorPaths := priorVal.UnmarkDeepWithPaths()             // Reference marks only!
```

**Step 2: Call provider with unmarked values (lines 902-909)**
```go
resp = provider.PlanResourceChange(providers.PlanResourceChangeRequest{
    TypeName:         n.Addr.Resource.Resource.Type,
    Config:           unmarkedConfigVal,
    PriorState:       unmarkedPriorVal,    // UNMARKED (no schema marks)
    ProposedNewState: proposedNewVal,
    PriorPrivate:     priorPrivate,
    ProviderMeta:     metaConfigVal,
})
```

**Step 3: Provider returns unmarked planned state (lines 916-1000)**
```go
plannedNewVal := resp.PlannedState
...
// Re-apply config marks to planned value
if len(unmarkedPaths) > 0 {
    plannedNewVal = plannedNewVal.MarkWithPaths(unmarkedPaths)  // Apply config marks
}
```

**Step 4: THE PHANTOM UPDATE TRIGGER (lines 1208-1210)**
```go
// line 1082-1083: Basic value equality check (unmarked comparison)
eqV := unmarkedPlannedNewVal.Equals(unmarkedPriorVal)
eq := eqV.IsKnown() && eqV.True()

// lines 1085-1091: If values are equal, set action to NoOp
var action plans.Action
switch {
case priorVal.IsNull():
    action = plans.Create
case eq && !matchedForceReplace:
    action = plans.NoOp  // <- Values are equal

// LINE 1208: THIS CONVERTS NoOp TO Update BASED ON MARK DIFFERENCES
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update  // <- PHANTOM UPDATE!
}
```

**The Comparison Being Made**:
- **Planned value marks**: `filterMarks(plannedNewVal, unmarkedPaths)` = config marks from configuration
- **Prior value marks**: `priorPaths` = reference marks from refreshed state (NO schema marks!)

**Why This Causes Phantom Updates**:

When a provider schema declares an attribute as sensitive:

| Phase | What Happens | Marks Present |
|-------|-------------|---------------|
| Encode to state file | Unmark value before JSON serialization | Reference marks only (if any) |
| Decode from state file | Restore reference marks only | Reference marks only |
| Refresh execute | Re-apply reference marks, NOT schema marks | Reference marks only |
| Plan extract prior marks | Extract marks from refreshed state | Reference marks only |
| Plan extract config marks | Extract marks from config | Config marks (possibly different!) |
| **Plan comparison at line 1208** | **Compare: config marks vs reference marks** | **DIFFERENT!** |
| Result | Action changed from NoOp to Update | **Phantom Update!** |

### 5. Schema Marks Are Applied ONLY During Expression Evaluation

**File**: `/workspace/internal/terraform/evaluate.go`
**Lines**: 714-723

```go
// Decode state value (has reference marks only from state file)
ios, err := is.Current.Decode(ty)
...
val := ios.Value  // Has reference marks only

// THIS IS WHERE SCHEMA MARKS ARE APPLIED, BUT ONLY FOR EVALUATION
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()  // Remove reference marks
    marks = append(marks, schema.ValueMarks(val, nil)...)  // ADD schema marks
    val = val.MarkWithPaths(marks)  // Re-apply combined marks
}
instances[key] = val  // Value now has schema marks for expression evaluation
```

**Critical Point**: Schema marks are applied here (line 718-723), but this is AFTER planning. The marks applied here are NOT reflected in the plan file or the plan comparison.

Additionally, at lines 689-695, for planned changes:
```go
afterMarks := change.AfterValMarks
if schema.ContainsSensitive() {
    afterMarks = append(afterMarks, schema.ValueMarks(val, nil)...)  // Schema marks added
}
instances[key] = val.MarkWithPaths(afterMarks)
```

This applies schema marks for expression evaluation, but these marks are NOT stored in the plan file or used in the plan comparison logic.

### 6. Marks Utility Functions

**File**: `/workspace/internal/terraform/marks.go`
**Lines**: 17-58

```go
// Line 31-58: marksEqual compares two sets of marks
func marksEqual(a, b []cty.PathValueMarks) bool {
    // Unordered comparison of path/mark sets
    ...
}

// Line 17-27: filterMarks removes marks that don't apply to a value
func filterMarks(val cty.Value, marks []cty.PathValueMarks) []cty.PathValueMarks {
    // Returns only marks that can be applied to val
    ...
}
```

These functions are used at line 1208 to compare mark sets, but they operate on incomplete mark information (missing schema marks).

## Affected Components

1. **`internal/terraform/node_resource_abstract_instance.go`** (1270 lines)
   - `refresh()` method (lines 580-723): Doesn't apply schema marks after refresh
   - `plan()` method (lines 725-1268): Mark comparison logic at line 1208

2. **`internal/states/instance_object.go`** (150 lines)
   - `Encode()` method (lines 94-137): Stores only reference marks

3. **`internal/states/instance_object_src.go`** (150+ lines)
   - `Decode()` method (lines 77-104): Restores only reference marks

4. **`internal/terraform/evaluate.go`** (800+ lines)
   - `GetResource()` method (lines 680-725): Applies schema marks for evaluation only

5. **`internal/terraform/marks.go`** (60 lines)
   - `marksEqual()` and `filterMarks()` functions: Compare incomplete mark sets

6. **`internal/command/jsonplan/values.go`** (250 lines)
   - `marshalPlanResources()` (lines 169-245): Uses marks from plan (which lack schema marks)

7. **`internal/command/jsonstate/state.go`** (500 lines)
   - `State()` method (lines 400-411, 453-462): Correctly applies schema marks when generating JSON output (but plan generation doesn't)

8. **Provider RPC boundary**:
   - Provider receives unmarked values
   - Provider returns unmarked values
   - All sensitivity marking is Terraform's responsibility

## Causal Chain

1. **Initial Symptom**: User reports phantom in-place updates after `terraform apply` with no config changes

2. **Intermediate Hop 1 - State Storage**: When state is encoded for storage (lines 94-137 in `instance_object.go`), schema-derived marks are NOT stored because they are considered transient marks applied only at evaluation time. State stores only reference marks (marks from sensitive variable references).

3. **Intermediate Hop 2 - State Decoding**: When state is decoded for use in subsequent operations (lines 77-104 in `instance_object_src.go`), only the stored reference marks are restored. Schema marks are missing.

4. **Intermediate Hop 3 - Refresh Execution**: During `terraform refresh` (lines 580-723 in `node_resource_abstract_instance.go`), the code:
   - Extracts marks from the prior state (only reference marks)
   - Sends unmarked value to provider
   - Receives unmarked response
   - Re-applies only the extracted reference marks (line 718-720)
   - Does NOT apply schema marks (never calls `schema.ValueMarks()`)

5. **Intermediate Hop 4 - Plan Starts**: In the plan phase (lines 725+), the code receives the refreshed state as "prior state." This prior state has only reference marks, NOT schema marks.

6. **Intermediate Hop 5 - Mark Extraction**: Config marks are extracted from configuration (line 868), prior marks are extracted from refreshed state (line 869). These may differ:
   - Config marks depend on what variables are used (e.g., is `password = var.db_password`?)
   - Prior marks depend on what was stored in state (only reference marks)
   - Schema marks are NOT in either set

7. **ROOT CAUSE - Phantom Update Trigger** (line 1208): The plan comparison logic checks if marks are equal. Because schema marks were never applied to the refreshed state, the mark comparison fails even though the values are identical:
   ```go
   if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
       action = plans.Update  // <- WRONG!
   }
   ```
   - `filterMarks(plannedNewVal, unmarkedPaths)`: config marks from config
   - `priorPaths`: reference marks from state (missing schema marks!)
   - These are different → action changed to Update

8. **Final Symptom**: Plan shows resource "will be updated in-place" even though no actual attribute values changed, only sensitivity mark metadata differs.

## Recommendation

The fix requires applying schema-derived sensitivity marks at the appropriate point in the refresh→plan flow:

**Option A (Recommended)**: Apply schema marks during refresh after receiving the provider response.

In `node_resource_abstract_instance.go`, modify the `refresh()` method (around lines 717-720) to:
```go
// Mark the value if necessary
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)
}

// ADDITION: Also apply schema-derived marks
if schema.ContainsSensitive() {
    unmarked, marks := ret.Value.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(unmarked, nil)...)
    ret.Value = unmarked.MarkWithPaths(marks)
}
```

This ensures the refreshed state has both reference marks AND schema marks before being passed to the plan phase.

**Option B**: Apply schema marks when extracting prior marks in the plan phase.

In `node_resource_abstract_instance.go`, modify the `plan()` method (around lines 868-869) to ensure schema marks are included when extracting `priorPaths`.

**Option C**: Store schema marks in state files.

Modify `instance_object.go` to calculate and store schema-derived marks in `AttrSensitivePaths`, though this requires schema context during state serialization.

**Diagnostic Steps**:

1. Enable trace-level logging for mark operations and compare marks applied at refresh vs marks used in plan comparison
2. Verify that schema marks are missing from refreshed state when compared to the planned value's marks
3. Confirm that phantom updates disappear once schema marks are applied during refresh
4. Check that `terraform show -json` on state and plan JSON outputs correctly show `sensitive_values` for schema-defined sensitive attributes (this is already handled correctly in `jsonstate.go` but may be missing from `jsonplan.go`)

## Key Files Summary

| File | Lines | Function | Issue |
|------|-------|----------|-------|
| `node_resource_abstract_instance.go` | 718-720 | `refresh()` | Doesn't apply schema marks |
| `node_resource_abstract_instance.go` | 868-869 | `plan()` | Extracts incomplete mark set (no schema marks) |
| `node_resource_abstract_instance.go` | 1208 | `plan()` | Compares incomplete marks, triggers phantom update |
| `instance_object.go` | 94-137 | `Encode()` | Stores only reference marks |
| `instance_object_src.go` | 77-104 | `Decode()` | Restores only reference marks |
| `evaluate.go` | 714-723 | `GetResource()` | Applies schema marks too late (after planning) |
| `marks.go` | 31-58 | `marksEqual()` | Called with incomplete mark sets |
| `jsonplan/values.go` | 212-235 | `marshalPlanResources()` | Plan JSON may lack schema marks |
