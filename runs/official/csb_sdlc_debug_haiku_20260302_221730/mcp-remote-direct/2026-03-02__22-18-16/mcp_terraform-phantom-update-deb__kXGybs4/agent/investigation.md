# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary

Terraform generates phantom in-place updates for resources with schema-defined sensitive attributes because provider response values are reconstructed with only **configuration-source sensitivity marks**, missing **schema-defined sensitivity marks**. This mark asymmetry is never stored in state, causing subsequent plan comparisons to detect differences in sensitivity metadata even when attribute values are identical. Additionally, the state file's `sensitive_attributes` records incomplete sensitivity information, omitting schema-defined sensitive paths entirely.

## Root Cause

The root cause spans a **sensitivity mark gap** across four interconnected mechanisms:

1. **Provider responses lack all sensitivity information** — providers return unmarked values
2. **Mark reconstruction omits schema-defined sensitive attributes** — only config-source marks are re-applied
3. **State serialization captures incomplete marks** — `AttrSensitivePaths` only contains marks explicitly on the in-memory value
4. **Plan comparison detects mark differences as attribute changes** — causes NoOp to become Update

## Evidence

### 1. Provider Response Flow (node_resource_abstract_instance.go:902-916)

The provider's `PlanResourceChange` is called with unmarked values and returns unmarked responses:

```go
resp = provider.PlanResourceChange(providers.PlanResourceChangeRequest{
    TypeName:         n.Addr.Resource.Resource.Type,
    Config:           unmarkedConfigVal,
    PriorState:       unmarkedPriorVal,
    ProposedNewState: proposedNewVal,
    PriorPrivate:     priorPrivate,
    ProviderMeta:     metaConfigVal,
})
plannedNewVal := resp.PlannedState  // <-- NO marks from provider
```

**File:** `internal/terraform/node_resource_abstract_instance.go:902-916`
**Line 916:** Provider response received without any sensitivity marks

### 2. Configuration-Only Mark Reconstruction (node_resource_abstract_instance.go:868, 998-999)

Marks from the **configuration** are extracted before provider call and re-applied afterward, but these represent only **variable-source sensitivity**, not schema-defined sensitivity:

```go
// Line 868: Extract config marks before sending to provider
unmarkedConfigVal, unmarkedPaths := configValIgnored.UnmarkDeepWithPaths()

// Lines 998-999: Re-apply config marks ONLY
if len(unmarkedPaths) > 0 {
    plannedNewVal = plannedNewVal.MarkWithPaths(unmarkedPaths)
}
```

**File:** `internal/terraform/node_resource_abstract_instance.go:868, 998-999`
**Key Issue:** `unmarkedPaths` contains marks from sensitive variable references (e.g., `var.db_password` is marked sensitive), but NOT marks from provider schema's `Sensitive: true` declarations.

### 3. State Serialization with Incomplete Marks (instance_object.go:94-136)

When encoding the planned state object to state, marks are extracted from the value itself. Since schema marks were never applied to the value, they're not captured:

```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    // Line 98: Extract marks from the value
    val, pvm := o.Value.UnmarkDeepWithPaths()

    // Lines 128-136: Save only marks that were on the value
    return &ResourceInstanceObjectSrc{
        SchemaVersion:       schemaVersion,
        AttrsJSON:           src,
        AttrSensitivePaths:  pvm,  // <-- INCOMPLETE: missing schema-defined marks
        Private:             o.Private,
        Status:              o.Status,
        Dependencies:        dependencies,
        CreateBeforeDestroy: o.CreateBeforeDestroy,
    }, nil
}
```

**File:** `internal/states/instance_object.go:94-136`
**Key Issue:** `pvm` only contains marks that were explicitly set on `o.Value`. Schema-defined sensitivity is never on the value, so it's not saved to state.

### 4. State Decoding with Incomplete Marks (instance_object_src.go:77-103)

When state is read back, only the incomplete marks from `AttrSensitivePaths` are re-applied:

```go
func (os *ResourceInstanceObjectSrc) Decode(ty cty.Type) (*ResourceInstanceObject, error) {
    // Line 87: Unmarshal JSON
    val, err = ctyjson.Unmarshal(os.AttrsJSON, ty)
    // Lines 89-90: Apply ONLY stored marks (incomplete)
    if os.AttrSensitivePaths != nil {
        val = val.MarkWithPaths(os.AttrSensitivePaths)
    }
    if err != nil {
        return nil, err
    }
}
```

**File:** `internal/states/instance_object_src.go:77-103**
**Key Issue:** Decoded values lack schema-defined sensitivity marks because they were never stored in state.

### 5. Phantom Update Detection (node_resource_abstract_instance.go:1208)

The plan compares marks from prior state against marks from planned value. When schema marks differ, a NoOp becomes an Update:

```go
// Line 1208: The phantom update mechanism
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update
}
```

**File:** `internal/terraform/node_resource_abstract_instance.go:1208`
**Explanation:**
- `plannedNewVal` has marks from `unmarkedPaths` (config-source only, from line 999)
- `priorPaths` has marks extracted from decoded state (also incomplete, from line 869)
- If schema marks should apply to `plannedNewVal` but don't, or if they should apply to `priorPaths` but don't, comparison fails
- Even though underlying values are identical, mark difference triggers Update action

### 6. The Compensating Workaround (evaluate.go:714-723, 689-693)

**Only** when reading from state for expression evaluation does Terraform compensate by re-applying schema marks:

```go
// Lines 714-723: Re-applying schema marks for expressions
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(val, nil)...)
    val = val.MarkWithPaths(marks)
}
```

**File:** `internal/terraform/evaluate.go:714-723`
**Key Issue:** This happens ONLY during expression evaluation (`GetResource()`), not during plan construction or state serialization. This creates an asymmetry:
- Values in state ≠ Values during expression evaluation (marks differ)
- This workaround prevents expressions from seeing incomplete marks, but does nothing for plan comparison

### 7. JSON Output Manifestation (jsonplan/plan.go:417-419, 446-448)

JSON plan and state output attempt to apply schema marks, but the underlying state is incomplete:

```go
// Lines 417-419: BeforeSensitive in JSON output
marks := rc.BeforeValMarks
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.Before, nil)...)
}

// Lines 446-448: AfterSensitive in JSON output
marks := rc.AfterValMarks
if schema.ContainsSensitive() {
    marks = append(marks, schema.ValueMarks(changeV.After, nil)...)
}
```

**File:** `internal/command/jsonplan/plan.go:417-419, 446-448`
**Key Issue:** JSON output produces correct sensitivity maps by re-applying schema marks, but this is redundant work and indicates marks were never preserved. The underlying state file lacks this information entirely (internal/command/jsonstate/state.go:402-406 does the same workaround).

## Affected Components

### Core Flow
- **`internal/terraform/node_resource_abstract_instance.go`** — Plan construction, provider response handling, mark reconstruction
- **`internal/states/instance_object.go`** — State encoding, mark extraction
- **`internal/states/instance_object_src.go`** — State decoding, mark application
- **`internal/terraform/marks.go`** — Mark comparison logic (`marksEqual`, `filterMarks`)

### Evaluation & Compensation
- **`internal/terraform/evaluate.go`** — Expression evaluation context, schema mark re-application workaround
- **`internal/terraform/node_resource_abstract.go`** — State reading for evaluation

### JSON Output (Manifestation)
- **`internal/command/jsonplan/plan.go`** — Plan JSON marshaling, redundant schema mark re-application
- **`internal/command/jsonstate/state.go`** — State JSON marshaling, redundant schema mark re-application

## Causal Chain

1. **Provider Response** → Returns unmarked value (provider responsibility)

2. **Configuration Mark Extraction** → Extracts marks from config: only variable-source marks captured
   - File: `node_resource_abstract_instance.go:868` (`unmarkedPaths`)

3. **Config Mark Re-application** → Re-applies only config marks to planned value
   - File: `node_resource_abstract_instance.go:998-999`
   - Missing: Schema marks never re-applied

4. **Change Construction** → Planned value stored in change with incomplete marks
   - File: `node_resource_abstract_instance.go:1236-1247`

5. **State Encoding** → Marks extracted from planned value, only config marks saved
   - File: `instance_object.go:98-131`
   - State file contains `AttrSensitivePaths` with only config-source marks

6. **State Decoding** → Marks restored from state (incomplete)
   - File: `instance_object_src.go:87-90`
   - Schema marks missing from decoded value

7. **Plan Comparison** → Detects mark difference between planned and prior
   - File: `node_resource_abstract_instance.go:1208`
   - NoOp → Update due to missing schema marks

8. **Symptom Manifest** → Plan shows phantom update
   - Underlying values identical
   - Marks differ (incomplete in state, complete in expression evaluator only)

## Recommendation

**Root Fix Strategy:**

1. **Preserve schema sensitivity in state** — When encoding to state, add schema-defined sensitive paths to `AttrSensitivePaths` before serialization
   - Modify: `instance_object.go:Encode()` to apply schema marks before `UnmarkDeepWithPaths()`
   - Alternative: Store schema sensitivity separately in state file format

2. **Eliminate redundant mark compensation** — Once schema marks are stored, remove the workaround logic from `evaluate.go`, `jsonplan/plan.go`, and `jsonstate/state.go`
   - These compensations exist because marks were incomplete; fixing source eliminates the need

3. **Consistent mark handling in plan construction** — Ensure that `plannedNewVal` receives schema marks the same way prior values do
   - Both prior and planned should apply schema marks at the same point in the flow

**Diagnostic Steps:**

1. Add logging to `instance_object.go:Encode()` to show which marks are captured vs. missing
2. Add logging to `node_resource_abstract_instance.go:1208` to show why `marksEqual()` fails
3. Compare `AttrSensitivePaths` in state file vs. marks applied during expression evaluation
4. Verify that schema-only sensitive attributes never appear in `terraform show -json` output

**Verification Test:**

Create a resource with schema-sensitive attribute that is NOT referenced by a sensitive variable:
```hcl
resource "test_instance" "example" {
  ami = "ami-12345"
  password = "hardcoded-value"  # password is marked Sensitive in schema
}
```

Expected after fix:
- `terraform plan` shows no changes (not phantom update)
- `terraform show -json` includes password in `sensitive_values`
