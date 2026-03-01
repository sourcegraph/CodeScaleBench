# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place updates for resources with provider-schema-defined sensitive attributes because the refresh/plan cycle creates an asymmetry in sensitivity mark application. The provider schema's `Sensitive: true` attribute declarations are never persisted to state, causing the evaluator's compensating mark-application logic to create inconsistencies that trigger false "Update" actions when no values have actually changed.

---

## Root Cause

The root cause is a **sensitivity mark gap** between three critical stages:

1. **State Serialization** (`internal/states/instance_object.go`): When state is written to disk, only sensitivity marks from variable references are saved in `AttrSensitivePaths`; schema-defined sensitive attributes are lost.

2. **State Deserialization** (`internal/states/instance_object_src.go`): When state is read, marks are re-applied from the incomplete `AttrSensitivePaths`, lacking schema marks.

3. **Evaluation-Time Compensation** (`internal/terraform/evaluate.go`): The `GetResource()` method applies schema marks when reading from state for expression evaluation, but this compensating layer is NOT applied during plan generation in `node_resource_abstract_instance.go`.

This asymmetry causes the plan phase to compare:
- **Planned state** (from provider, no marks at all)
- **Prior state** (from state file with incomplete marks, only from variables)

When the marks differ even though values don't, a phantom "Update" action is triggered.

---

## Evidence

### 1. Sensitivity Marks Lost During State Encoding

**File:** `internal/states/instance_object.go`, lines 94-136

```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    // Extract marks from value before serialization
    val, pvm := o.Value.UnmarkDeepWithPaths()  // Line 98

    // Convert to JSON (loses all mark information)
    src, err := ctyjson.Marshal(val, ty)       // Line 111

    // Return object with incomplete marks
    return &ResourceInstanceObjectSrc{
        SchemaVersion:      schemaVersion,
        AttrsJSON:          src,                // JSON has NO marks
        AttrSensitivePaths: pvm,                // Only marks from variables
        Private:            o.Private,
        ...
    }, nil
}
```

**Critical Issue:** `pvm` (path-value marks) extracted at line 98 contains ONLY marks that were already on the value—which come from sensitive variable references, NOT from the provider schema's `Sensitive: true` declarations. The provider schema marks were never on the value in the first place because they're only applied during expression evaluation, not during state persistence.

### 2. Incomplete Marks Re-Applied During State Decoding

**File:** `internal/states/instance_object_src.go`, lines 77-104

```go
func (os *ResourceInstanceObjectSrc) Decode(ty cty.Type) (*ResourceInstanceObject, error) {
    var val cty.Value
    ...
    val, err = ctyjson.Unmarshal(os.AttrsJSON, ty)

    // Re-apply marks from state (INCOMPLETE - missing schema marks)
    if os.AttrSensitivePaths != nil {
        val = val.MarkWithPaths(os.AttrSensitivePaths)  // Line 90
    }
    ...
}
```

The value is re-marked with `AttrSensitivePaths`, but these paths are incomplete—they lack any paths from the provider schema's `Sensitive: true`.

### 3. Plan Comparison Without Schema Marks

**File:** `internal/terraform/node_resource_abstract_instance.go`, lines 725-1250

The `plan()` method (called from `managedResourceExecute` at line 250 of `node_resource_plan_instance.go`) handles the plan phase:

```go
// Line 869: Extract marks from prior state (incomplete)
unmarkedPriorVal, priorPaths := priorVal.UnmarkDeepWithPaths()

// Line 871: Create proposed value
proposedNewVal := objchange.ProposedNew(schema, unmarkedPriorVal, unmarkedConfigVal)

// Line 902: Call provider (unmarked values sent)
resp = provider.PlanResourceChange(providers.PlanResourceChangeRequest{
    TypeName:         n.Addr.Resource.Resource.Type,
    Config:           unmarkedConfigVal,
    PriorState:       unmarkedPriorVal,        // No schema marks
    ProposedNewState: proposedNewVal,          // No schema marks
    ...
})

// Line 916: Provider response (no marks)
plannedNewVal := resp.PlannedState

// Line 1082: Compare unmarked values
eqV := unmarkedPlannedNewVal.Equals(unmarkedPriorVal)
eq := eqV.IsKnown() && eqV.True()

// Line 1208: PHANTOM UPDATE TRIGGER
// If values are equal but marks differ, mark as Update
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update
}
```

**Critical Flow:**
- `priorPaths` contains marks extracted from the state value (line 869)
- These marks only include marks from sensitive variable references
- Schema-defined sensitive attributes are NOT in `priorPaths`
- `plannedNewVal` comes from provider with NO marks
- Mark comparison at line 1208 can trigger false positives if schema marks should be present

### 4. Refresh Path Reapplies Incomplete Marks

**File:** `internal/terraform/node_resource_abstract_instance.go`, lines 619-723

The refresh method (called during plan at line 208 of `node_resource_plan_instance.go`):

```go
// Line 620-626: Extract marks before provider call
priorVal := state.Value
var priorPaths []cty.PathValueMarks
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()
}

// Line 636-641: Provider call (unmarked)
resp = provider.ReadResource(providers.ReadResourceRequest{
    TypeName:     n.Addr.Resource.Resource.Type,
    PriorState:   priorVal,      // Unmarked
    Private:      state.Private,
    ProviderMeta: metaConfigVal,
})

// Line 693: New state from provider
ret.Value = newState

// Line 718-720: Reapply original marks (INCOMPLETE)
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)
}
```

**Issue:** The marks reapplied at line 719 are incomplete because `priorPaths` lacks schema marks.

### 5. Evaluator's Compensating Mark Application

**File:** `internal/terraform/evaluate.go`, lines 541-725

The `GetResource()` method applies schema marks when reading from state for expression evaluation:

```go
// Line 718-723: For regular state objects
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()           // Remove existing marks
    marks = append(marks, schema.ValueMarks(val, nil)...)  // Add schema marks
    val = val.MarkWithPaths(marks)
}
```

**Critical Asymmetry:** This compensating mark application happens ONLY during expression evaluation via `GetResource()`, NOT during:
- State decoding for planning
- Provider calls during refresh/plan
- Difference calculation

This creates an asymmetry where:
- Values read FROM state for evaluation have schema marks (via `GetResource()`)
- Values read FROM state during planning don't have schema marks
- Planned values from provider have no marks at all

### 6. JSON Output Manifestation

**File:** `internal/command/jsonplan/resource.go`, line 44

The `SensitiveValues` field in JSON plan output reflects only the marks saved in state:

```go
SensitiveValues json.RawMessage `json:"sensitive_values,omitempty"`
```

These are derived from state's `AttrSensitivePaths` (via the plan's change tracking), which lacks schema-defined sensitive paths. This produces incorrect `sensitive_values` in `terraform show -json` output.

---

## Affected Components

1. **`internal/states/instance_object.go`** - Encodes state, loses schema marks
2. **`internal/states/instance_object_src.go`** - Decodes state, applies incomplete marks
3. **`internal/terraform/node_resource_abstract_instance.go`** - Plan generation without schema marks
   - `plan()` method (line 725+)
   - `refresh()` method (line 580+)
   - Mark comparison at line 1208
4. **`internal/terraform/evaluate.go`** - Compensating schema mark application only during evaluation
   - `GetResource()` method (line 541+)
5. **`internal/command/jsonplan/`** - JSON output reflects incomplete sensitivity information
6. **`internal/marks.go`** - Mark equality comparison (`marksEqual()`, `filterMarks()`)

---

## Causal Chain

1. **Provider Response Boundary:** Provider returns `ReadResource` / `PlanResourceChange` response with **no sensitivity marks** (providers don't mark values; Terraform does).

2. **State Persistence Gap:** When state is encoded via `instance_object.Encode()`, only marks that are already on the value are persisted. Schema-defined sensitive marks were never on the value because they're only applied during expression evaluation, so they're lost forever.

3. **Incomplete State Reading:** When state is decoded via `instance_object_src.Decode()`, the re-marked value only has marks from sensitive variable references (stored in `AttrSensitivePaths`), not from schema.

4. **Plan Without Compensation:** During planning in `node_resource_abstract_instance.plan()`, the code:
   - Extracts incomplete marks from prior state
   - Calls provider with unmarked values
   - Receives unmarked planned value from provider
   - Compares marks at line 1208, detecting "changes" that are just missing schema marks

5. **Evaluation-Time Asymmetry:** During expression evaluation (via `GetResource()` in evaluate.go), schema marks ARE applied, but only for expressions—not for plan comparison.

6. **Phantom Diff Manifestation:** The plan detects a "change" (NoOp → Update at line 1209) because:
   - The planned value has no marks
   - The prior value has only variable-reference marks
   - Schema marks are absent from both, but the comparison logic doesn't know they should be there

7. **JSON Output Inaccuracy:** When the plan is serialized to JSON or state, `sensitive_values` reflects only variable-reference sensitivity, omitting schema-defined sensitive attributes.

---

## Diagnostic Evidence

**When phantom updates occur:**
- `terraform plan` immediately after `terraform apply` shows "will be updated in-place"
- `terraform show -json` shows incomplete `sensitive_values` lacking schema-marked attributes
- `terraform plan -refresh-only` also shows phantom changes
- The phantom diff disappears if no provider-schema attributes are marked `Sensitive: true`

**Root Cause Signature:**
- State file's `sensitive_attributes` lists only paths from variable references
- Missing paths for all schema-defined `Sensitive: true` attributes
- Plan comparison detects mark differences even though underlying values are identical

---

## Recommendation

### Fix Strategy

The core fix requires synchronizing the three stages to use the same mark-application logic:

1. **Apply Schema Marks During State Deserialization** - NOT just during expression evaluation:
   - In `instance_object_src.Decode()`, after unmarking and remarking with `AttrSensitivePaths`, apply schema marks unconditionally
   - This ensures that state values always carry complete mark information

2. **Persist Complete Marks to State** - Include schema marks in serialization:
   - Before encoding state in `instance_object.Encode()`, compute and include schema marks in addition to variable-reference marks
   - This requires passing the schema to the encode operation (currently it doesn't have access)

3. **Alternative: Skip Mark Comparison for NoOp Actions**:
   - Remove or modify the check at line 1208 that triggers updates based on mark differences alone
   - Only treat as Update if actual value changes, not mark-only differences (already done for UnmarkDeep at line 1049-1052)

### Diagnostic Steps

1. Check state file's `sensitive_attributes` section:
   - Should include paths for ALL schema-defined `Sensitive: true` attributes
   - Not just those from variable references

2. Compare before/after sensitivity in plan:
   - `terraform plan -json` should show schema-defined attributes in `sensitive_values`

3. Verify evaluator marks match persistence:
   - Schema marks applied in `GetResource()` should match marks in state

---

## Impact Assessment

This issue affects:
- Any provider with schema attributes marked `Sensitive: true`
- User confidence in plan accuracy (false positives)
- State file accuracy (incomplete sensitivity information)
- JSON output completeness (missing sensitivity metadata)

The fix would require careful coordination between:
- State serialization/deserialization layer
- Plan generation layer
- Provider schema application layer
- Expression evaluation layer
