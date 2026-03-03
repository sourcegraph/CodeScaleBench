# Argo CD Codebase Orientation

## 1. Main Entry Points

Argo CD is a multi-binary system with several core components. Each component has its own CLI entry point defined through cobra commands:

### 1.1 API Server (`argocd-server`)
**Entry Point**: `cmd/argocd-server/commands/argocd_server.go:NewCommand()`

**Primary Responsibility**: The API Server is the main HTTP/gRPC server that exposes:
- REST API endpoints for UI and CLI interactions
- Server-side API for application management, cluster configuration, and settings
- Authentication/Authorization through Dex and session management
- Repository credential management
- Webhook handling for GitOps triggers
- Integration with the Kubernetes control plane

**Key Dependencies**: Connects to:
- Redis for caching and session storage
- Repo Server for manifest generation
- Kubernetes API server for Application CRD and cluster state
- Dex for OAuth2/OIDC authentication

### 1.2 Application Controller (`argocd-application-controller`)
**Entry Point**: `cmd/argocd-application-controller/commands/argocd_application_controller.go:NewCommand()` (lines 50-100)

**Primary Responsibility**: The Application Controller is a Kubernetes controller that implements the GitOps reconciliation loop:
- Continuously monitors Application CRD resources in the cluster
- Compares current live state against desired state (from Git)
- Orchestrates synchronization (sync) operations
- Manages application health and sync status updates
- Handles resource state caching through `AppStateManager`
- Executes hooks and manages sync waves for progressive deployments
- Implements sharding for horizontal scaling across multiple controller instances

**Key Components**:
- `controller/appcontroller.go`: Main reconciliation loop implementation
- `controller/state.go`: State comparison logic via `AppStateManager` interface
- `controller/sync.go`: Synchronization execution logic
- `controller/cache/`: Live cluster state caching

### 1.3 Repository Server (`argocd-repo-server`)
**Entry Point**: `cmd/argocd-repo-server/commands/argocd_repo_server.go:NewCommand()` (lines 53-100)

**Primary Responsibility**: The Repository Server is a gRPC service that manages Git repositories and generates Kubernetes manifests:
- Clones and maintains local cache of Git repositories
- Generates Kubernetes manifests from various templating tools (Helm, Kustomize, Jsonnet)
- Handles custom manifest generation via Config Management Plugins (CMP)
- Provides manifest diffs and health checks
- Supports multiple source types (Git, Helm registries, OCI)
- Manages GPG verification of Git commits

**Key Components**:
- `reposerver/repository/repository.go`: Manifest generation service
- `reposerver/repository/chart.go`: Helm chart handling
- `reposerver/cache/`: Repository cache management

### 1.4 ApplicationSet Controller (`argocd-applicationset-controller`)
**Entry Point**: `cmd/argocd-applicationset-controller/commands/applicationset_controller.go:NewCommand()` (lines 50-100)

**Primary Responsibility**: The ApplicationSet Controller manages ApplicationSet CRD resources:
- Generates multiple Applications from a single ApplicationSet definition
- Implements progressive sync strategies (RollingSync)
- Supports dynamic application generation via generators (cluster, git, matrix, etc.)
- Handles progressive rollout of changes across multiple applications
- Manages webhook handlers for ApplicationSet updates

**Key Components**:
- `applicationset/controllers/`: ApplicationSet controller logic
- `applicationset/generators/`: Generator implementations for different source types
- `applicationset/services/`: PullRequest and SCM provider integrations

---

## 2. Core Packages

### 2.1 Application API Types (`pkg/apis/application/v1alpha1/`)
**Responsibility**: Defines Argo CD CRDs and their structures

**Key Files**:
- `types.go`: Core structures for Application, AppProject, and ApplicationSet CRDs
  - `Application struct`: Spec (desired state), Status (observed state), Operation (pending operations)
  - `ApplicationSpec struct`: Source (Git repos), Destination (Kubernetes cluster), SyncPolicy
  - `ApplicationSource struct`: Repository URL, path, templating tool configuration
  - `ApplicationStatus struct`: SyncStatus, HealthStatus, Resources, Conditions

- `repository_types.go`: Repository credentials and cluster information types
- `app_project_types.go`: Project (RBAC) definition for grouping applications
- `applicationset_types.go`: ApplicationSet CRD for generating multiple applications

### 2.2 Application Client Set (`pkg/client/`)
**Responsibility**: Generated Kubernetes client for Argo CD custom resources

**Key Features**:
- Type-safe client for Application, AppProject, and ApplicationSet CRDs
- Informers and listers for efficient watch/list operations
- Used by controllers for resource operations and event handling

### 2.3 Controller Logic (`controller/`)
**Responsibility**: Core GitOps reconciliation and synchronization implementation

**Key Files**:
- `appcontroller.go`: Main ApplicationController that watches Applications and triggers reconciliation
- `state.go`: `AppStateManager` interface for comparing Application spec vs live state
- `sync.go`: SyncAppState implementation that executes manifest synchronization to cluster
- `hook.go`: Pre/post-delete hook execution for cleanup operations
- `cache/`: Cluster state caching with live updates from Kubernetes API

**Core Loop**:
1. Watch Application CRD changes
2. On change: `CompareAppState()` to determine sync status
3. If sync needed: `SyncAppState()` to apply resources to cluster
4. Update Application.Status with results (health, sync status, conditions)

### 2.4 Repository Server (`reposerver/`)
**Responsibility**: Git repository and manifest generation management

**Key Files**:
- `repository/repository.go`: Manifest Service that clones Git repos and generates manifests
  - Supports Helm, Kustomize, Jsonnet, raw YAML
  - Integrates with Config Management Plugins for custom generators
  - Implements manifest caching for performance

- `cache/`: Repository cache layer for Git clones and manifest generation results
- `metrics/`: Prometheus metrics for repository operations

### 2.5 API Server (`server/`)
**Responsibility**: REST/gRPC API endpoint implementation for UI and CLI

**Key Subpackages**:
- `server/application/`: Application CRUD and sync operations API
- `server/repository/`: Repository credential management API
- `server/cluster/`: Cluster management API
- `server/project/`: Project/RBAC management API
- `server/settings/`: Settings and configuration API
- `server/cache/`: Server-side caching for API responses

### 2.6 Common Utilities (`common/`, `util/`)
**Responsibility**: Shared constants, configuration, and utility functions

**Key Files**:
- `common/common.go`:
  - Component names (ApplicationController, etc.)
  - Default service addresses (repo-server, redis, dex)
  - ConfigMap/Secret names for settings (argocd-cm, argocd-secret)
  - Default ports and paths
  - Kubernetes API group and CRD names

- `util/settings/settings.go`:
  - `ArgoCDSettings` struct: Runtime configuration loaded from argocd-cm ConfigMap and argocd-secret Secret
  - OIDC, webhook, and banner configuration
  - TLS certificates and authentication settings

- `util/argo/`: Argo CD-specific utilities for Application reconciliation
- `util/kube/`: Kubernetes client utilities
- `util/git/`: Git client wrappers for repository operations

---

## 3. Configuration Loading

### 3.1 CLI Flags and Configuration
**Framework**: All components use [Cobra](https://github.com/spf13/cobra) for CLI command structure

**Pattern**:
- Each component's `NewCommand()` returns a `*cobra.Command`
- CLI flags are defined with default values
- Flags are parsed into component-specific config structs at startup

**Examples**:
- `argocd-application-controller`: `appResyncPeriod`, `repoServerAddress`, `repoServerTimeoutSeconds`, `kubectlParallelismLimit`
- `argocd-repo-server`: `listenPort`, `parallelismLimit`, `disableTLS`
- `argocd-server`: `listenPort`, `repoServerAddress`, `dexServerAddress`

**See**: `cmd/argocd-*/commands/` files for detailed flag definitions

### 3.2 Runtime Configuration from Kubernetes ConfigMaps/Secrets
**Configuration Source**: Kubernetes resources in argocd namespace

**Key Resources** (defined in `common/common.go`):
- `argocd-cm` (ConfigMap): Main Argo CD settings
  - OIDC configuration
  - Webhook secrets
  - UI customization (banners, CSS)
  - Helm build options
  - Kustomize options

- `argocd-secret` (Secret): Sensitive configuration
  - Server TLS certificate
  - JWT signing key for tokens
  - Database connection strings

- `argocd-rbac-cm` (ConfigMap): RBAC policies

- `argocd-ssh-known-hosts-cm` (ConfigMap): SSH host keys for Git

- `argocd-tls-certs-cm` (ConfigMap): TLS certificates for repositories

**Loading**: Uses `settings.SettingsManager` to watch and reload configuration dynamically
- **File**: `util/settings/settings.go:NewSettingsManager()`
- Watches for ConfigMap/Secret changes
- Implements in-memory cache of `ArgoCDSettings` struct
- Provides `GetSettings()` method that blocks until configuration is loaded

### 3.3 Configuration Pipeline

```
1. CLI Flags (Cobra)
   └── Parsed from command-line arguments

2. Environment Variables (util/env/)
   └── Override CLI defaults (e.g., ARGOCD_REPO_SERVER)

3. Kubernetes ConfigMaps/Secrets
   └── Loaded via SettingsManager
   └── Watched for dynamic reloading
   └── Loaded into ArgoCDSettings struct
```

**See**:
- `util/env/env.go`: Environment variable parsing utilities
- `util/settings/settings.go`: Configuration loading and watching

---

## 4. Test Structure

### 4.1 Unit Tests
**Organization**: Located alongside source code as `*_test.go` files

**Examples**:
- `controller/appcontroller_test.go`
- `pkg/apis/application/v1alpha1/types_test.go`
- `reposerver/repository/repository_test.go`

**Framework**: Go's standard `testing` package with custom fixtures

**Test Patterns**:
- Table-driven tests for multiple scenarios
- Mocking of Kubernetes client and external services
- Unit isolation using dependency injection

### 4.2 Integration Tests
**Organization**: Located in `test/` and component-specific directories

**Key Locations**:
- `test/`: Common test utilities and fixtures
- `test/fixture/`: Shared test fixtures for Git repos, manifests, etc.
- `controller/appcontroller_test.go`: Integration tests for sync logic

**Framework**: Uses custom test context builders and fixtures

**Test Coverage**:
- Full reconciliation loop with mock Kubernetes API
- Manifest generation with real Git repos
- State comparison and health evaluation

### 4.3 End-to-End (E2E) Tests
**Organization**: `test/e2e/` directory with extensive test suite

**Key Test Files**:
- `app_management_test.go`: Basic application CRUD and sync
- `app_autosync_test.go`: Auto-sync policy testing
- `sync_waves_test.go`: Progressive sync with waves
- `hook_test.go`: Lifecycle hook execution
- `sync_options_test.go`: Sync options (Prune, Force, etc.)
- `applicationset_test.go`: ApplicationSet functionality
- `helm_test.go`: Helm chart deployment
- `kustomize_test.go`: Kustomize build testing
- `git_test.go`: Git repository operations

**Framework**:
- Uses BDD-style fixtures (`test/e2e/fixture/`)
- Runs against real Kubernetes cluster (kind or in-cluster)
- Deploys Argo CD components via Helm/Kustomize
- Creates real git repositories for testing

**Key Fixtures** (`test/e2e/fixture/`):
- `fixture.Fixture`: Main test context with Argo CD client
- `fixture.App()`: Create test application
- `fixture.Repo()`: Create test git repository
- `fixture.ClusterResources()`: Manage resources in test cluster

**Execution**:
```bash
# Run all E2E tests
make test-e2e

# Run specific test
go test -run TestName ./test/e2e/
```

### 4.4 Testing Frameworks and Tools

**Go Testing**:
- Standard `testing` package
- `require`/`assert` libraries for assertions
- `gomock` for interface mocking

**External Tools**:
- `kubectl`: For cluster operations in E2E tests
- Kind or minikube: For test cluster creation
- Git: Real repository operations in tests
- Redis: Mock or real for integration tests

**Test Utilities**:
- `test/testutil.go`: Common test helper functions
- `test/fixture/`: BDD-style test fixtures
- `test/e2e/fixture/`: E2E-specific fixture builders

---

## 5. Application Sync Pipeline

The Application sync pipeline is the core GitOps workflow that deploys manifests from Git to Kubernetes. Here are the 4+ key stages:

### Stage 1: Change Detection and Reconciliation Trigger
**Location**: `controller/appcontroller.go` (AppController.processAppRefreshQueueItem)

**Process**:
1. Application Controller watches Application CRD resources
2. On change (new/update/delete): Application queued for reconciliation
3. Controller pulls Application from queue and starts comparison
4. Also triggers on timer-based resync period (default 180 seconds)

**Key Code**:
```
appcontroller.go: NewApplicationController()
  - Sets up informers for Application, AppProject resources
  - Registers event handlers for create/update/delete
  - Maintains workqueue for reconciliation
```

### Stage 2: State Comparison (Desired vs Live)
**Location**: `controller/state.go` (AppStateManager.CompareAppState)

**Process**:
1. Fetch desired state from Git repo via Repo Server
   - Call `reposerver/repository.Service.GenerateManifests()`
   - Returns target Kubernetes manifests

2. Fetch live state from cluster
   - Query cluster API for actual resources
   - Uses `controller/cache/` for efficient caching

3. Compare desired vs live state
   - Calculate diff using gitops-engine
   - Determine sync status (Synced, OutOfSync, Unknown)
   - Evaluate health status using `health.GetResourceHealth()`

4. Return `comparisonResult` with:
   - `syncStatus`: Synced, OutOfSync, or Unknown
   - `healthStatus`: Healthy, Degraded, or Progressing
   - `resources`: Per-resource status list

**Key Code**:
```
state.go: AppStateManager interface
  - CompareAppState(): Main comparison method
  - GetRepoObjs(): Fetch manifests from repo server
  - SyncAppState(): Execute sync operation
```

### Stage 3: Manifest Generation (Repo Server)
**Location**: `reposerver/repository/repository.go` (Service.GenerateManifests)

**Process**:
1. Clone/fetch Git repository (with caching)
   - Uses `util/git/` client
   - Caches repository locally

2. Check out specified revision (branch, tag, commit SHA)
   - Resolves ambiguous references (e.g., "main" → commit SHA)

3. Generate manifests based on source type:
   - **Helm**: Run `helm template` on chart
   - **Kustomize**: Run `kustomize build` on base
   - **Jsonnet**: Evaluate `.jsonnet` files
   - **Raw YAML**: Parse `.yaml`/`.yml` files directly
   - **Plugins**: Invoke Config Management Plugins via gRPC

4. Return list of Kubernetes manifests (YAML)

**Key Code**:
```
repository/repository.go:
  - Service.GenerateManifests(): Main generation method
  - GenerateManifestsFromCharts(): Helm support
  - GenerateManifestsFromKustomize(): Kustomize support
```

### Stage 4: Synchronization (Apply to Cluster)
**Location**: `controller/sync.go` (AppStateManager.SyncAppState)

**Process**:
1. Validate sync operation (checks RBAC, project restrictions)

2. Execute pre-sync hooks (if any)
   - Resources with `argocd.argoproj.io/compare-result: prune` annotation
   - Run before main sync operation

3. Apply manifests to cluster
   - **Apply Strategy**: `kubectl apply` (default)
   - **Hook Strategy**: Trigger Argo Rollouts hooks or Helm hooks
   - Uses kubectl or gitops-engine's sync engine

4. Execute sync in waves (progressive deployment)
   - Resources grouped by `argocd.argoproj.io/sync-wave` annotation (default: 0)
   - Waves executed sequentially with configurable delay
   - Wait for wave to be healthy before proceeding to next wave

5. Execute post-sync hooks (if any)
   - Run after main sync completes

6. Execute post-delete hooks (on resource deletion)
   - Cleanup tasks before resource is deleted

7. Prune out-of-sync resources (if enabled)
   - Delete resources in cluster that don't exist in Git

8. Record operation result in Application.Status
   - Success/failure status
   - List of resources applied
   - Conditions for health/sync status

**Key Code**:
```
sync.go:
  - SyncAppState(): Main sync method
  - Sync waves: handled by gitops-engine pkg/sync/syncwaves
  - Hook execution: controller/hook.go
```

### Stage 5: Status Update (Optional - Alternative Completion)
**Location**: `controller/appcontroller.go` (appStateManager methods)

**Process**:
1. Update Application.Status with comparison results:
   - `syncStatus`: Current sync state
   - `healthStatus`: Overall health
   - `resources`: Per-resource details
   - `reconciledAt`: When reconciliation completed

2. Store operation result
   - Success/failure message
   - Manifest generation logs
   - Sync operation details

3. Emit metrics
   - Reconciliation duration
   - Sync success/failure counts
   - Health status distribution

**See**: `controller/metrics/` for metric definitions

### Sync Pipeline Data Flow Diagram
```
Application CRD
    ↓
[1] AppController detects change
    ↓
[2] CompareAppState()
    ├── GetRepoObjs() from Repo Server
    │   └── [3] GenerateManifests from Git
    │       ├── Clone/fetch Git repo
    │       ├── Checkout revision
    │       └── Template (Helm/Kustomize/etc)
    │
    └── Get live state from cluster
        └── Compare desired vs live
        └── Calculate sync status & health
    ↓
[4] If OutOfSync and auto-sync enabled: SyncAppState()
    ├── Execute pre-sync hooks
    ├── Apply manifests (kubectl apply or hook strategy)
    ├── Execute by sync waves
    ├── Execute post-sync hooks
    ├── Prune resources (if enabled)
    └── Collect operation results
    ↓
[5] Update Application.Status
    ├── Set syncStatus, healthStatus
    ├── Add resource details
    └── Emit metrics
```

---

## 6. Adding a New Sync Strategy

To add a new sync strategy (e.g., custom hook behavior or wave behavior), you would need to modify these packages in sequence:

### 6.1 Step 1: Define CRD Type in API
**File**: `pkg/apis/application/v1alpha1/types.go`

**Changes**:
```go
// Add new sync strategy struct (around line 1340+)
type SyncStrategyCustom struct {
    // New fields for your custom strategy
    CustomOption string `json:"customOption,omitempty" protobuf:"bytes,1,opt,name=customOption"`
}

// Update SyncStrategy struct (around line 1342)
type SyncStrategy struct {
    Apply       *SyncStrategyApply   `json:"apply,omitempty" protobuf:"bytes,1,opt,name=apply"`
    Hook        *SyncStrategyHook    `json:"hook,omitempty" protobuf:"bytes,2,opt,name=hook"`
    Custom      *SyncStrategyCustom  `json:"custom,omitempty" protobuf:"bytes,3,opt,name=custom"` // NEW
}

// Add validation/convenience methods
func (s *SyncStrategy) IsCustomStrategy() bool {
    return s != nil && s.Custom != nil
}
```

**Also Update**:
- `pkg/apis/application/v1alpha1/generated.proto`: Add to SyncStrategy message
- Run code generation: `make gen-api` to regenerate client/openapi code

### 6.2 Step 2: Implement Sync Logic
**File**: `controller/sync.go`

**Changes**:
```go
// In SyncAppState() method, add handling for new strategy
func (m *appStateManager) SyncAppState(app *v1alpha1.Application, state *v1alpha1.OperationState) {
    // ... existing code ...

    // Around line 90-100, add new strategy handling
    switch {
    case syncOp.SyncStrategy.IsApplyStrategy():
        // existing apply strategy
    case syncOp.SyncStrategy.IsHookStrategy():
        // existing hook strategy
    case syncOp.SyncStrategy.IsCustomStrategy():
        // NEW: Your custom strategy implementation
        m.executeCustomSync(app, state, syncOp)
    }
}

// Add new method
func (m *appStateManager) executeCustomSync(app *v1alpha1.Application, state *v1alpha1.OperationState, syncOp v1alpha1.SyncOperation) {
    // Implement your custom sync logic here
    // Could involve: custom webhook calls, ordering, retry logic, etc.
}
```

### 6.3 Step 3: Handle Sync Strategy in GitOps Engine Integration
**File**: `controller/sync.go` (Continued)

**Changes**:
```go
// When creating sync options for gitops-engine (around line 348)
syncSettings := sync.WithOperationSettings(
    syncOp.DryRun,
    syncOp.Prune,
    syncOp.SyncStrategy.Force(),  // YOUR CUSTOM STRATEGY MIGHT AFFECT THIS
    syncOp.IsApplyStrategy() || len(syncOp.Resources) > 0,
)

// If your strategy needs pre/post hooks, add them here
if syncOp.SyncStrategy.IsCustomStrategy() {
    // Configure custom hooks or resource ordering
}
```

### 6.4 Step 4: Update CLI Command Handling
**File**: `cmd/argocd/commands/app.go`

**Changes**:
```go
// In the sync command parsing (around line 2080+)
switch {
case "apply":
    syncReq.Strategy = &argoappv1.SyncStrategy{Apply: &argoappv1.SyncStrategyApply{}}
    syncReq.Strategy.Apply.Force = force
case "hook":
    syncReq.Strategy = &argoappv1.SyncStrategy{Hook: &argoappv1.SyncStrategyHook{}}
    syncReq.Strategy.Hook.Force = force
case "custom":  // NEW
    syncReq.Strategy = &argoappv1.SyncStrategy{Custom: &argoappv1.SyncStrategyCustom{}}
    // Parse custom options from flags
}
```

**Also Add**:
- CLI flags for custom strategy options

### 6.5 Step 5: Update API Server Handling
**File**: `server/application/application.go`

**Changes**:
```go
// In the Sync() RPC handler, ensure your custom strategy is properly handled
func (s *applicationServiceServer) Sync(ctx context.Context, q *application.SyncRequest) (*v1alpha1.Application, error) {
    // ... existing code ...

    // Validate custom strategy if present
    if q.Strategy != nil && q.Strategy.Custom != nil {
        // Validate custom strategy options
    }

    // Create the sync request
}
```

### 6.6 Step 6: Add Tests
**Files**:
- `controller/sync_test.go`: Unit tests for sync logic
- `test/e2e/sync_options_test.go`: E2E tests

**Test Pattern**:
```go
func TestCustomSyncStrategy(t *testing.T) {
    // Setup application with custom sync strategy
    app := &v1alpha1.Application{
        Spec: v1alpha1.ApplicationSpec{
            SyncPolicy: &v1alpha1.SyncPolicy{
                SyncOptions: []string{...},
            },
        },
    }
    app.Spec.SyncPolicy.SyncStrategy = &v1alpha1.SyncStrategy{
        Custom: &v1alpha1.SyncStrategyCustom{...},
    }

    // Test sync execution
    // Verify expected behavior
}
```

### 6.7 Step 7: Update Documentation (Manifests/Examples)
**File**: `docs/user-guide/sync-kubectl.md` or create new sync strategy doc

**Add**:
- Example Application CRD with custom strategy
- Explanation of strategy behavior
- Configuration options

### Summary of Files to Modify
1. `pkg/apis/application/v1alpha1/types.go` - Add CRD types
2. `pkg/apis/application/v1alpha1/generated.proto` - Update protobuf definition
3. `controller/sync.go` - Implement sync execution
4. `controller/sync_test.go` - Add unit tests
5. `cmd/argocd/commands/app.go` - CLI flag parsing
6. `server/application/application.go` - API server handling
7. `test/e2e/sync_options_test.go` - Add E2E tests
8. Documentation files - Explain new strategy

**Code Generation Commands**:
```bash
make gen-api          # Regenerate API client code
make gen-crd-spec     # Regenerate CRD manifests
```

---

## Additional Resources

### Key Architecture Documents
- `docs/developer-guide/architecture/components.md`: Architecture overview
- `docs/user-guide/sync-kubectl.md`: Sync strategy documentation

### Important Interfaces
- `AppStateManager` (`controller/state.go`): Application comparison and sync
- `ManifestService` (`reposerver/repository/repository.go`): Manifest generation
- `ResourceTracking` (`util/argo/resource_tracking.go`): Resource ownership tracking

### Debugging Tips
- **Enable verbose logging**: Set `ARGOCD_LOG_LEVEL=debug`
- **Check Application status**: `kubectl describe app <app-name> -n argocd`
- **View repo server logs**: `kubectl logs -n argocd argocd-repo-server-*`
- **Trace sync operations**: Check Application.status.operationState for execution details

