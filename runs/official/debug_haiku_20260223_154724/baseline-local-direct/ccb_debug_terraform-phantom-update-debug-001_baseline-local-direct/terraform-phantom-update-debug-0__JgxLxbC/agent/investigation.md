# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place updates for resources with provider-schema-defined sensitive attributes because the system has a fundamental **asymmetry in how sensitivity marks are applied during state serialization vs. expression evaluation**. Schema-defined `Sensitive: true` attributes are never stored in state files but are applied on-the-fly during expression evaluation, creating a hidden mark disparity that the planning system interprets as a change even when underlying attribute values are identical.

## Root Cause

The root cause is a **three-layer mark management asymmetry**:

1. **State Encoding Layer** (`internal/states/instance_object.go:Encode`): Only stores marks that exist on the value at write time (from configuration variable references). Provider schema-defined sensitive paths are never included.

2. **State Decoding Layer** (`internal/states/instance_object_src.go:Decode`): Reapplies only the incomplete marks from `AttrSensitivePaths`, missing schema-defined sensitivities.

3. **Evaluation Layer** (`internal/terraform/evaluate.go:GetResource`): Applies schema marks on-the-fly when retrieving resource values for expression evaluation, but this only happens for resources referenced in expressions.

4. **Planning Comparison Layer** (`internal/terraform/node_resource_abstract_instance.go:plan`): Compares sensitivity marks between prior state and planned state, detecting a "change" when one side has schema marks and the other doesn't, even though the underlying values are identical.

## Evidence

### 1. State Serialization (Incomplete Marks Stored)

**File**: `internal/states/instance_object.go:94-137`

```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    // Line 98: Only marks currently on the value are extracted
    val, pvm := o.Value.UnmarkDeepWithPaths()

    // ... value is serialized without marks ...

    // Line 131: Only the extracted marks are stored in state
    return &ResourceInstanceObjectSrc{
        SchemaVersion:       schemaVersion,
        AttrsJSON:           src,
        AttrSensitivePaths:  pvm,  // INCOMPLETE: Missing schema-defined marks
        ...
    }, nil
}
```

**Problem**: Provider schema `Sensitive: true` declarations are NEVER marked on values during planning/apply, so they cannot be extracted and stored in state.

### 2. State Deserialization (Same Incomplete Marks Reapplied)

**File**: `internal/states/instance_object_src.go:77-104`

```go
func (os *ResourceInstanceObjectSrc) Decode(ty cty.Type) (*ResourceInstanceObject, error) {
    val, err := ctyjson.Unmarshal(os.AttrsJSON, ty)
    if os.AttrSensitivePaths != nil {
        // Line 90: Reapplies only the marks that were stored in AttrSensitivePaths
        val = val.MarkWithPaths(os.AttrSensitivePaths)
    }

    return &ResourceInstanceObject{
        Value: val,
        ...
    }, nil
}
```

**Problem**: The decoded value lacks schema-defined sensitive marks that should always be present according to the provider schema.

### 3. Provider Response Lacks Marks

**File**: `internal/terraform/node_resource_abstract_instance.go:881-910`

```go
// Line 902: Provider returns a response without any marks
resp = provider.PlanResourceChange(providers.PlanResourceChangeRequest{
    TypeName:         n.Addr.Resource.Resource.Type,
    Config:           unmarkedConfigVal,
    PriorState:       unmarkedPriorVal,
    ProposedNewState: proposedNewVal,
    PriorPrivate:     priorPrivate,
    ProviderMeta:     metaConfigVal,
})

// Line 916: Planned state has no marks initially
plannedNewVal := resp.PlannedState
```

**Context**: Providers are RPC/plugin boundaries that never understand Terraform's sensitivity marks. They only return raw values.

### 4. Marks from Config References Are Reapplied (But Incomplete)

**File**: `internal/terraform/node_resource_abstract_instance.go:859-1000`

```go
// Line 868-869: Extract marks from both config and prior
unmarkedConfigVal, unmarkedPaths := configValIgnored.UnmarkDeepWithPaths()
unmarkedPriorVal, priorPaths := priorVal.UnmarkDeepWithPaths()

// Lines 998-1000: Reapply config marks to planned value
if len(unmarkedPaths) > 0 {
    plannedNewVal = plannedNewVal.MarkWithPaths(unmarkedPaths)
}

// priorPaths contains marks from AttrSensitivePaths (config refs only)
```

**Problem**:
- `unmarkedPaths` = config reference sensitivity marks only
- `priorPaths` = marks from prior state (also config refs only)
- Neither includes schema-defined sensitive marks

### 5. Refresh Path (Same Asymmetry)

**File**: `internal/terraform/node_resource_abstract_instance.go:580-723`

```go
// Line 620: Get prior value from state
priorVal := state.Value

// Lines 623-626: Extract ALL marks before sending to provider
if priorVal.ContainsMarked() {
    priorVal, priorPaths = priorVal.UnmarkDeepWithPaths()
}

// Line 636: Provider returns unmarked response
resp = provider.ReadResource(providers.ReadResourceRequest{
    TypeName:     n.Addr.Resource.Resource.Type,
    PriorState:   priorVal,
    ...
})

// Lines 718-720: Re-apply ONLY the extracted marks (incomplete)
if len(priorPaths) > 0 {
    ret.Value = ret.Value.MarkWithPaths(priorPaths)
}
```

**Problem**: Refreshed value never gets schema marks, even though the resource schema defines them.

### 6. Compensating Workaround in Expression Evaluation

**File**: `internal/terraform/evaluate.go:718-723`

```go
// This is ONLY applied when retrieving resources for evaluation
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    // Add schema marks on-the-fly
    marks = append(marks, schema.ValueMarks(val, nil)...)
    val = val.MarkWithPaths(marks)
}
instances[key] = val
```

**Purpose**: When resources are referenced in expressions (like in outputs or locals), schema marks are applied. But this happens ONLY during expression evaluation, not during state management.

### 7. The Asymmetry Triggers Phantom Updates

**File**: `internal/terraform/node_resource_abstract_instance.go:1208-1210`

```go
// Line 1082: Underlying values are equal
eqV := unmarkedPlannedNewVal.Equals(unmarkedPriorVal)
eq := eqV.IsKnown() && eqV.True()

// ... if eq && !matchedForceReplace, action = plans.NoOp

// Line 1208-1210: BUT if marks differ, change to Update
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update
}
```

**The Phantom Diff Trigger**:
- If prior state was evaluated/saved when GetResource was called, it might have schema marks
- But the planned value only has config reference marks
- The mark comparison detects they differ
- Even though values are identical, action changes from NoOp to Update

### 8. Incomplete JSON Output

**File**: `internal/command/jsonstate/state.go:402-411`

```go
value, marks := riObj.Value.UnmarkDeepWithPaths()
if schema.ContainsSensitive() {
    // Schema marks ARE added here for JSON output
    marks = append(marks, schema.ValueMarks(value, nil)...)
}
s := SensitiveAsBool(value.MarkWithPaths(marks))
v, err := ctyjson.Marshal(s, s.Type())
current.SensitiveValues = v
```

**Symptom**: JSON output correctly shows schema-defined sensitive attributes as sensitive, but the underlying state object that was used to generate that JSON doesn't actually have those marks stored in `AttrSensitivePaths`.

## Affected Components

1. **`internal/states/` (State Management)**
   - `instance_object.go`: Encode/Decode logic
   - `instance_object_src.go`: State serialization
   - Controls what marks are stored in state files

2. **`internal/terraform/node_resource_abstract_instance.go` (Graph Evaluation)**
   - `plan()` method (lines 725-1250): Primary planning logic
   - `refresh()` method (lines 580-723): State refresh logic
   - Lines 1208-1210: The comparison that triggers phantom updates

3. **`internal/terraform/evaluate.go` (Expression Evaluation)**
   - `GetResource()` method (lines 541-800): Applies schema marks only during evaluation
   - Lines 718-723: The compensating workaround

4. **`internal/terraform/marks.go` (Mark Comparison)**
   - `marksEqual()`: Compares mark sets
   - `filterMarks()`: Filters applicable marks

5. **`internal/command/jsonstate/state.go` (JSON Output)**
   - Lines 402-411: Applies schema marks for JSON output only
   - Creates illusion of complete sensitivity info

## Causal Chain

1. **Initial Setup**: Provider schema defines `Sensitive: true` for certain attributes (e.g., `password`, `secret_key`)

2. **First Apply**:
   - User applies configuration with sensitive attributes
   - Provider response has no marks (RPC boundary)
   - If config references sensitive variable: marks from variable sensitivity are applied to planned value
   - State is written via `Encode()`: marks are extracted and stored in `AttrSensitivePaths`
   - **BUT**: Schema-defined sensitive marks are never applied to planned value, so they're never stored

3. **Subsequent Plan** (no config changes):
   - State is read via `readResourceInstanceState()` and `Decode()`
   - Only marks from `AttrSensitivePaths` are reapplied (config references only)
   - `refresh()` is called, marks are extracted and reapplied
   - `plan()` is called with refreshed state as prior
   - Provider returns unchanged value (no marks)
   - Config marks are reapplied to planned value
   - Comparison at line 1208: `marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths)`
   - If marks differ (due to schema vs reference mark sources), action changes from NoOp to Update

4. **Mark Source Mismatch**:
   - Prior marks: From `AttrSensitivePaths` (config references + any prior schema marks that shouldn't exist)
   - Planned marks: Only from `unmarkedPaths` (current config references)
   - If config marks changed or if prior state was processed differently, they won't match

5. **Root Enabler**: The core issue is that schema marks are NEVER applied to values during planning/state cycles. They're only applied during expression evaluation (GetResource). This creates:
   - **State has incomplete marks**: Missing schema-defined sensitivities
   - **Planned values have incomplete marks**: Only config reference sensitivities
   - **Evaluation has complete marks**: But only for evaluated expressions
   - **Comparison detects asymmetry**: Even when values are identical

## Recommendation

**Fix Strategy**: The system needs to treat schema-defined sensitive attributes consistently throughout the planning and state management lifecycle:

1. **Option A (Recommended - Minimal Impact)**: Apply schema marks earlier in planning cycle
   - In `plan()`: After receiving provider response, apply schema marks to `plannedNewVal` before comparison
   - In `refresh()`: After receiving provider response, apply schema marks to refreshed value
   - This ensures both before and after have the same mark sources during comparison

2. **Option B (More Complete)**: Store schema-aware marks in state
   - Modify `Encode()` to include schema-defined sensitive marks in `AttrSensitivePaths`
   - This requires passing schema to Encode, currently unavailable
   - Would make state files self-describing regarding sensitivity

3. **Option C (Breaking Change)**: Don't compare marks, only values
   - Remove the mark comparison at line 1208
   - Accept that sensitivity metadata differences shouldn't trigger updates
   - Requires audit of whether mark changes have semantic meaning

**Diagnostic Steps to Verify**:

1. Add logging to `plan()` at line 1208 to print both mark sets
2. Check if marks differ when values are identical
3. Trace mark sources: are they from schema or from config references?
4. Compare mark sets from `filterMarks(plannedNewVal, unmarkedPaths)` vs `priorPaths`
5. In `GetResource()`, note which resources receive schema marks during evaluation
6. Check state files to confirm `AttrSensitivePaths` lacks schema-defined sensitive attribute paths

**Test Case**:
- Create resource with provider schema attribute marked `Sensitive: true`
- Don't reference that attribute from any sensitive variables
- Apply configuration
- Run plan immediately without config changes
- Verify no "will be updated" appears

The issue manifests most clearly with:
- Resources having schema-sensitive attributes not referenced from sensitive variables
- Imported resources (no prior mark history)
- Resources with provider-level sensitivity different from variable-level sensitivity
