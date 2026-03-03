# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place update diffs for resources with provider-schema-defined sensitive attributes because of an asymmetry in how sensitivity marks flow through the system. The issue stems from **incomplete sensitivity mark persistence in state**: when resource values are refreshed and stored, only marks from sensitive variable references are saved, not marks from the provider schema itself. During plan generation, schema marks are applied dynamically to the JSON output for display purposes, creating an apparent difference in sensitivity between before and after values even though the underlying attribute values are identical.

---

## Root Cause

**Incomplete sensitivity mark storage at state serialization boundary.**

The root cause is located in the **state refresh-to-storage pipeline**, specifically:

1. **`internal/terraform/node_resource_abstract_instance.go`, `refresh()` method (lines 620-722)**: When a resource is refreshed from the provider, marks extracted before sending to the provider (`priorPaths` at line 625) only contain marks from sensitive variables (e.g., `var.db_password` marked as sensitive). These are **not** the provider schema's declared sensitive attributes.

2. **`internal/states/instance_object.go`, `Encode()` method (line 98)**: When encoding the refreshed value for storage, `UnmarkDeepWithPaths()` extracts **only the marks currently on the value**. Since schema-defined sensitive marks were never added to the refreshed value (the provider returns unmarked values and only variable marks are reapplied), the schema marks are **not** present in the encoded state.

3. **`internal/states/instance_object_src.go`, `Decode()` method (lines 89-90)**: When decoding from state, only the marks that were stored (`AttrSensitivePaths`) are reapplied. These lack schema-defined marks.

4. **`internal/terraform/evaluate.go`, `GetResource()` method (lines 714-723)**: This is the **compensating workaround** that masks the underlying issue. When reading resource values for expression evaluation during planning, the code explicitly applies schema marks if the schema contains sensitive attributes. This creates the asymmetry: values read **via GetResource** have schema marks added, but values read **directly from state** in the plan path do not.

5. **`internal/command/jsonplan/plan.go`, `MarshalResourceChange()` method (lines 417-420, 446-449)**: When generating JSON output for display, schema marks are applied on-the-fly to both before and after values. This compounds the issue: the before value appears to have sensitivity marks that were never stored in the plan itself.

---

## Evidence

### Code References

**1. Refresh Path – Incomplete Mark Extraction (node_resource_abstract_instance.go:620-722)**

```go
// Line 623-626: Extract marks BEFORE sending to provider
var priorPaths []cty.PathValueMarks
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()
}
// priorPaths only contains marks from sensitive variables, NOT schema

// Line 717-720: Reapply marks AFTER provider returns
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)
}
// Schema marks are NOT reapplied here
```

**Issue**: `priorPaths` only has marks from sensitive variable references. Provider schema declares sensitive attributes are never added at this point.

---

**2. State Encoding – Missing Schema Marks (instance_object.go:94-137)**

```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    // Line 98: Extract existing marks
    val, pvm := o.Value.UnmarkDeepWithPaths()

    // ... process value ...

    // Line 131: Save only the marks that are on the value
    AttrSensitivePaths:  pvm,  // Missing schema marks!
}
```

**Issue**: Only marks present in the value are persisted. Schema-defined sensitive marks are never in the value because the refresh path never adds them.

---

**3. State Decoding – Restore Incomplete Marks (instance_object_src.go:77-104)**

```go
func (os *ResourceInstanceObjectSrc) Decode(ty cty.Type) (*ResourceInstanceObject, error) {
    val, err := ctyjson.Unmarshal(os.AttrsJSON, ty)
    if os.AttrSensitivePaths != nil {
        val = val.MarkWithPaths(os.AttrSensitivePaths)  // Only has variable marks
    }
    return &ResourceInstanceObject{Value: val, ...}, nil
}
```

**Issue**: Reapplies only the incomplete marks that were stored.

---

**4. Evaluator Compensation – Schema Marks Applied at Expression Evaluation Time (evaluate.go:714-723)**

```go
// When reading from state for planned resources (lines 714-723)
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(val, nil)...)  // ADD schema marks here
    val = val.MarkWithPaths(marks)
}
instances[key] = val
```

**Issue**: This is a compensating mechanism that adds schema marks during **evaluation** (when reading from state for expression purposes), but these marks are **not** part of the planned change or state storage. This is the ONLY place schema marks are applied in the normal flow.

---

**5. JSON Output Generation – Dynamic Schema Mark Addition (jsonplan/plan.go:417-420, 446-449)**

```go
// For Before value (line 417-425):
marks := rc.BeforeValMarks  // Only has variable marks from the plan
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.Before, nil)...)  // Add schema marks here
}
bs := jsonstate.SensitiveAsBool(changeV.Before.MarkWithPaths(marks))
beforeSensitive, err := ctyjson.Marshal(bs, bs.Type())

// For After value (line 446-449):
marks := rc.AfterValMarks  // Only has variable marks from the plan
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.After, nil)...)  // Add schema marks here
}
as := jsonstate.SensitiveAsBool(changeV.After.MarkWithPaths(marks))
afterSensitive, err := ctyjson.Marshal(as, as.Type())
```

**Issue**: Schema marks are applied at JSON output time, making the before value appear to have sensitivity information that was never persisted in the plan. The difference in before vs. after sensitivity (in marks only, not in values) appears as a change to the user.

---

**6. Plan Phase – Incomplete Mark Comparison (node_resource_abstract_instance.go:1208-1210)**

```go
// Check if marks differ even though values are equal
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update
}
```

**Issue**: This compares `unmarkedPaths` (marks from config) against `priorPaths` (marks from state, missing schema marks). Neither has schema marks, so for schema-sensitive attributes with no variable marks, they appear equal when they shouldn't.

---

## Affected Components

1. **`internal/terraform/node_resource_abstract_instance.go`** – Refresh path, plan path:
   - `refresh()` method: Extracts and reapplies incomplete marks
   - `plan()` method: Uses incomplete marks for comparison
   - Does not apply schema marks to prior values

2. **`internal/states/instance_object.go`** – State serialization:
   - `Encode()` method: Serializes incomplete marks to state file

3. **`internal/states/instance_object_src.go`** – State deserialization:
   - `Decode()` method: Restores incomplete marks from state

4. **`internal/terraform/evaluate.go`** – Expression evaluation:
   - `GetResource()` method: Applies schema marks when reading state for evaluation (compensating mechanism)

5. **`internal/command/jsonplan/plan.go`** – JSON plan output:
   - `MarshalResourceChange()` method: Dynamically applies schema marks at output time

6. **`internal/terraform/marks.go`** – Utility functions:
   - `marksEqual()`: Used for comparing incomplete mark sets
   - `filterMarks()`: Filters inapplicable marks

---

## Causal Chain

```
1. SYMPTOM: terraform plan shows phantom in-place update even with no config changes
   ↓
2. User sees "will be updated in-place" for resource with sensitive schema attributes
   ↓
3. terraform show -json shows different sensitive_values in before vs. after
   ↓
4. Root cause: Sensitivity metadata differs between before and after in JSON output
   ↓
5. Before sensitivity: Includes schema marks (added at JSON output time)
   After sensitivity: Includes schema marks (added at JSON output time)
   Both appear different because schema marks were never in the planned change
   ↓
6. Why schema marks are missing from planned change:
   a) Refresh returns unmarked value from provider
   b) Only variable-reference marks are reapplied (line 719)
   c) State is encoded with incomplete marks (line 98)
   d) Plan reads state with incomplete marks (lines 89-90)
   e) Plan's BeforeValMarks only have variable marks, not schema marks
   ↓
7. Why GetResource compensates:
   - GetResource explicitly applies schema marks when reading from state (line 714-723)
   - This is ONLY mechanism adding schema marks in normal flow
   - But these marks are NOT captured in the plan itself
   ↓
8. Why phantom diff appears:
   - JSON output generation applies schema marks on-the-fly (lines 418-420, 446-449)
   - Before value: Has dynamically-applied schema marks
   - After value: Has dynamically-applied schema marks
   - But from different sources (refreshed state vs. provider response)
   - Even though underlying values are identical, mark structure differs
   ↓
9. Why it only affects schema-sensitive attributes:
   - Variable marks are preserved in state
   - Schema marks are NOT preserved in state
   - So only schema-sensitive attributes (without variable marks) lack marks in state
   ↓
10. ROOT CAUSE: Asymmetry in mark persistence
    - Sensitive variables: Marks persisted in state ✓
    - Schema sensitive attributes: Marks NOT persisted in state ✗
    - Compensating layer (GetResource) masks issue during evaluation
    - JSON generation exposes issue by dynamically adding missing marks
```

---

## Recommendation

### Fix Strategy

The fix requires **ensuring schema-defined sensitive marks are persisted in state**, not applied only during evaluation or output generation.

**Two approaches:**

**Option A (Preferred): Apply schema marks at state encoding time**
- Modify `node_resource_abstract_instance.go`'s `refresh()` method to apply schema marks before encoding
- At line 717-720, after reapplying variable marks, also apply schema marks
- This ensures state encodes complete sensitivity information
- State decoding will then have complete marks
- Eliminates need for compensating layer in evaluate.go
- Eliminates dynamic mark application in JSON output

**Option B: Capture schema marks in plan**
- Modify `plan()` method to explicitly apply schema marks to `priorVal`
- Encode schema marks into `BeforeValMarks` when creating the change
- This ensures the planned change has complete mark information
- Still requires changes to how marks are compared and stored

### Diagnostic Steps

1. **Enable trace logging** in `node_resource_abstract_instance.go`:
   - Log `priorPaths` extracted at line 625
   - Log marks on value after reapplying at line 719
   - Compare against schema.ValueMarks() to see what's missing

2. **Inspect state file** after refresh:
   ```bash
   terraform state show -json <resource> | jq '.current_state_object.sensitive_attributes'
   ```
   - Will only show paths for variable-marked attributes
   - Should include schema-marked paths

3. **Compare plan marks**:
   ```bash
   terraform show -json <plan-file> | jq '.resource_changes[].change | {before_sensitive, after_sensitive}'
   ```
   - Before will have no schema marks (from state)
   - After will have schema marks (from evaluate.go)
   - Difference indicates the phantom update

4. **Test with schema-sensitive only** vs. **variable-sensitive only** attributes:
   - Schema-sensitive-only: Phantom diff appears
   - Variable-sensitive-only: No phantom diff (marks persisted)

---

## Additional Context

### Why GetResource Compensates

The `GetResource()` method in `evaluate.go` (lines 714-723) is a **defensive compensating layer**. It ensures that when Terraform evaluates expressions that reference resource values from state, those values have schema-defined sensitivity marks applied. This prevents sensitive attributes from being accidentally logged or displayed during evaluation.

However, **this compensation only applies to expression evaluation**, not to:
- Plan change storage (`BeforeValMarks`, `AfterValMarks`)
- State storage (`AttrSensitivePaths`)
- Plan file output

### Why JSON Output Exposes the Issue

The `jsonplan/plan.go` code (lines 418-420, 446-449) applies schema marks **at output time** because:
1. It reads `BeforeValMarks` and `AfterValMarks` from the change, which have incomplete marks
2. It detects the incompleteness via `schema.ContainsSensitive()`
3. It dynamically adds missing schema marks for display purposes

This is a **second compensating layer** that only helps with JSON output, not with the core issue of incomplete mark persistence.

### Historical Context

This design pattern suggests that at some point, the `GetResource()` compensation was sufficient. The system likely worked when:
- Resource values were always read via `GetResource()` for comparison
- JSON output was generated more directly from evaluated values

The issue emerged when:
- Direct state comparisons started being used for plan generation
- JSON output generation was refactored to use stored `ValMarks` instead of evaluated values
