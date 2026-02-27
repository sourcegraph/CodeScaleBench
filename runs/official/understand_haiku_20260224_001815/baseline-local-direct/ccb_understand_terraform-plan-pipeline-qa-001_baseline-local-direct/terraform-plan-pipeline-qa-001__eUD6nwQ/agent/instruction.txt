# Architecture Q&A: Terraform Plan/Apply Pipeline

**Repository:** hashicorp/terraform
**Task Type:** Architecture Q&A (investigation only — no code changes)

## Background

Terraform's `terraform plan` command builds a dependency graph of all resources in the configuration, resolves providers, and computes the diff between desired state and current state. This process involves multiple layers: CLI command parsing, backend operation execution, graph construction via a series of transformers, concurrent graph walking, and provider plugin communication for diff computation.

## Questions

Answer ALL of the following questions about Terraform's plan execution pipeline:

### Q1: Command to Context

When a user runs `terraform plan`, how does the CLI command reach the core planning logic? Specifically:
- How does `PlanCommand.Run()` in `internal/command/plan.go` delegate to the backend?
- How does the backend create and invoke `terraform.Context.Plan()`?
- What are the key fields of `PlanOpts` that control plan behavior (mode, targets, force-replace)?

### Q2: Graph Construction Pipeline

How does `PlanGraphBuilder` construct the dependency graph for a plan operation?
- What is the role of the `Steps()` method and how does the sequence of `GraphTransformer` stages build the graph?
- Specifically, what do `ConfigTransformer`, `ReferenceTransformer`, and `AttachStateTransformer` each contribute?
- How does `ReferenceTransformer` analyze node references to add dependency edges between resources?

### Q3: Provider Resolution and Configuration

How are providers resolved, initialized, and configured during the plan walk?
- How does `EvalContext.InitProvider()` instantiate a provider plugin?
- At what point in graph execution is `ConfigureProvider()` called relative to resource planning?
- What is the role of `CloseProviderTransformer` in the graph lifecycle?

### Q4: Diff Computation per Resource

For a single managed resource instance, how does Terraform compute the planned changes?
- Trace the execution path from `NodePlannableResourceInstance.Execute()` through `managedResourceExecute()`
- How does the refresh phase (`refresh()`) synchronize with remote state before planning?
- How does the `plan()` method invoke the provider's `PlanResourceChange` RPC to compute the diff?
- What determines whether a resource is marked for create, update, replace, or delete?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Terraform Plan/Apply Pipeline Architecture

## Q1: Command to Context
<answer with specific file paths, type names, and function references>

## Q2: Graph Construction Pipeline
<answer with specific file paths, type names, and function references>

## Q3: Provider Resolution and Configuration
<answer with specific file paths, type names, and function references>

## Q4: Diff Computation per Resource
<answer with specific file paths, type names, and function references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, types, and functions — avoid vague or speculative answers
- Focus on the `internal/terraform/`, `internal/command/`, and `internal/providers/` directories
