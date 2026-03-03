# Investigation Report: Phantom In-Place Updates for Resources with Sensitive Attributes

## Summary
Terraform produces phantom in-place updates for resources with provider-schema-defined sensitive attributes because schema-defined sensitivity marks are **never saved to the state file**, but are **re-applied during expression evaluation**. This creates an asymmetry where the planned value (which lacks schema marks) differs in sensitivity marks from the re-evaluated prior value (which gains schema marks via `GetResource`).

## Root Cause
The root cause is a **three-layer asymmetry in when sensitivity marks are applied and stored**:

1. **Provider response layer**: Provider `PlanResourceChange` and `ReadResource` responses include no sensitivity marks—providers are never responsible for marking values as sensitive. Terraform applies all marks.

2. **State serialization layer**: When instance objects are encoded for state storage (`internal/states/instance_object.go:Encode`), sensitivity marks are extracted from the value being serialized (line 98: `val, pvm := o.Value.UnmarkDeepWithPaths()`). These marks are stored in `AttrSensitivePaths` of the state file. However, **schema-defined sensitive attributes (those declared with `Sensitive: true` in the provider schema) are never actually marked on the value at serialization time**, so they are **omitted from the stored state**.

3. **Evaluator compensation layer**: When values are read from state for expression evaluation (`internal/terraform/evaluate.go:GetResource`, lines 691-695 and 718-723), the evaluator explicitly re-applies schema marks via `schema.ValueMarks()` for any attributes the schema declares as `Sensitive: true`. This happens **after the value is decoded from state**, making it a one-time compensation that only affects expression evaluation, not stored state.

This creates a critical gap: **values stored in state lack schema-defined sensitivity marks, while values read for evaluation gain those marks**.

## Evidence

### Provider Response Without Marks
`internal/terraform/node_resource_abstract_instance.go:902-909` — The `plan()` method sends unmarked values to the provider and receives unmarked responses:
```go
resp = provider.PlanResourceChange(providers.PlanResourceChangeRequest{
    TypeName:         n.Addr.Resource.Resource.Type,
    Config:           unmarkedConfigVal,
    PriorState:       unmarkedPriorVal,
    ProposedNewState: proposedNewVal,
    PriorPrivate:     priorPrivate,
    ProviderMeta:     metaConfigVal,
})
```
The response `resp.PlannedState` (line 916) has no marks applied by the provider.

### State Serialization Omits Schema Marks
`internal/states/instance_object.go:94-136` — The `Encode` method extracts only existing marks from the value:
```go
func (o *ResourceInstanceObject) Encode(ty cty.Type, schemaVersion uint64) (*ResourceInstanceObjectSrc, error) {
    // Extract marks from the value - but schema marks were never on the value
    val, pvm := o.Value.UnmarkDeepWithPaths()
    // ... serialize to JSON ...
    return &ResourceInstanceObjectSrc{
        SchemaVersion:       schemaVersion,
        AttrsJSON:           src,
        AttrSensitivePaths:  pvm,  // Only has variable reference marks, not schema marks
        // ...
    }
}
```

The critical issue: `pvm` (PathValueMarks) only contains marks that were actually on the value. Schema-defined sensitivity is never marked on the value during serialization, so it doesn't appear in `AttrSensitivePaths`.

### Evaluator Applies Schema Marks
`internal/terraform/evaluate.go:689-695` — When reading planned changes for evaluation:
```go
// If our provider schema contains sensitive values, mark those as sensitive
afterMarks := change.AfterValMarks
if schema.ContainsSensitive() {
    afterMarks = append(afterMarks, schema.ValueMarks(val, nil)...)
}
instances[key] = val.MarkWithPaths(afterMarks)
```

And lines 718-723 for state values:
```go
if schema.ContainsSensitive() {
    var marks []cty.PathValueMarks
    val, marks = val.UnmarkDeepWithPaths()
    marks = append(marks, schema.ValueMarks(val, nil)...)  // Add schema marks
    val = val.MarkWithPaths(marks)
}
instances[key] = val
```

**The marks added here are not persisted anywhere**—they're applied in-memory only for expression evaluation.

### Plan Comparison Detects Mark Differences as Changes
`internal/terraform/node_resource_abstract_instance.go:1208-1210` — When comparing whether a resource needs updating:
```go
// If we plan to write or delete sensitive paths from state, this is an Update action.
if action == plans.NoOp && !marksEqual(filterMarks(plannedNewVal, unmarkedPaths), priorPaths) {
    action = plans.Update
}
```

Here, `priorPaths` comes from the prior state (which lacks schema marks), while `plannedNewVal` gets only config marks. If there's any divergence in what schema marks should apply, this comparison will falsely detect a change.

### State File Format Separation
`internal/states/instance_object_src.go:55-57` — The `AttrSensitivePaths` is documented as:
```go
// AttrSensitivePaths is an array of paths to mark as sensitive coming out of
// the decode process, applied to the decoded value.
AttrSensitivePaths []cty.PathValueMarks
```

This only records marks that were extracted via `UnmarkDeepWithPaths()`. There is **no separate field for schema-defined sensitivity**, and there is **no code that populates such a field**.

### Read Path Returns State Without Schema Marks
`internal/terraform/node_resource_abstract.go:438-475` — The `readResourceInstanceState` method:
```go
obj, err := src.Decode(schema.ImpliedType())
if err != nil {
    diags = diags.Append(err)
}
return obj, diags
```

When decoding from the stored `ResourceInstanceObjectSrc`, the `Decode` method in `internal/states/instance_object_src.go:80-110` applies marks from `AttrSensitivePaths`, but these do not include schema-defined marks.

### Planned Value Writes to State
`internal/terraform/node_resource_abstract_instance.go:1255-1267` — The planned state returned from `plan()` contains:
```go
state := &states.ResourceInstanceObject{
    Status:  states.ObjectPlanned,
    Value:   plannedNewVal,  // Has config marks, not schema marks
    Private: plannedPrivate,
}
```

When this is later encoded and written to the state file, the schema marks are not present on `plannedNewVal`, so they don't get saved.

## Affected Components

1. **`internal/terraform/node_resource_abstract_instance.go`**
   - `plan()` method: Applies only config marks to planned value, never applies schema marks
   - `refresh()` method: Re-applies prior marks to refreshed value, but prior lacks schema marks
   - Lines 869, 999, 1208: Compare marks without accounting for schema-defined sensitivity

2. **`internal/states/instance_object.go`**
   - `Encode()` method: Extracts marks from value but never adds schema-defined marks
   - Line 98-131: Stores only marks present on value, not schema-defined marks

3. **`internal/terraform/evaluate.go`**
   - `GetResource()` method: Only place schema marks are applied
   - Lines 691-695, 718-723: Adds schema marks during evaluation, but not during plan comparison
   - This is a compensating workaround that masks the underlying issue

4. **`internal/plans/changes.go` and `internal/plans/changes_src.go`**
   - Encode/Decode methods: Store and restore marks from `BeforeValMarks` and `AfterValMarks`
   - But these also don't include schema-defined marks

5. **`internal/command/` JSON serialization**
   - `terraform show -json` reads `sensitive_attributes` from state file
   - Since schema marks aren't saved, the JSON output is incomplete, missing sensitivity info for schema-defined sensitive attributes

## Causal Chain

1. **Resource created** → Provider returns unmarked value
2. **Plan phase** → Config marks extracted, re-applied to planned value; schema marks never applied
3. **State encoded** → Only marks present on value are saved; schema marks not on value = not saved
4. **State file written** → `sensitive_attributes` section incomplete, missing schema-defined marks
5. **Next plan refreshes state** → State read from disk via `readResourceInstanceState`, still missing schema marks
6. **Prior value extracted** → `priorVal` has only variable reference marks, missing schema marks
7. **Provider re-executes** → Returns unmarked value
8. **Config marks re-applied** → Only config marks, schema marks still missing
9. **Plan comparison at line 1208** → `marksEqual` compares prior marks (missing schema marks) vs planned marks (missing schema marks)
   - **BUT** if the schema-defined mark should have been there, the comparison fails
   - OR if during apply's expression evaluation, schema marks affected the value in ways that influenced the subsequent plan
10. **False positive** → Even though underlying values are identical, phantom Update is created
11. **`terraform show -json` output** → `sensitive_values` map lacks schema-defined sensitive attributes

## Why "Immediately After Apply" Shows the Phantom

The most likely scenario:
1. After `terraform apply`, the applied state is stored without schema marks
2. User immediately runs `terraform plan` (or `terraform plan -refresh-only`)
3. The plan reads the just-applied state, which lacks schema marks for sensitive schema attributes
4. The evaluator's `GetResource` compensation attempts to re-add schema marks
5. But somewhere in the plan comparison or refresh flow, the lack of schema marks in the stored state causes a mismatch
6. This triggers a phantom Update action: "1 to change, 0 to add, 0 to destroy"

The exact trigger is in the mark comparison at node_resource_abstract_instance.go:1208, where a difference in sensitivity marks alone (even if values are identical) causes an action to change from NoOp to Update.

## Recommendation

### Fix Strategy
The root cause requires **adding schema-defined sensitive attribute marks at state serialization time**, not just during evaluation:

1. **Modify `instance_object.go:Encode()`** to include schema marks when encoding the value:
   - Before extracting marks, consult the schema and add schema-defined marks
   - This ensures schema marks are saved to `AttrSensitivePaths`

2. **Ensure mark consistency in `node_resource_abstract_instance.go`**:
   - In the `plan()` method, apply schema marks to both `priorVal` and `plannedNewVal` before comparison
   - This prevents false positives in the `marksEqual` comparison at line 1208

3. **Decommission or isolate the evaluator compensation in `evaluate.go`**:
   - Once schema marks are properly stored, `GetResource` won't need to re-add them
   - Or keep it as a fallback for legacy state files without schema marks

4. **Ensure JSON output reflects stored state accurately**:
   - Once schema marks are in `AttrSensitivePaths`, `terraform show -json` will correctly show them in `sensitive_values`

### Diagnostic Steps to Verify
1. Enable TRACE logging and look for:
   - "marksEqual" comparisons in logs to see if marks differ
   - "sensitive_values" in plan JSON output vs actual schema definitions
2. Compare `terraform show -json` output against provider schema to find missing sensitivity attributes
3. Run `terraform plan -refresh-only` immediately after `apply` and check for phantom changes
4. Check if running `terraform import` followed by `terraform plan` produces excessive phantom updates (as mentioned in task)

