# Terraform Plan/Apply Pipeline Architecture

## Q1: Command to Context

### How `PlanCommand.Run()` Delegates to the Backend

**File:** `internal/command/plan.go:22-118`

The `PlanCommand.Run()` method handles the CLI command and delegates planning to the backend through the following flow:

1. **Flag Parsing** (line 24-44): Parses arguments via `arguments.ParsePlan()` and sets up the CLI view
2. **Backend Preparation** (line 68): Calls `PrepareBackend()` to initialize the backend, which:
   - Loads backend configuration via `c.loadBackendConfig()`
   - Instantiates the backend via `c.Backend()`
   - Returns a `backendrun.OperationsBackend`

3. **Operation Request Building** (line 82-89): Calls `OperationRequest()` to construct a `backendrun.Operation` struct with:
   - `PlanMode`: specifying normal/destroy/refresh-only mode
   - `Targets`: resource targeting filters
   - `ForceReplace`: force replacement directives
   - `PlanRefresh`: whether to refresh remote state
   - `ConfigLoader`: the configuration loader
   - Other control parameters

4. **Variable Gathering** (line 90): Calls `GatherVariables()` to collect variable values

5. **Backend Operation Execution** (line 103): Calls `c.RunOperation(be, opReq)` which invokes the backend to execute the operation

### Key Fields in `PlanOpts`

**File:** `internal/terraform/context_plan.go:30-138`

`PlanOpts` defines the planning configuration passed to `Context.Plan()`:

- **Mode** (line 36): `plans.Mode` enum controlling plan type (NormalMode, DestroyMode, RefreshOnlyMode)
- **SkipRefresh** (line 42): Disables fetching updated values from providers (trusts prior state)
- **Targets** (line 68): Array of resource addresses for targeted planning (exceptional use only)
- **ForceReplace** (line 79): Resource instances to force replacement even if provider would update in-place
- **DeferralAllowed** (line 90): Permits deferring resources with unknown values for later processing
- **SetVariables** (line 58): Root module variable values provided by the user
- **ExternalProviders** (line 125): Pre-configured providers passed from the caller (root module only)

### Backend Invocation of Context.Plan()

The backend (via `backendrun.Operation`) creates a `terraform.Context` and invokes `Context.Plan()`:

**File:** `internal/terraform/context_plan.go:155-157`

```go
func (c *Context) Plan(config *configs.Config, prevRunState *states.State, opts *PlanOpts) (*plans.Plan, tfdiags.Diagnostics)
```

This delegates to `PlanAndEval()` (line 169) which:
1. Validates configuration and state dependencies
2. Checks external provider configurations
3. Routes to the appropriate mode-specific plan method (`plan()`, `destroyPlan()`, or `refreshOnlyPlan()`)
4. Constructs the final `plans.Plan` object with state, changes, and metadata

---

## Q2: Graph Construction Pipeline

### Steps() Method and Transformer Sequence

**File:** `internal/terraform/graph_builder_plan.go:121-277`

The `PlanGraphBuilder.Steps()` method returns a sequence of 20+ `GraphTransformer` stages that build the dependency graph:

#### Core Node Creation
1. **ConfigTransformer** (line 137-146): Creates nodes for all resources in configuration
   - Includes managed resources, data sources, and ephemeral resources
   - Handles import targets and config generation

2. **RootVariableTransformer** (line 149-154): Adds root module variables with raw values

3. **ModuleVariableTransformer** (line 155-159): Processes child module variables

4. **VariableValidationTransformer** (line 160-162): Adds validation nodes for variables

5. **LocalTransformer** (line 163): Adds local value nodes

6. **OutputTransformer** (line 164-176): Adds output nodes and determines refresh-only behavior

7. **CheckTransformer** (line 180-183): Adds check block assertion nodes

#### State and Configuration Attachment
8. **OrphanResourceInstanceTransformer** (line 186-191): Adds nodes for state-only resources not in config

9. **StateTransformer** (line 198-202): Adds nodes for deposed instances from state

10. **AttachStateTransformer** (line 205): Attaches prior state objects to resource instance nodes

11. **AttachResourceConfigTransformer** (line 215): Connects configuration to resource nodes

#### Provider Management
12. **transformProviders()** (line 218): Composite transformer for provider setup:
    - Adds external provider nodes
    - Adds configured providers
    - Adds missing default providers
    - Connects providers to consumers

#### Schema and Reference Resolution
13. **AttachSchemaTransformer** (line 225): Loads provider schemas for all resources

14. **ModuleExpansionTransformer** (line 230): Creates expansion nodes for module calls

15. **ExternalReferenceTransformer** (line 233-235): Incorporates external references from the caller

16. **ReferenceTransformer** (line 237): **Critical step** - analyzes configuration expressions and adds dependency edges

17. **AttachDependenciesTransformer** (line 239): Records explicit dependencies in state for destroy ordering

18. **attachDataResourceDependsOnTransformer** (line 243): Processes `depends_on` for data resources

#### Cleanup and Validation
19. **DestroyEdgeTransformer** (line 247-249): Adds reverse edges for destroy operations (plan-only)

20. **TargetsTransformer** (line 256): Prunes unrelated nodes based on `-target` flags

21. **ForcedCBDTransformer** (line 260): Detects create-before-destroy requirements from edges

22. **CloseProviderTransformer** (line 266): Adds nodes to close provider connections after use

23. **TransitiveReductionTransformer** (line 273): Simplifies graph by removing redundant edges

### ConfigTransformer: Creating Resource Nodes

**File:** `internal/terraform/transform_config.go:17-53`

- Recursively traverses the configuration module tree
- For each resource in the config:
  - Creates a node using the `Concrete` callback (typically `NodePlannableResourceInstance`)
  - Handles count/for_each expansion
  - Tracks import targets and associates them with resource nodes

### ReferenceTransformer: Building Dependency Edges

**File:** `internal/terraform/transform_reference.go:108-156`

The `ReferenceTransformer` is the critical step for dependency analysis:

1. **Builds a ReferenceMap** (line 115): Maps all referenceable nodes by their addresses
2. **Analyzes References** (line 118-148):
   - Iterates each vertex in the graph
   - Calls `m.References(v)` to find all parent nodes that this vertex depends on
   - For each parent, adds a directed edge: `v → parent` (child depends on parent)
3. **Special Cases**:
   - Skips destroy nodes (use only stored state, not references)
   - Avoids cycles with special module instance checks

The reference analysis examines:
- Direct attribute references (e.g., `aws_instance.web.id`)
- Computed value references (e.g., `data.aws_ami.ubuntu.id`)
- Count/for_each references
- Module output references

### AttachStateTransformer: Synchronizing with Prior State

**File:** `internal/terraform/transform_attach_state.go:29-71`

The `AttachStateTransformer` attaches the prior state to each resource instance node:

1. **Iterates all graph vertices** (line 42)
2. **Finds resource instance nodes** implementing `GraphNodeAttachResourceState`
3. **Locates prior state** (line 50): Gets the `states.Resource` for the resource from the input state
4. **Attaches to node** (line 67): Deep copies the resource state and calls `AttachResourceState()` on the node

This ensures resource instances have access to:
- Current attribute values from the prior apply
- Private data maintained by the provider
- Create-before-destroy metadata
- Dependencies recorded during prior apply

---

## Q3: Provider Resolution and Configuration

### Provider Initialization via EvalContext.InitProvider()

**File:** `internal/terraform/node_provider.go:28-29` and `internal/terraform/eval_provider.go:45-62`

The provider initialization flow:

1. **NodeApplyableProvider.Execute()** (line 28-29):
   ```go
   _, err := ctx.InitProvider(n.Addr, n.Config)
   ```
   - Called during graph walk for each provider node
   - `n.Addr`: absolute provider config address (e.g., `provider.aws.us-west-2`)
   - `n.Config`: provider configuration block from Terraform code

2. **EvalContext.InitProvider()** (accessed via eval_context.go):
   - Instantiates the provider plugin using the provider factory
   - Loads the provider's schema
   - Returns the initialized `providers.Interface`

3. **Provider Schema Loading** (line 57-62 in eval_provider.go):
   - Calls `ctx.ProviderSchema(addr)` to fetch the schema
   - Schema describes all resource types, data sources, and provider configuration

### ConfigureProvider: Applying Configuration

**File:** `internal/terraform/node_provider.go:103-151`

After initialization, `NodeApplyableProvider.Execute()` calls `ConfigureProvider()` for non-validate operations (line 44-49):

1. **Build Configuration Body** (line 106):
   - Merges explicit provider config from HCL with any input config
   - Uses `buildProviderConfig()` to construct the final `hcl.Body`

2. **Evaluate Configuration** (line 115):
   - Evaluates the configuration expression block using `ctx.EvaluateBlock()`
   - Resolves any variable/reference interpolations
   - Returns `cty.Value` with the provider's configuration

3. **Validate Configuration** (line 147-150):
   - Sends `ValidateProviderConfigRequest` to the provider
   - Provider validates the configuration and may insert defaults

4. **Call ConfigureProvider RPC** (implicit in ContextGraphWalker):
   - The provider plugin's `ConfigureProvider()` RPC is called (not shown in this snippet but happens in the provider interface)
   - Provider stores configuration state for later use during operations

### Provider Execution Timeline

**File:** `internal/terraform/graph_builder_plan.go:121-276`

The provider nodes execute in this order:

1. **Provider Configuration Nodes** execute first (added by `transformProviders()`)
   - Each `NodeApplyableProvider` runs its `Execute()` method
   - This calls `InitProvider()` and `ConfigureProvider()`
   - Creates edges from provider to all resource consumers

2. **Resource Instance Nodes** execute after their provider node completes
   - Resources wait for their provider node to finish
   - Can now call provider RPCs with confidence the provider is configured

3. **CloseProviderTransformer** (line 266) ensures:
   - A `graphNodeCloseProvider` node is created for each provider
   - This node depends on all resource instances that use the provider
   - After all resources finish, the provider connection is closed
   - Prevents resource leaks from partially-configured providers

---

## Q4: Diff Computation per Resource

### Resource Planning Execution Flow

**File:** `internal/terraform/node_resource_plan_instance.go:70-84` and line 179-451

The `NodePlannableResourceInstance.Execute()` method routes to the appropriate handler based on resource mode:

#### For Managed Resources: managedResourceExecute()

**File:** `internal/terraform/node_resource_plan_instance.go:179-451`

The managed resource execution comprises these phases:

### Phase 1: State Synchronization (Lines 183-278)

**Refresh Phase** (lines 296-323):
1. **Read Current State** via `n.readResourceInstanceState(ctx, addr)`:
   - Retrieves the prior state object from the stored state
   - Unmarshals the object value and any provider private data
   - Applies schema upgrades if needed

2. **Call Provider.ReadResource()** (line 635 in node_resource_abstract_instance.go):
   ```go
   resp = provider.ReadResource(providers.ReadResourceRequest{
       TypeName: n.Addr.Resource.Resource.Type,
       PriorState: priorVal,
       Private: state.Private,
       ProviderMeta: metaConfigVal,
       ClientCapabilities: {
           DeferralAllowed: deferralAllowed,
       },
   })
   ```
   - Asks the provider to read the actual remote resource
   - Provider returns updated state values reflecting any out-of-band changes
   - If the resource no longer exists remotely, returns null

3. **Detect Drift** (lines 640-721 in node_resource_abstract_instance.go):
   - Compares prior state with refreshed state
   - Any differences represent "drift" (external changes to the resource)
   - These differences will be reflected in the plan

4. **Write Refreshed State** (line 318):
   - Updates the refresh state with the new values from the provider
   - This becomes the "before" state for plan comparison

### Phase 2: Change Planning (Lines 335-451)

**Plan Phase** (lines 354-356):
1. **Evaluate Configuration** (line 819 in node_resource_abstract_instance.go):
   ```go
   origConfigVal, _, configDiags := ctx.EvaluateBlock(config.Config, schema, nil, keyData)
   ```
   - Evaluates the resource configuration block
   - Resolves all variable and reference interpolations
   - Returns the desired configuration as a `cty.Value`

2. **Call Provider.PlanResourceChange()** (line 927-937 in node_resource_abstract_instance.go):
   ```go
   resp = provider.PlanResourceChange(providers.PlanResourceChangeRequest{
       TypeName: n.Addr.Resource.Resource.Type,
       Config: unmarkedConfigVal,
       PriorState: unmarkedPriorVal,
       ProposedNewState: proposedNewVal,
       PriorPrivate: priorPrivate,
       ProviderMeta: metaConfigVal,
       ClientCapabilities: {
           DeferralAllowed: deferralAllowed,
       },
   })
   ```
   - `PriorState`: The refreshed state from the previous phase
   - `Config`: The desired configuration from the HCL
   - `ProposedNewState`: Terraform's initial diff (computed fields handled by provider)
   - Provider returns `PlannedState` which becomes the new state after apply

3. **Determine Action** (implicit in provider response):
   - Provider compares `PriorState` with `PlannedState`:
     - **Create**: `PriorState` is null, `PlannedState` is not null
     - **Update**: Both are non-null and have differences
     - **Replace**: Provider marks certain fields as "requires replacement"
     - **Delete**: `PlannedState` is null (resource removed from config)
     - **NoOp**: `PlannedState` equals `PriorState` (no changes)

4. **Apply Force Replace Logic** (lines 355, 393-395):
   - If user specified `-replace=resource`, override provider's action
   - Convert NoOp/Update actions to Replace for targeted instances

5. **Handle Deferrals** (lines 397-440):
   - If provider returns a `Deferred` object:
     - Indicates the provider cannot plan the resource yet (e.g., depends on unknown values)
     - `deferring.ReportResourceInstanceDeferred()` records the deferred change
     - Planning continues for other resources
     - Deferred resources are re-planned in the next Terraform run after apply

### Phase 3: Change Recording (Lines 413-430)

**Write Change to Plan** (line 416):
   ```go
   diags = diags.Append(n.writeChange(ctx, change, ""))
   ```
   - The computed change is written to `ctx.Changes()`
   - Records the action (Create/Update/Delete/Replace), before/after values, and computed values
   - These changes accumulate into the final `plans.Plan`

### Complete Execution Flow Diagram

```
NodePlannableResourceInstance.Execute()
├─ Import State (if importing)
│  └─ provider.ImportResource()
│
├─ Refresh Phase (if not skipRefresh)
│  ├─ provider.ReadResource()
│  └─ Write refreshed state to refreshState
│
├─ Plan Phase (if not skipPlanChanges)
│  ├─ Evaluate config expression
│  ├─ provider.PlanResourceChange()
│  │  └─ Returns PlannedState and action
│  ├─ Apply forceReplace override
│  ├─ Handle deferred resources
│  └─ Write change to changes buffer
│
└─ Return
   └─ Changes accumulated into final plans.Plan
```

### Key Execution Contexts

**EvalContext Responsibilities** (from context_walk.go):
- `ctx.InitProvider()`: Initialize provider plugins
- `ctx.Provider(addr)`: Get the initialized provider instance
- `ctx.ProviderSchema(addr)`: Get provider's schema
- `ctx.Deferrals()`: Access and modify deferral tracking
- `ctx.Changes()`: Accumulate changes for the plan
- `ctx.State()`: Access and modify working state during walk

---

## Evidence

### Critical File References

**Q1: Command to Context**
- `internal/command/plan.go:22-118` — PlanCommand.Run() and delegation flow
- `internal/backend/backendrun/operation.go` — Operation struct definition
- `internal/terraform/context_plan.go:30-138` — PlanOpts struct definition
- `internal/terraform/context_plan.go:155-158` — Context.Plan() entry point

**Q2: Graph Construction**
- `internal/terraform/graph_builder_plan.go:121-277` — Steps() with transformer sequence
- `internal/terraform/graph_builder_plan.go:18-109` — PlanGraphBuilder struct and Build() method
- `internal/terraform/transform_config.go:17-53` — ConfigTransformer definition
- `internal/terraform/transform_reference.go:108-156` — ReferenceTransformer implementation
- `internal/terraform/transform_attach_state.go:29-71` — AttachStateTransformer implementation
- `internal/terraform/transform_provider.go:17-41` — transformProviders() composition

**Q3: Provider Resolution**
- `internal/terraform/node_provider.go:18-52` — NodeApplyableProvider.Execute() and configuration
- `internal/terraform/node_provider_abstract.go:18-99` — NodeAbstractProvider structure
- `internal/terraform/eval_provider.go:45-62` — Provider initialization and schema loading
- `internal/terraform/graph_builder_plan.go:279-317` — initPlan() concrete provider setup
- `internal/terraform/transform_provider.go:250-310` — CloseProviderTransformer lifecycle

**Q4: Diff Computation**
- `internal/terraform/node_resource_plan_instance.go:29-451` — NodePlannableResourceInstance and managedResourceExecute()
- `internal/terraform/node_resource_abstract_instance.go:580-742` — refresh() and plan() methods
- `internal/terraform/context_plan.go:673-850` — planWalk() orchestration
- `internal/terraform/context_walk.go:83-99` — Graph walk execution and state management

### Additional Supporting Files

- `internal/terraform/context.go:37-164` — Context and ContextOpts definition
- `internal/terraform/node_resource_plan_instance.go:70-84` — Execute() dispatcher
- `internal/terraform/graph_walk.go` — Graph walking infrastructure
- `internal/terraform/providers.go` — Provider plugin interface
- `internal/plans/` — Plans data structures for recording changes
- `internal/states/` — State representation and synchronization
