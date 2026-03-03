# Terraform Plan/Apply Pipeline Architecture

## Q1: Command to Context

### CLI Entry Point
When a user runs `terraform plan`, the flow begins in **`internal/command/plan.go:22`**:
- `PlanCommand.Run(rawArgs []string)` parses arguments and prepares the backend
- At line 103, it calls `c.RunOperation(be, opReq)` which delegates to the backend's operation handler

### Backend to Context.Plan()
The backend's operation handler eventually invokes **`Context.Plan()`** defined in **`internal/terraform/context_plan.go:155`**:
```go
func (c *Context) Plan(config *configs.Config, prevRunState *states.State, opts *PlanOpts) (*plans.Plan, tfdiags.Diagnostics)
```

This method immediately delegates to **`Context.PlanAndEval()`** at line 156 in the same file, which is the core planning logic.

### PlanOpts Fields
The `PlanOpts` struct (**`internal/terraform/context_plan.go:32-138`**) controls plan behavior with these key fields:
- **`Mode`** (plans.Mode) - Specifies the plan mode (NormalMode, DestroyMode, RefreshOnlyMode)
- **`SkipRefresh`** (bool) - When true, skips refreshing managed resources and trusts the current state
- **`Targets`** ([]addrs.Targetable) - Activates targeted planning mode for specific resources
- **`ForceReplace`** ([]addrs.AbsResourceInstance) - Forces replacement of resources even if the provider would update them in-place
- **`PreDestroyRefresh`** (bool) - Indicates this is the refresh phase before a destroy plan
- **`SetVariables`** (InputValues) - Raw root module variable values provided by the user

### Planning Mode Delegation
Based on the mode, `PlanAndEval()` delegates to:
- **`c.plan()`** for NormalMode (line 274)
- **`c.destroyPlan()`** for DestroyMode (line 276)
- **`c.refreshOnlyPlan()`** for RefreshOnlyMode (line 278)

All three ultimately call **`c.planWalk()`** at **`internal/terraform/context_plan.go:673`**, which orchestrates the full plan operation.

---

## Q2: Graph Construction Pipeline

### Graph Builder Instantiation
At **`context_plan.go:887`**, the `planGraph()` method creates a `PlanGraphBuilder` configured with plan parameters. The builder is instantiated with:
- Configuration, prior state, provider configs, and targets
- Operation mode (walkPlan, walkPlanDestroy, walkValidate, walkImport)
- Force replace addresses and refresh flags
- Import targets and forget targets

The builder's `Build(addrs.RootModuleInstance)` method (line 918) returns the dependency graph.

### GraphTransformer Pipeline (Steps() Method)
At **`internal/terraform/graph_builder_plan.go:121-277`**, the `Steps()` method returns an ordered sequence of `GraphTransformer` stages that construct and refine the dependency graph:

#### Stage 1: Initial Graph Construction
- **`ConfigTransformer`** (line 137-146) - Creates all resource nodes from the configuration
  - File: **`internal/terraform/transform_config.go:55`**
  - Recursively processes all modules and creates nodes for ManagedResources and DataResources

- **`RootVariableTransformer`** (line 149-154) - Adds root module input variables

- **`ModuleVariableTransformer`** (line 155-159) - Adds module input variables

#### Stage 2: State Attachment
- **`AttachStateTransformer`** (line 205) - Attaches resource state to resource instance nodes
  - File: **`internal/terraform/transform_attach_state.go:35`**
  - For nodes implementing `GraphNodeAttachResourceState`, retrieves the resource state from `prevRunState` and attaches it

#### Stage 3: Schema and Reference Analysis
- **`AttachSchemaTransformer`** (line 225) - Attaches provider schemas to resource nodes before reference analysis

- **`ReferenceTransformer`** (line 237) - Connects nodes that reference each other to form proper ordering
  - File: **`internal/terraform/transform_reference.go:112`**
  - Implementation:
    - Creates a `ReferenceMap` of all vertices (line 115)
    - For each non-destroy node, calls `m.References(v)` to find nodes this node depends on (line 125)
    - For each parent node found, adds a directed edge: `g.Connect(dag.BasicEdge(v, parent))` (line 144)
  - This ensures resources referencing each other are executed in dependency order

#### Stage 4: Additional Transformations
- **`ModuleExpansionTransformer`** (line 230) - Creates expansion nodes for module calls
- **`ExternalReferenceTransformer`** (line 233-235) - Plugs in external references supplied by the caller
- **`AttachDependenciesTransformer`** (line 239) - Attaches explicit depends_on configuration
- **`attachDataResourceDependsOnTransformer`** (line 242-243) - Records transitive dependencies from data resource depends_on
- **`DestroyEdgeTransformer`** (line 247-249) - Adds destroy dependency edges for the TargetsTransformer

#### Stage 5: Targeting and Cleanup
- **`TargetsTransformer`** (line 256) - Prunes graph to only resources targeted with -target
- **`ForcedCBDTransformer`** (line 260) - Detects when create_before_destroy must be forced to avoid cycles
- **`pruneUnusedNodesTransformer`** (line 251-253) - Removes unused nodes that aren't connected to the graph

#### Stage 6: Final Transformation
- **`CloseProviderTransformer`** (line 266) - Adds nodes to close provider connections after resources are processed
- **`CloseRootModuleTransformer`** (line 269) - Closes the root module
- **`TransitiveReductionTransformer`** (line 273) - Reduces edges while preserving ordering to improve readability

### ReferenceTransformer in Detail
The `ReferenceTransformer` analyzes node references by:
1. Building a reference map with `NewReferenceMap(vertices)` that indexes referenceable addresses
2. For each vertex implementing `GraphNodeReferencer`:
   - Calling `References()` to get list of `*addrs.Reference` objects it depends on
   - Looking up each reference in the reference map via `m.References(v)`
   - Adding edges from the referencing node to each referenced node

This establishes the execution order: if Resource A references Resource B, an edge is added ensuring B is evaluated before A.

---

## Q3: Provider Resolution and Configuration

### Provider Initialization
During the graph walk, provider nodes are executed before resource nodes. At **`internal/terraform/eval_context.go:55`**, the `EvalContext.InitProvider()` method signature shows:
```go
InitProvider(addr addrs.AbsProviderConfig, configs *configs.Provider) (providers.Interface, error)
```

Implementation flow:
- `NodeEvalableProvider.Execute()` in **`internal/terraform/node_provider_eval.go:19`** calls `ctx.InitProvider()`
- The actual implementation (in context_builtin.go) initializes the provider plugin using the contextPlugins factory

### Provider Configuration
At **`internal/terraform/eval_context.go:86`**, `ConfigureProvider()` is called:
```go
ConfigureProvider(addrs.AbsProviderConfig, cty.Value) tfdiags.Diagnostics
```

The configuration step:
- Is called on provider nodes (e.g., `NodeApplyableProvider`)
- Sends the evaluated provider configuration block to the provider via RPC
- Happens BEFORE resource planning, as part of the graph walk before resource nodes execute

### Provider Lifecycle: CloseProviderTransformer
At **`internal/terraform/transform_provider.go:255-257`**, the `CloseProviderTransformer` adds nodes to close providers:
```go
type CloseProviderTransformer struct{}
func (t *CloseProviderTransformer) Transform(g *Graph) error
```

This transformer:
- Iterates through all provider nodes in the graph
- Creates a `graphNodeCloseProvider` for each provider
- Adds edges from all resources using a provider to that provider's close node
- Ensures providers are closed only after all dependent resources are processed

The close node implementation calls `EvalContext.CloseProvider()` to clean up the provider connection.

---

## Q4: Diff Computation per Resource

### Resource Instance Planning Entry Point
At **`internal/terraform/node_resource_plan_instance.go:70`**, `NodePlannableResourceInstance.Execute()` dispatches based on resource mode:
```go
func (n *NodePlannableResourceInstance) Execute(ctx EvalContext, op walkOperation) tfdiags.Diagnostics {
	addr := n.ResourceInstanceAddr()
	switch addr.Resource.Resource.Mode {
	case addrs.ManagedResourceMode:
		return n.managedResourceExecute(ctx)  // line 76
	case addrs.DataResourceMode:
		return n.dataResourceExecute(ctx)
	case addrs.EphemeralResourceMode:
		return n.ephemeralResourceExecute(ctx)
	}
}
```

### Managed Resource Planning Pipeline
For managed resources, **`managedResourceExecute()`** at **`node_resource_plan_instance.go:179`** orchestrates the planning process:

#### 1. State Reading
- Gets the provider instance via `getProvider(ctx, n.ResolvedProvider)` (line 190)
- Calls `n.readResourceInstanceState(ctx, addr)` (line 255) to load the resource's prior state
- For imports, calls `n.importState()` (line 213) to import the resource first

#### 2. Refresh Phase (Optional)
At line 296-323, the refresh phase executes:
- Calls **`n.refresh(ctx, states.NotDeposed, instanceRefreshState, ...)`**
- Implementation in **`node_resource_abstract_instance.go:580`**:
  - Calls `provider.ReadResource(providers.ReadResourceRequest{...})` at line 635
  - The provider RPC call reads the current remote state for the resource
  - Updates `instanceRefreshState` with the refreshed values
  - Handles deferral if the provider defers the refresh

#### 3. Planning Phase (Computing Diff)
At line 354-356, the planning phase computes the diff:
```go
change, instancePlanState, planDeferred, repeatData, planDiags := n.plan(
	ctx, nil, instanceRefreshState, n.ForceCreateBeforeDestroy, n.forceReplace,
)
```

The **`plan()`** method implementation in **`node_resource_abstract_instance.go:744`** performs:

##### Step 3a: Configuration Evaluation
- Evaluates the resource configuration block against the current context (line 819)
- Validates the configuration against the provider schema (line 866-875)
- Applies `ignore_changes` logic to the configuration (line 884)

##### Step 3b: Provider Plan RPC Call
At **line 927**, the core diff computation occurs:
```go
resp = provider.PlanResourceChange(providers.PlanResourceChangeRequest{
	TypeName:         n.Addr.Resource.Resource.Type,
	Config:           unmarkedConfigVal,
	PriorState:       unmarkedPriorVal,
	ProposedNewState: proposedNewVal,
	PriorPrivate:     priorPrivate,
	ProviderMeta:     metaConfigVal,
	ClientCapabilities: providers.ClientCapabilities{
		DeferralAllowed: deferralAllowed,
	},
})
```

The provider plugin:
- Compares the prior state with the desired configuration
- Returns a `PlannedState` representing what the resource should look like after apply
- Optionally returns `RequiresReplace` to indicate which attributes require replacement
- May return a deferral if it can't plan the resource (line 950-951)

##### Step 3c: Action Determination
At **line 1054**, `getAction()` determines the action based on the diff:
```go
action, actionReason := getAction(n.Addr, unmarkedPriorVal, unmarkedPlannedNewVal, createBeforeDestroy, forceReplace, reqRep)
```

The action is determined by:
- **Create**: When prior state is null and planned state is known
- **Update**: When prior state exists and values differ, but no attributes require replacement
- **Replace**: When `RequiresReplace` includes any attributes, or when `forceReplace` is set for this resource
- **Delete**: During destroy plans, when resource exists in prior state
- **No-Op**: When prior and planned states are identical

##### Step 3d: Replace Action Replanning (Optional)
If the action is `Replace` (line 1056-1100):
- The provider is called again with a null prior state (line 1089)
- This generates correct computed values for a newly created resource
- The result is combined with the actual prior state to show what changes during replacement

#### 4. Change Recording
At **line 376**, `n.writeChange()` records the computed change in the plan state, making it available to be serialized into the plan file.

### Summary of Execution Flow
```
NodePlannableResourceInstance.Execute()
  ├─ managedResourceExecute()
  │   ├─ readResourceInstanceState() [Load prior state]
  │   ├─ refresh() [Optional]
  │   │   └─ provider.ReadResource() [Get current remote state]
  │   ├─ plan()
  │   │   ├─ EvaluateBlock() [Evaluate config]
  │   │   ├─ ValidateResourceConfig() [Validate]
  │   │   ├─ provider.PlanResourceChange() [Compute diff]
  │   │   └─ getAction() [Determine Create/Update/Replace/Delete]
  │   │       └─ provider.PlanResourceChange() again if Replace
  │   └─ writeChange() [Record the planned change]
  └─ [Resource planning complete]
```

---

## Evidence

### File References

#### Q1: Command to Context
- `internal/command/plan.go:22` - PlanCommand.Run()
- `internal/command/plan.go:103` - RunOperation call
- `internal/terraform/context_plan.go:155` - Context.Plan()
- `internal/terraform/context_plan.go:169` - Context.PlanAndEval()
- `internal/terraform/context_plan.go:32-138` - PlanOpts struct definition
- `internal/terraform/context_plan.go:273-278` - Mode-based delegation
- `internal/terraform/context_plan.go:673` - planWalk()

#### Q2: Graph Construction Pipeline
- `internal/terraform/context_plan.go:887` - planGraph()
- `internal/terraform/context_plan.go:901` - PlanGraphBuilder instantiation
- `internal/terraform/graph_builder_plan.go:112-118` - PlanGraphBuilder.Build()
- `internal/terraform/graph_builder_plan.go:121-277` - PlanGraphBuilder.Steps()
- `internal/terraform/transform_config.go:1-100` - ConfigTransformer definition
- `internal/terraform/transform_attach_state.go:29-71` - AttachStateTransformer implementation
- `internal/terraform/transform_reference.go:108-156` - ReferenceTransformer implementation
- `internal/terraform/transform_reference.go:112-148` - ReferenceTransformer.Transform() - adds edges based on references
- `internal/terraform/graph_builder_plan.go:266` - CloseProviderTransformer in steps

#### Q3: Provider Resolution and Configuration
- `internal/terraform/eval_context.go:34-150` - EvalContext interface definition
- `internal/terraform/eval_context.go:55` - InitProvider() signature
- `internal/terraform/eval_context.go:86` - ConfigureProvider() signature
- `internal/terraform/node_provider_eval.go:12-22` - NodeEvalableProvider.Execute()
- `internal/terraform/transform_provider.go:255-270` - CloseProviderTransformer definition and Transform()

#### Q4: Diff Computation per Resource
- `internal/terraform/node_resource_plan_instance.go:29-56` - NodePlannableResourceInstance definition
- `internal/terraform/node_resource_plan_instance.go:70-84` - Execute() dispatcher method
- `internal/terraform/node_resource_plan_instance.go:179-450` - managedResourceExecute() implementation
- `internal/terraform/node_resource_plan_instance.go:255` - readResourceInstanceState() call
- `internal/terraform/node_resource_plan_instance.go:296-323` - Refresh phase invocation
- `internal/terraform/node_resource_abstract_instance.go:577-742` - refresh() implementation
- `internal/terraform/node_resource_abstract_instance.go:580` - refresh() signature
- `internal/terraform/node_resource_abstract_instance.go:635` - provider.ReadResource() RPC call
- `internal/terraform/node_resource_abstract_instance.go:744-1150` - plan() implementation
- `internal/terraform/node_resource_abstract_instance.go:927-937` - provider.PlanResourceChange() RPC call
- `internal/terraform/node_resource_abstract_instance.go:1054` - getAction() determination
- `internal/terraform/node_resource_abstract_instance.go:1056-1100` - Replace action replanning logic
