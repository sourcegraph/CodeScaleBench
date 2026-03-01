# Investigation: Phantom In-Place Updates for Resources with Sensitive Attributes in Terraform

**Repository:** hashicorp/terraform
**Task Type:** Deep Causal Chain (investigation only — no code fixes)

## Scenario

A Terraform user reports that `terraform plan` consistently shows resources "will be updated in-place" even though **no configuration changes** have been made. The phantom update appears for any resource that has provider-schema-defined sensitive attributes (e.g., `password`, `secret_key`).

The user is managing a VPN tunnel resource:

```hcl
resource "test_instance" "example" {
  ami      = "ami-12345"
  password = var.db_password  # provider schema marks 'password' as Sensitive: true
}
```

After a successful `terraform apply`, immediately running `terraform plan` shows:

```
  # test_instance.example will be updated in-place
  ~ resource "test_instance" "example" {
        id       = "i-abc123"
        # (1 unchanged attribute hidden)
    }

Plan: 0 to add, 1 to change, 0 to destroy.
```

There are **no actual attribute changes** — the before and after values are identical. The phantom diff occurs specifically for resources where the provider schema declares one or more attributes with `Sensitive: true`.

Additionally, `terraform show -json` on the state file shows that the `sensitive_values` section in the JSON output is **incomplete** — it lists sensitivity marks that came from variable references (e.g., `var.db_password` is a `sensitive` variable) but **omits** sensitivity marks from the provider schema itself (e.g., the `password` attribute is always sensitive regardless of how it's populated).

Running `terraform plan -refresh-only` also shows phantom changes, and `terraform import` followed by `terraform plan` shows even more phantom updates.

## Your Task

Investigate the root cause of why Terraform generates phantom in-place updates for resources with schema-sensitive attributes, and produce a report at `/logs/agent/investigation.md`.

Your report MUST cover:

1. **How provider responses flow through the graph evaluator** — when `ReadResource` (refresh) or `PlanResourceChange` (plan) returns a value from the provider, how does `node_resource_abstract_instance.go` process that response? Specifically, examine `readResourceInstanceState()` (refresh path) and `plan()` (plan path) in `internal/terraform/node_resource_abstract_instance.go`.

2. **The sensitivity mark gap** — the provider response comes back **without** any sensitivity marks (providers don't mark values; that's Terraform's responsibility). The code re-applies marks from the **prior state** (`priorPaths` from `AttrSensitivePaths`), but these only contain marks from sensitive variable references, NOT from the provider schema's `Sensitive: true` declarations.

3. **How state serialization records incomplete sensitivity** — when the instance object is written to state via `internal/states/instance_object.go`, `sensitive_attributes` in the state file only has paths from sensitive references, missing the schema-defined sensitive paths. Trace through how `AttrSensitivePaths` is populated and how `unmarkValueForStorage` extracts marks before state serialization.

4. **The evaluator's compensating workaround** — `internal/terraform/evaluate.go`'s `GetResource()` method was the ONLY place that applied schema marks (via `markProviderSensitiveAttributes()` or similar). This meant that when a value was read FROM state and decoded for expression evaluation, it would get schema marks added. But the value stored IN state never had those marks. This created an asymmetry.

5. **How the asymmetry produces phantom diffs** — the plan compares refreshed state (which has schema marks from the evaluator) against the planned state (which was built from provider response without schema marks). The mark difference causes the plan to detect a "change" even though the underlying values are identical. The diff is in the sensitivity metadata, not the attribute values themselves.

6. **The JSON output manifestation** — `internal/command/` layer functions that produce `terraform show -json` read `sensitive_attributes` from state, which is incomplete. This produces incorrect `sensitive_values` in JSON plan/state output, where schema-defined sensitive attributes are missing from the sensitivity map.

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding>

## Root Cause
<Specific file, function, and mechanism>

## Evidence
<Code references with file paths and line numbers>

## Affected Components
<List of packages/modules impacted>

## Causal Chain
<Ordered list: symptom → intermediate hops → root cause>

## Recommendation
<Fix strategy and diagnostic steps>
```

## Constraints

- Do NOT write any code fixes
- Do NOT modify any source files
- Your job is investigation and analysis only
- The causal chain spans at least 4 packages: `internal/terraform/` (graph evaluation + marks), `internal/states/` (state serialization), `internal/command/` (JSON output), and the provider interaction boundary
- Focus on how `node_resource_abstract_instance.go` handles provider responses, how `marks.go` applies sensitivity, how `instance_object.go` serializes state, and how `evaluate.go` compensates
