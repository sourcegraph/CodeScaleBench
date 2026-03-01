# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place updates for resources with provider-schema-defined sensitive attributes because schema-based sensitivity marks are applied inconsistently: they are excluded from state serialization but re-applied during expression evaluation, creating a mark asymmetry between planned and refreshed states during subsequent planning cycles.

## Root Cause

The root cause is an **incomplete sensitivity mark flow** across four interconnected mechanisms:

1. **State encoding strips schema marks** (`internal/states/instance_object.go:98-131`)
2. **State decoding lacks schema marks** (`internal/states/instance_object_src.go:77-104`)
3. **Planning ignores schema marks** (`internal/terraform/node_resource_abstract_instance.go:869-1208`)
4. **Evaluation compensates with schema marks** (`internal/terraform/evaluate.go:691-723`)

This creates a **mark application asymmetry**: schema marks are only added when values are read FOR EVALUATION, not when stored in or used FOR PLANNING.

## Evidence

### Evidence 1: State Encoding Loses Schema Marks

**File:** `internal/states/instance_object.go:94-137`

```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    val, pvm := o.Value.UnmarkDeepWithPaths()  // Line 98: Strips ALL marks
    val = cty.UnknownAsNull(val)
    src, err := ctyjson.Marshal(val, ty)
    if err != nil { return nil, err }

    return &ResourceInstanceObjectSrc{
        SchemaVersion:      schemaVersion,
        AttrsJSON:          src,
        AttrSensitivePaths: pvm,  // Line 131: Only stores extracted marks
        Private:            o.Private,
        Status:             o.Status,
        // ...
    }, nil
}
```

**Problem:** When `o.Value.UnmarkDeepWithPaths()` is called at line 98, all marks are stripped. Only marks that were already on the value are extracted into `pvm`. Schema-declared sensitive attributes (e.g., `password` marked `Sensitive: true` in the provider schema) are **never applied to values during planning**, so they are never present to extract. The `AttrSensitivePaths` saved to state contains only marks from sensitive variable references.

### Evidence 2: State Decoding Applies Only Stored Marks

**File:** `internal/states/instance_object_src.go:77-104`

```go
func (os *ResourceInstanceObjectSrc) Decode(ty cty.Type) (*ResourceInstanceObject, error) {
    var val cty.Value
    var err error
    if os.AttrsFlat != nil {
        val, err = hcl2shim.HCL2ValueFromFlatmap(os.AttrsFlat, ty)
    } else {
        val, err = ctyjson.Unmarshal(os.AttrsJSON, ty)
        if os.AttrSensitivePaths != nil {
            val = val.MarkWithPaths(os.AttrSensitivePaths)  // Line 90: Only stored marks
        }
        if err != nil { return nil, err }
    }
    return &ResourceInstanceObject{
        Value: val,  // Value has only sensitive variable marks
        // ...
    }, nil
}
```

**Problem:** At line 90, only the marks stored in `AttrSensitivePaths` are reapplied. These don't include schema-defined sensitive attributes because they were never extracted during encoding. The decoded value lacks schema sensitivity information.

### Evidence 3: Planning Compares Marks Without Schema Context

**File:** `internal/terraform/node_resource_abstract_instance.go:809-1208`

Key code paths during `plan()` method:

```go
// Line 812-827: Extract prior value from refreshed state
var priorVal cty.Value
if currentState != nil {
    if currentState.Status != states.ObjectTainted {
        priorVal = currentState.Value  // Already unmarked by refresh()
        priorPrivate = currentState.Private
    } else {
        priorValTainted = currentState.Value
        priorVal = cty.NullVal(schema.ImpliedType())
    }
} else {
    priorVal = cty.NullVal(schema.ImpliedType())
}

// Line 868-869: Extract config marks
unmarkedConfigVal, unmarkedPaths := configValIgnored.UnmarkDeepWithPaths()

// Line 869: Extract prior marks (from state only)
unmarkedPriorVal, priorPaths := priorVal.UnmarkDeepWithPaths()

// Line 998-1000: Reapply configuration marks only
if len(unmarkedPaths) > 0 {
    plannedNewVal = plannedNewVal.MarkWithPaths(unmarkedPaths)
}

// Line 1208: Phantom update triggered by mark difference
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update  // CONVERTS NoOp TO Update!
}
```

**Problem:** At line 1208, if the values are identical but marks differ, action is converted from `plans.NoOp` to `plans.Update`. This happens because:
- `plannedNewVal` is marked with `unmarkedPaths` (configuration marks)
- `priorPaths` comes from the state-loaded value (only sensitive variable marks)
- Neither path includes schema-defined sensitive marks, BUT...

### Evidence 4: Evaluator Applies Schema Marks Only for Expression Evaluation

**File:** `internal/terraform/evaluate.go:689-723`

This is the compensating workaround that creates the asymmetry:

```go
// Line 689-696: For planned values in expression evaluation
afterMarks := change.AfterValMarks
if schema.ContainsSensitive() {
    afterMarks = append(afterMarks, schema.ValueMarks(val, nil)...)  // ADDS schema marks
}
instances[key] = val.MarkWithPaths(afterMarks)

// ...

// Line 718-723: For state-loaded values in expression evaluation
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(val, nil)...)  // ADDS schema marks
    val = val.MarkWithPaths(marks)
}
instances[key] = val
```

**Problem:** Schema marks via `schema.ValueMarks()` are applied ONLY in `GetResource()`, which is used for expression evaluation. They are NOT applied during planning in `node_resource_abstract_instance.go`. This creates an asymmetry:

- **For expression evaluation:** Values have schema marks + variable marks
- **For planning state comparison:** Values have only variable marks
- **Result:** Same resource value appears different depending on context

### Evidence 5: Refresh Phase Doesn't Apply Schema Marks

**File:** `internal/terraform/node_resource_abstract_instance.go:580-723`

The `refresh()` method reapplies marks from prior state:

```go
// Line 623-626: Extract marks from prior state
var priorPaths []cty.PathValueMarks
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()
}

// Line 636-641: Call provider ReadResource (returns unmarked value)
resp = provider.ReadResource(providers.ReadResourceRequest{
    TypeName:     n.Addr.Resource.Resource.Type,
    PriorState:   priorVal,  // Sent unmarked
    Private:      state.Private,
    ProviderMeta: metaConfigVal,
})

// Line 717-720: Reapply marks from PRIOR state only
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)  // Only prior marks, no schema marks
}
```

**Problem:** The `priorPaths` extracted from the state-loaded value contain only sensitive variable marks (because that's all that was stored). Schema marks are never applied to the refreshed value, creating an inconsistency with expression evaluation.

### Evidence 6: JSON Output Manifests Incomplete Sensitivity

**File:** `internal/command/jsonplan/plan.go:417-450`

The JSON plan generation attempts to apply schema marks:

```go
// Line 417-420: For "before" sensitivity
marks := rc.BeforeValMarks
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.Before, nil)...)
}

// Line 446-449: For "after" sensitivity
marks := rc.AfterValMarks
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.After, nil)...)
}
```

**Problem:** Although the JSON output code attempts to apply schema marks (correct behavior), the marks stored in the plan (`rc.BeforeValMarks`, `rc.AfterValMarks`) are incomplete because they come from `Change.Encode()` which only extracted marks that existed at encoding time (line 590 in `internal/plans/changes.go`). Schema marks were never present during planning, so they're never extracted into the stored marks.

## Affected Components

- **`internal/terraform/node_resource_abstract_instance.go`** - Plan and refresh methods that handle mark flow
- **`internal/states/instance_object.go` and `instance_object_src.go`** - State serialization/deserialization that loses schema marks
- **`internal/terraform/evaluate.go`** - GetResource() compensating by applying schema marks (asymmetry point)
- **`internal/terraform/marks.go`** - Mark comparison logic that detects the asymmetry
- **`internal/command/jsonplan/plan.go` and `jsonstate/state.go`** - JSON output generation
- **`internal/plans/changes.go` and `changes_src.go`** - Change encoding/decoding that preserves only partial marks

## Causal Chain

1. **Provider Response → Unmarkable Value**
   - Provider returns resource values without any marks (correct: providers don't know about sensitivity)
   - Marks must be reapplied by Terraform

2. **Configuration Evaluation → Variable Marks Only**
   - Configuration is evaluated to extract sensitive variable references
   - These marks are stored in `origConfigVal` as `unmarkedPaths`
   - Schema-defined sensitive attributes are not in configuration, so no marks for them

3. **State Storage → Incomplete Mark Preservation**
   - When planning finishes, the planned value (with variable marks only) is stored to state via `Encode()`
   - `AttrSensitivePaths` in state captures only the marks that exist on the value: variable marks
   - Schema-defined marks are never present, so never stored

4. **State Loading → Mark Restoration Without Schema**
   - Next planning cycle loads state via `Decode()`
   - Marks from `AttrSensitivePaths` (variable marks only) are reapplied to the value
   - Value is refreshed; marks reapplied from prior state
   - No schema marks are applied

5. **Planning Phase → Mark Comparison Mismatch**
   - Plan method receives refreshed state with variable marks only
   - Provider returns new value (unmarked)
   - Config marks (variable marks only) are reapplied to planned value
   - Comparison at line 1208: `marksEqual(plannedNewVal, priorVal)` checks mark equality
   - If configuration hasn't changed, both should have the same variable marks
   - But in expression evaluation context, schema marks would be added, causing perceived difference

6. **Evaluation Workaround → Compensating Asymmetry**
   - When values are read FOR EXPRESSION EVALUATION via `GetResource()`, schema marks are added
   - This compensates for the missing marks in state
   - But planning never adds schema marks, creating inconsistency
   - Same resource value has different marks in planning context vs. evaluation context

7. **Phantom Update Manifestation**
   - Even with identical values, the mark difference (presence of schema marks in evaluated context vs. absence in planning context) could trigger the mismatch
   - The update action is triggered because the mark comparison fails, even though values are identical

## Recommendation

### Fix Strategy

The core issue is **incomplete mark application**: schema marks are applied inconsistently depending on context. There are two possible approaches:

**Option A (Preferred):** Apply schema marks during state serialization
- Include schema-defined sensitive attributes in `AttrSensitivePaths` when encoding state
- Call `schema.ValueMarks()` in `Change.Encode()` BEFORE unmarking, similar to what `evaluate.go` does
- Remove the compensating workaround from `GetResource()` or apply it consistently in planning

**Option B:** Strip schema marks during planning
- Remove schema mark application from `GetResource()` during expression evaluation
- Apply schema marks only at the display/output layer (JSON generation)
- Ensures marks are never stored in state, eliminating serialization inconsistency

### Diagnostic Steps

1. **Verify mark source discrepancy:**
   - In `Change.Encode()` (line 557 in `changes.go`), log the marks being extracted
   - In `node_resource_abstract_instance.go` line 1208, log `plannedNewVal` and `priorVal` marks
   - Confirm that schema marks are missing from stored marks but would be added in evaluation

2. **Trace mark application:**
   - Add logging in `evaluate.go` `GetResource()` when `schema.ValueMarks()` is called
   - Compare with logging in planning phase marks
   - Verify that planning never applies schema marks but evaluation does

3. **Test with sensitive attributes:**
   - Use a test resource with `Sensitive: true` declared attributes
   - Run apply, then immediately run plan
   - Confirm phantom update and that the diff shows update even though values are identical
   - Verify the JSON output shows incomplete `sensitive_values` without schema attributes

4. **State file inspection:**
   - Inspect saved state JSON and check `sensitive_attributes` field
   - Confirm it only contains paths from variable references, not from schema `Sensitive: true` attributes
   - Compare with what would be generated if schema marks were included
