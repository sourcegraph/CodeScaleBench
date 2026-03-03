# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Phantom in-place updates occur because Terraform's state serialization layer only records sensitivity marks from variable references, not from the provider schema's `Sensitive: true` declarations. When resources are refreshed and planned, the absence of schema-defined sensitive marks causes an asymmetry in mark comparisons, triggering spurious Update actions even when values haven't changed.

## Root Cause

The root cause spans multiple layers:

1. **State serialization gap**: Provider responses don't include sensitivity marks (providers don't mark values). When encoding state, the code extracts marks from the value and stores them in `AttrSensitivePaths`, but only variable-based marks exist on the value at save time—schema marks were never applied.

2. **Mark restoration incomplete**: When state is decoded and during refresh, only the stored marks from `AttrSensitivePaths` are re-applied. Schema marks are never restored at the state layer.

3. **Asymmetric mark comparison in plan**: During planning, a second check (line 1208 of `node_resource_abstract_instance.go`) compares marks between prior and planned values even when values are identical. If marks differ, the action is upgraded from `NoOp` to `Update`.

4. **Evaluator compensation creates asymmetry**: The evaluator's `GetResource()` method applies schema marks when values are read for expression evaluation, but this happens in the expression evaluation path, not when currentState is passed to the plan function. This creates an asymmetry where:
   - `priorPaths` (from state): contains only variable marks
   - `unmarkedPaths` (from config): contains marks from the configuration
   - These can differ due to different variable references or schema mark application

## Evidence

### File: `internal/states/instance_object.go` (lines 94-137)

The `Encode()` method extracts marks at save time:
```go
// Line 98-99: Extract marks from value
val, pvm := o.Value.UnmarkDeepWithPaths()

// Line 131: Save only the marks that existed on the value
AttrSensitivePaths: pvm,
```

**Problem**: If a provider returns an unmarked value for a schema-sensitive attribute, no mark is extracted. Schema marks are only on values when applied by the evaluator downstream.

### File: `internal/states/instance_object_src.go` (lines 77-104)

The `Decode()` method restores only stored marks:
```go
// Lines 89-90: Re-apply stored marks from state file
if os.AttrSensitivePaths != nil {
    val = val.MarkWithPaths(os.AttrSensitivePaths)
}
```

**Problem**: No schema marks are restored because they were never recorded in the state file.

### File: `internal/terraform/node_resource_abstract_instance.go` (lines 580-723)

The `refresh()` method handles prior marks:
```go
// Lines 623-626: Extract marks from prior state value
var priorPaths []cty.PathValueMarks
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()
}

// Lines 718-720: Re-apply only variable marks to refreshed value
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)
}
```

**Problem**: Only variable marks (from state) are re-applied. Schema marks are never added.

### File: `internal/terraform/node_resource_abstract_instance.go` (lines 1199-1210)

The `plan()` method triggers phantom Updates:
```go
// Lines 1082-1083: Unmarked values are equal (no actual change)
eqV := unmarkedPlannedNewVal.Equals(unmarkedPriorVal)
eq := eqV.IsKnown() && eqV.True()

// Line 1090-1091: Action is set to NoOp
case eq && !matchedForceReplace:
    action = plans.NoOp

// Lines 1199-1210: But then marks are compared
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update
}
```

**Problem**: Even though values are identical, different mark sets (variable vs. schema) trigger an Update action.

### File: `internal/terraform/evaluate.go` (lines 689-693, 714-723)

The evaluator applies schema marks when reading resources:
```go
// Lines 689-693: For planned objects
if schema.ContainsSensitive() {
    afterMarks = append(afterMarks, schema.ValueMarks(val, nil)...)
}

// Lines 714-723: For current state objects
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(val, nil)...)
    val = val.MarkWithPaths(marks)
}
```

**Key finding**: Schema marks are only applied by the evaluator when resources are read for expression evaluation. They are NOT applied when:
- State is decoded from disk
- Refresh returns values to the plan node
- The plan node compares prior vs. planned values

### File: `internal/terraform/marks.go` (lines 17-58)

Mark comparison and filtering functions:
```go
// Lines 17-26: Filter marks that don't apply to a value
func filterMarks(val cty.Value, marks []cty.PathValueMarks) []cty.PathValueMarks {
    var res []cty.PathValueMarks
    for _, mark := range marks {
        if _, err := mark.Path.Apply(val); err == nil {
            res = append(res, mark)
        }
    }
    return res
}

// Lines 31-58: Compare mark sets for equality
func marksEqual(a, b []cty.PathValueMarks) bool {
    // ... checks if two mark sets are identical ...
}
```

These are called from line 1208 to detect mark differences.

### File: `internal/command/jsonstate/state.go` (lines 402-411)

JSON output generation applies schema marks at presentation layer:
```go
// Lines 402-406: JSON output applies schema marks on-demand
value, marks := riObj.Value.UnmarkDeepWithPaths()
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(value, nil)...)
}
s := SensitiveAsBool(value.MarkWithPaths(marks))
```

**Key finding**: The JSON output "compensates" by applying schema marks when generating output, but these marks don't exist in the state file itself. This is why `terraform show -json` shows complete `sensitive_values` even though the state file doesn't have schema marks recorded.

## Affected Components

1. **`internal/states/`**: State serialization (encode/decode) only stores variable-based marks
2. **`internal/terraform/node_resource_abstract_instance.go`**: Refresh and plan functions don't apply schema marks; phantom diff detection (lines 1199-1210)
3. **`internal/terraform/evaluate.go`**: Only the expression evaluator applies schema marks, creating asymmetry
4. **`internal/terraform/marks.go`**: Mark comparison triggers Update actions on mark differences
5. **`internal/command/jsonstate/`**: Compensates at presentation layer but doesn't fix root cause

## Causal Chain

1. **Provider response**: Provider returns resource value WITHOUT any sensitivity marks (correct behavior—providers don't mark values)

2. **State encoding**: The value's marks are extracted and stored in `AttrSensitivePaths`. If the value has marks from sensitive variables, those are stored. But schema-defined marks are NOT on the value, so they are NOT stored.

3. **State file persistence**: `sensitive_attributes` in the state file contains only variable-based marks. Schema marks are completely absent.

4. **State decoding**: When state is read, the stored marks (variable marks only) are re-applied via `Decode()`. Schema marks are not re-applied because they don't exist in the stored state.

5. **Refresh execution**: The prior value (with variable marks) is sent to the provider. The response (unmarked) is received. Prior marks are extracted and re-applied to the refreshed value. The refreshed state has variable marks but NOT schema marks.

6. **Plan execution**: The currentState (from refresh) is passed with variable marks only. Configuration is evaluated. Provider is called. Response is unmarked and re-applied with config marks.

7. **Mark comparison**: Line 1208 compares marks between prior (variable marks) and planned (config marks). These can differ even though values are identical.

8. **Phantom Update**: If marks are different, the action is upgraded from `NoOp` to `Update`, creating a phantom in-place change.

9. **JSON output manifestation**: When `terraform show -json` is run, the jsonstate layer applies schema marks on-demand, creating complete `sensitive_values`. But the state file itself never had these schema marks, so they are lost across Terraform runs.

## Recommendation

The fix requires recording schema-defined sensitive marks in the state file itself. Three approaches are possible:

1. **Record schema marks at encode time** (cleanest): Modify `instance_object.go::Encode()` to:
   - Accept the resource schema as a parameter
   - Apply schema marks to the value before extraction
   - Store both variable and schema marks in `AttrSensitivePaths`
   - This requires threading the schema through the encode pipeline

2. **Apply schema marks at decode time** (moderate): Modify `instance_object_src.go::Decode()` to:
   - Accept the resource schema as a parameter
   - Apply schema marks after restoring stored marks
   - Risk: breaks the current contract that Decode() knows nothing about schema

3. **Fix the asymmetry in plan comparison** (band-aid): Modify `node_resource_abstract_instance.go::plan()` to:
   - Apply schema marks to currentState.Value before comparison
   - Requires accessing schema in the plan function
   - Doesn't fix root cause: schema marks still absent from state file

**Diagnostic steps**:
1. Add logging in `instance_object.go::Encode()` to log whether `schema.ContainsSensitive()` is true
2. Add logging in `instance_object_src.go::Decode()` to show what marks are being restored
3. Add logging in `node_resource_abstract_instance.go::plan()` line 1208 to show `priorPaths` vs. `unmarkedPaths` when mark mismatch is detected
4. Check if schema marks are ever present on values when Encode() is called
5. Compare mark sets in a test case with schema-sensitive attributes but no sensitive variable references

