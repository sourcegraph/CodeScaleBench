# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place update diffs for resources with provider-schema-defined sensitive attributes because sensitivity marks from the provider schema are applied inconsistently during the refresh, plan, and state serialization cycle. The marks are applied at expression evaluation time but not preserved through state encoding/decoding, creating an asymmetry between what the plan comparison sees and what gets displayed.

## Root Cause

The root cause lies in the **incomplete serialization of sensitivity metadata to state** combined with **inconsistent mark application during refresh and plan phases**:

1. **State Serialization Gap** (`internal/states/instance_object.go:94-137`):
   - When a resource value is encoded for state storage via `Encode()`, only the marks currently ON the value are extracted and saved as `AttrSensitivePaths`
   - However, the value at encode time has only **variable-based sensitivity marks** (from `var.db_password` being sensitive), NOT schema-defined marks (from the provider schema declaring `password` attribute as `Sensitive: true`)
   - The provider schema marks are applied LATER during expression evaluation, not during encoding

2. **Schema Mark Application Asymmetry** (`internal/terraform/evaluate.go:718-723`):
   - Only ONE location applies schema-defined sensitivity marks: `GetResource()` in the evaluator
   - This is called when evaluating resource references in expressions, NOT during the plan comparison
   - The applied marks are never persisted to state

3. **Refresh Path Doesn't Preserve Schema Marks** (`internal/terraform/node_resource_abstract_instance.go:578-723`):
   - `refresh()` unmarked the prior value (line 625), sends it to provider, then re-marks with ONLY the original marks (line 719)
   - These "original marks" come from `AttrSensitivePaths` in state (applied during Decode), which lack schema-defined marks
   - After refresh, the value still has no schema-defined marks

4. **JSON Output Manifestation** (`internal/command/` layer):
   - `terraform show -json` output reads `sensitive_attributes` from state's `AttrSensitivePaths`
   - Since schema marks are not stored in state, they're missing from the JSON's `sensitive_values` section
   - This creates incomplete sensitivity metadata in plan/state JSON output

## Evidence

### Key Code Locations

**1. State Encoding (instance_object.go:94-137)**
```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    // Line 98: Only extracts marks ON the value at encode time
    val, pvm := o.Value.UnmarkDeepWithPaths()

    // Line 131: Saves only these extracted marks to state
    AttrSensitivePaths:  pvm,
}
```
This saves only the marks currently on the value. Schema-defined marks have not been applied yet.

**2. State Decoding (instance_object_src.go:77-104)**
```go
func (os *ResourceInstanceObjectSrc) Decode(ty cty.Type) (*ResourceInstanceObject, error) {
    val, err = ctyjson.Unmarshal(os.AttrsJSON, ty)
    // Lines 89-91: Applies only the marks that were saved in state
    if os.AttrSensitivePaths != nil {
        val = val.MarkWithPaths(os.AttrSensitivePaths)
    }
    return &ResourceInstanceObject{Value: val, ...}
}
```
Only applies the incomplete marks from state.

**3. Refresh Path (node_resource_abstract_instance.go:620-720)**
```go
// Line 625: Extract marks from prior value (which only has variable-based marks from state)
priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()

// Lines 636-641: Call provider with unmarked value (no marks to provider)
resp = provider.ReadResource(providers.ReadResourceRequest{
    PriorState: priorVal,  // Unmarked
    ...
})

// Lines 719: Re-apply only the marks that were extracted
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)
}
```
The refreshed value never gets schema marks because `priorPaths` doesn't contain them.

**4. Schema Mark Application (evaluate.go:718-723)**
```go
// This is the ONLY place where schema marks are applied
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(val, nil)...)  // Adds schema marks
    val = val.MarkWithPaths(marks)
}
```
This code is in `GetResource()`, called only during expression evaluation, NOT during plan comparison.

**5. Plan Comparison (node_resource_abstract_instance.go:1208-1210)**
```go
// Phantom update triggered by mark differences
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update
}
```
If marks don't match (even if underlying values do), the action changes to Update.

## Affected Components

1. **`internal/terraform/node_resource_abstract_instance.go`**
   - `refresh()` method (lines 580-723): Re-applies marks without schema marks
   - `plan()` method (lines 725-1268): Compares marks and triggers phantom updates
   - `writeResourceInstanceState()` and `writeResourceInstanceStateImpl()` (lines 267-359): Encodes state

2. **`internal/states/instance_object.go`**
   - `Encode()` method (lines 94-137): Extracts only present marks, loses schema-defined marks

3. **`internal/states/instance_object_src.go`**
   - `Decode()` method (lines 77-104): Applies only the incomplete marks from state

4. **`internal/terraform/evaluate.go`**
   - `GetResource()` method (lines 541-799): Only place where schema marks are applied
   - Creates asymmetry between values used in expressions vs values used in planning

5. **`internal/terraform/marks.go`**
   - `marksEqual()` function (lines 29-58): Compares marks, treating presence/absence of schema marks as a difference

6. **`internal/command/` (JSON output layer)**
   - Serializes `sensitive_attributes` from state (missing schema marks) to JSON `sensitive_values`

## Causal Chain

1. **Resource Creation**: Provider returns value WITHOUT any marks (providers don't mark)

2. **Mark Re-application in Refresh**: Only variable-based marks from prior state are re-applied (schema marks never were in prior state)

3. **State Encoding**: Marks are extracted and saved to `AttrSensitivePaths`
   - **Gap**: Schema-defined marks are NOT on the value yet, so not saved

4. **State Persistence**: State file written with `AttrSensitivePaths` containing only variable marks
   - **Result**: Schema sensitivity information is permanently lost in state

5. **State Decoding (Plan Phase)**: `Decode()` applies marks from `AttrSensitivePaths`
   - **Result**: Decoded value has only variable-based marks

6. **Refresh in Plan Phase**: `refresh()` unmarked and re-marks with original marks
   - **Result**: Refreshed value still has only variable-based marks

7. **Provider Plan Response**: Provider returns planned value WITHOUT marks

8. **Plan Marking**: Planned value is marked with config marks (variable-based only)
   - **Result**: Planned value has variable marks

9. **Expression Evaluation** (separate path): `GetResource()` is called
   - **Action**: Applies schema marks to value
   - **Result**: Values used in expressions have BOTH variable and schema marks

10. **Plan Comparison**: Values without schema marks are compared
    - **Result**: No phantom update detected

11. **Plan Display/Evaluation**: Values with schema marks are used
    - **Result**: Sensitivity marks differ from what plan comparison determined
    - **Symptom**: Phantom update appears in output

12. **JSON Output**: State serialization uses values without schema marks
    - **Result**: `sensitive_values` in JSON is incomplete
    - **Symptom**: Missing sensitive attributes in `terraform show -json`

## Recommendation

### Fix Strategy

The asymmetry can be resolved by **applying schema-defined sensitivity marks consistently at the point where values enter the plan evaluation cycle**. Two possible approaches:

1. **Option A: Apply schema marks earlier in refresh** (least breaking)
   - In `refresh()` method (line 719), after re-applying `priorPaths`, also apply schema marks
   - Store schema marks in state via `Encode()` (but this requires state format changes)
   - Pro: Minimal changes, works with current state format
   - Con: Need to carry schema context through refresh

2. **Option B: Apply schema marks in plan evaluation** (more comprehensive)
   - After `plan()` creates the change object, apply schema marks to both Before and After values
   - Similar to what `GetResource()` does, but for plan comparison
   - Pro: Centralizes schema mark application
   - Con: More changes, potential for other asymmetries

3. **Option C: Include schema mark information in state** (most correct)
   - Extend state file format to record which attributes are schema-sensitive
   - Applied during Decode() like variable marks
   - Pro: Complete solution, survives state serialization
   - Con: Requires state migration, larger state files

### Diagnostic Steps

To verify this hypothesis:

1. **Trace mark propagation**: Log when marks are applied/removed through refresh and plan phases
2. **Check `AttrSensitivePaths`**: Verify that state file's `AttrSensitivePaths` never contains schema-defined paths
3. **Compare Before/After marks in change**: Check if the `ResourceInstanceChange` object has different marks than what plan comparison determined
4. **Review `terraform show -json` output**: Confirm `sensitive_values` lacks schema-defined attributes
5. **Add schema marks to refresh**: Temporarily apply schema marks in refresh() and verify phantom updates disappear
