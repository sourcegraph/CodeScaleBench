# Argo CD Codebase Orientation

## 1. Main Entry Points

Argo CD is a distributed system with multiple binaries. The main entry point is `cmd/main.go`, which routes to specific component commands based on the binary name.

### API Server (argocd-server)
- **Entry Point**: `cmd/argocd-server/commands/argocd_server.go:NewCommand()`
- **Primary Responsibility**: Serves the REST/gRPC API that the UI and CLI use. Manages authentication, authorization, and provides endpoints for application management, project management, repository management, cluster management, etc.
- **Key Components**:
  - Initializes `server.ArgoCDServer` (server/server.go:277)
  - Sets up HTTP/GRPC listeners on configurable ports
  - Manages WebSocket connections for real-time updates
  - Coordinates with other components via gRPC clients

### Application Controller (argocd-application-controller)
- **Entry Point**: `cmd/argocd-application-controller/commands/argocd_application_controller.go:NewCommand()`
- **Primary Responsibility**: The core reconciliation loop that continuously monitors Application CRs and syncs them to the target Kubernetes cluster. Compares desired state (from git repos) with live state (in the cluster).
- **Key Components**:
  - Runs a Kubernetes controller using client-go informers
  - Implements resource reconciliation logic in `controller/appcontroller.go`
  - Calls the repo server to get desired manifests
  - Coordinates sync operations through `controller/sync.go`
  - Manages application health and sync status

### Repository Server (argocd-repo-server)
- **Entry Point**: `cmd/argocd-repo-server/commands/argocd_repo_server.go:NewCommand()`
- **Primary Responsibility**: Maintains local git repository caches and generates Kubernetes manifests from various sources (Kustomize, Helm, Jsonnet, etc.). Acts as an internal service called by the controller and API server.
- **Key Components**:
  - Implements `reposerver/repository/repository.go:Service` with methods like `GenerateManifest()`
  - Handles git operations (clone, fetch, checkout) with credential management
  - Supports multiple templating systems: Kustomize, Helm, Jsonnet, Argo CD plugins
  - Runs as a gRPC server on configurable port (default 8081)

### ApplicationSet Controller (argocd-applicationset-controller)
- **Entry Point**: `cmd/argocd-applicationset-controller/commands/applicationset_controller.go:NewCommand()`
- **Primary Responsibility**: Watches ApplicationSet CRs and dynamically generates Application CRs based on generator strategies (List, Cluster, Git, Matrix, etc.). Enables templating and multi-cluster deployments.
- **Key Components**:
  - Uses controller-runtime for Kubernetes reconciliation
  - Multiple generators in `applicationset/generators/`
  - Validates ApplicationSets before generating Applications
  - Supports progressive sync and policy overrides

---

## 2. Core Packages

### pkg/apis/application/v1alpha1
**Location**: `pkg/apis/application/v1alpha1/`
**Responsibility**: Defines all Argo CD CRD types and API structures
- **Application** (types.go:55): Main CRD for declarative deployment specifications
- **ApplicationSpec**: Source, destination, project, sync policy, ignore differences
- **ApplicationStatus**: Current sync/health status, conditions, resources
- **ApplicationSet** (applicationset_types.go): Template for generating Applications
- **AppProject** (app_project_types.go): RBAC and repository access control
- **Repository** (repository_types.go): Git/Helm repository credentials
- **SyncStrategy** (types.go:1342): Defines sync execution strategy (apply vs hook-based)

### controller
**Location**: `controller/`
**Responsibility**: Application reconciliation and sync orchestration
- **appcontroller.go**: Main reconciliation loop, watches Applications and triggers syncs
- **sync.go** (SyncAppState): Orchestrates resource sync operations using gitops-engine
- **state.go** (appStateManager): Compares desired vs live state, generates diffs
- **hook.go**: Handles pre/post-delete hooks for graceful resource cleanup
- **cache/** : Application state caching layer for performance

### server
**Location**: `server/`
**Responsibility**: REST/gRPC API handlers and server setup
- **server.go** (ArgoCDServer): Main server initialization and gRPC registration
- **application/** : Handlers for Application resource operations
- **settings/** : Handlers for system configuration
- **project/** : Project RBAC management
- **repository/** : Repository credential management
- **cache/** : Server-level caching (live state cache)

### reposerver
**Location**: `reposerver/`
**Responsibility**: Git repository management and manifest generation
- **server.go** (ArgoCDRepoServer): gRPC server setup and initialization
- **repository/repository.go** (Service): Manifest generation engine
  - GenerateManifest(): Main entry point for manifest generation
  - Supports Kustomize, Helm, Jsonnet, custom tools via plugins
- **cache/**: Repository content caching
- **apiclient/**: Generated gRPC client code for repo server API

### util/settings
**Location**: `util/settings/`
**Responsibility**: Configuration management through Kubernetes ConfigMaps/Secrets
- **SettingsManager** (settings.go:552): Watches and manages Argo CD configuration
- Loads settings from argocd-cm ConfigMap and argocd-secret Secret
- Provides methods like GetResourceOverrides(), GetKustomizeSettings(), etc.
- Handles OIDC, Webhook secrets, Kustomize options, and resource health overrides

### util/argo
**Location**: `util/argo/`
**Responsibility**: Application-specific utilities and business logic
- **argo.go**: Core functions like ValidateApplication(), CompareAppState()
- **diff/**: Diff calculation and normalization (comparing desired vs live)
- **normalizers/**: Ignore rules for comparing resources (e.g., ignore generated fields)
- **ResourceTracking**: Manages app ownership labels and tracking metadata

### applicationset
**Location**: `applicationset/`
**Responsibility**: ApplicationSet controller and generators
- **controllers/**: ApplicationSet reconciliation logic
- **generators/**: Various generator implementations (Cluster, Git, Matrix, etc.)
- **services/**: Template rendering and validation
- **utils/**: Helper functions for ApplicationSet processing

---

## 3. Configuration Loading

Argo CD uses a multi-layered configuration approach combining CLI flags, environment variables, and Kubernetes-native resources.

### Configuration Pipeline

#### 1. CLI Flags (Cobra)
Each component's `NewCommand()` function uses [Spf13 Cobra](https://github.com/spf13/cobra) to define CLI flags:
- **Application Controller** (`cmd/argocd-application-controller/commands/argocd_application_controller.go:234`):
  - `--app-resync` (resync period)
  - `--app-hard-resync` (full resync period)
  - `--kubeconfig` (Kubernetes client config)
  - `--repo-server` (repo server address)
  - Flags populated via `command.Flags().Int64Var()`, `StringVar()`, etc.

#### 2. Environment Variables
Parsed via `util/env/` package functions:
- `env.ParseNumFromEnv()`: Parse integers with defaults
- `env.ParseBoolFromEnv()`: Parse boolean flags
- `env.StringFromEnv()`: Parse strings with fallback defaults
- Examples: `ARGOCD_RECONCILIATION_TIMEOUT`, `ARGOCD_SYNC_WAVE_DELAY`

#### 3. Kubernetes ConfigMaps/Secrets
**SettingsManager** (`util/settings/settings.go:1801`)
```
NewSettingsManager(ctx, kubeClient, namespace)
→ Watches argocd-cm ConfigMap
→ Watches argocd-secret Secret
→ Provides methods to retrieve settings at runtime
```

Example usage in API server (`cmd/argocd-server/commands/argocd_server.go:279`):
```go
settingsMgr := settings_util.NewSettingsManager(ctx, opts.KubeClientset, opts.Namespace)
settings, err := settingsMgr.InitializeSettings(opts.Insecure)
```

#### 4. Kubeconfig and Cluster Access
Via `clientcmd.ClientConfig` pattern:
```go
clientConfig := cli.AddKubectlFlagsToCmd(&command)
config, err := clientConfig.ClientConfig()
kubeClient := kubernetes.NewForConfigOrDie(config)
```

### Key Configuration Structures

- **ArgoCDSettings** (util/settings/settings.go:49): In-memory runtime config
  - URL, DexConfig, OIDCConfig, TLS certificates
  - Webhook secrets, Kustomize options
  - Resource overrides (health indicators)

- **RepoServerInitConstants** (reposerver/repository/repository.go:101): Repo server limits
  - ParallelismLimit, MaxCombinedDirectoryManifestsSize
  - Stream size limits, Helm registry limits

---

## 4. Test Structure

Argo CD uses a three-tiered testing approach: unit tests, integration tests, and end-to-end tests.

### Unit Tests
**Location**: Throughout codebase with `*_test.go` files
**Framework**: `testing` package + `testify` for assertions
**Example**: `controller/appcontroller_test.go`
- Uses mock objects and fake Kubernetes clients
- Mocks external dependencies (repo server, live state cache, database)
- Uses `fake.NewSimpleClientset()` for Kubernetes API mocking
- Tests individual functions in isolation

**Key Test Utilities**:
- `k8s.io/client-go/kubernetes/fake` - Fake Kubernetes client
- `github.com/stretchr/testify/assert` - Assertion helpers
- `github.com/stretchr/testify/mock` - Mocking library

### Integration Tests
**Location**: Test files in main directories
**Framework**: Similar to unit tests but may use real components
- Tests interaction between multiple components
- Often uses fixture data and test manifests

### End-to-End Tests
**Location**: `test/e2e/` directory
**Framework**: Go testing + test fixtures
**Components**:
- **Fixture System** (`test/e2e/fixture/fixture.go`):
  - Provides cluster setup/teardown
  - Manages test repositories and applications
  - CLI command wrappers for testing argocd CLI
  - Named constants: `ArgoCDNamespace = "argocd-e2e"`, `TestingLabel = "e2e.argoproj.io"`

- **Test Data** (`test/e2e/testdata/`):
  - Real git repositories with application manifests
  - Guestbook example with various sync configurations
  - Test data for different deployment tools (Kustomize, Helm, Jsonnet)

- **Test Patterns**:
  - Create test Applications via fixture API
  - Trigger sync operations
  - Wait for conditions (via polling with retries)
  - Assert on status fields and resource states
  - Example test: `test/e2e/app_management_test.go:TestAppLogs()`

**E2E Test Categories** (visible in file list):
- Application management and sync (`app_management_test.go`, `app_sync_options_test.go`)
- Auto-sync behavior (`app_autosync_test.go`)
- Sync waves and hooks (`sync_waves_test.go`, `hook_test.go`)
- Repository interaction (`repo_management_test.go`, `git_test.go`)
- ApplicationSet templates (`applicationset_test.go`)
- RBAC and projects (`project_management_test.go`)

**Test Execution**:
E2E tests require a running Argo CD deployment and Kubernetes cluster. They communicate via gRPC using the fixture's client setup.

---

## 5. Application Sync Pipeline

The path from Application CRD to actual deployment involves these key stages:

### Stage 1: CRD Definition and Storage
**Files Involved**: `pkg/apis/application/v1alpha1/types.go`
- Application is defined as a Kubernetes CRD
- Stored in etcd via Kubernetes API server
- Status subresource tracks sync/health conditions
- Operation field holds current/completed sync details

### Stage 2: Application Monitoring and Reconciliation
**Files Involved**: `controller/appcontroller.go`
- Application Controller watches Application CRs via informers
- On Application change or resync timer trigger:
  1. Fetch Application resource
  2. Verify project permissions and repository access
  3. Queue for reconciliation (respects backoff/rate limiting)
  4. Invoke `appStateManager.SyncAppState()` in `controller/sync.go`

### Stage 3: Desired State Retrieval
**Files Involved**:
- `controller/state.go` (appStateManager.GetRepoObjs())
- `reposerver/repository/repository.go` (Service.GenerateManifest())
- gRPC call from controller to repo server

**Process**:
1. Clone/fetch git repository to local cache
2. Check out specified revision (branch/tag/commit)
3. Call GenerateManifest() with source configuration
4. Select appropriate templating engine:
   - **Kustomize**: Run `kustomize build` (util/kustomize/)
   - **Helm**: Render chart via `helm template` (util/helm/)
   - **Jsonnet**: Render jsonnet files (util/lua/, util/app/)
   - **Custom Tools**: Invoke ConfigManagementPlugin (cmpserver/)
5. Parse YAML output into Unstructured objects
6. Return manifest list to controller

**Key Functions**:
- `repository.GenerateManifest()` - Main manifest generation
- `state.CompareAppState()` - Compares desired vs live state
- Returns `compareResult` with ResourceDiffs

### Stage 4: Diff Calculation and Status Update
**Files Involved**:
- `util/argo/diff/` (diff calculation)
- `controller/state.go` (status update logic)

**Process**:
1. Retrieve live state from target cluster (via live state cache)
2. Calculate diff between desired and live manifests
3. Apply normalizers/ignore rules (`util/argo/normalizers/`)
4. Update Application.Status with:
   - `sync.status` (Synced/OutOfSync)
   - `health.status` (Healthy/Degraded)
   - List of resource differences
5. Determine if sync is needed

### Stage 5: Sync Execution
**Files Involved**:
- `controller/sync.go` (SyncAppState main orchestration)
- `reposerver/repository/repository.go` (GenerateManifest called again)
- gitops-engine sync engine

**Process** (if sync is triggered):
1. Validate sync request and resource selection
2. Regenerate manifests (to ensure fresh state)
3. Determine resource ordering:
   - **Sync Waves**: Resources grouped by `argocd.argoproj.io/sync-wave` annotation
   - **Dependencies**: Handled via gitops-engine hooks
4. Execute sync phases in order:
   - **PreSync**: Run pre-sync hooks (if defined)
   - **Sync**: Apply manifests with chosen strategy
   - **PostSync**: Run post-sync hooks
   - **SyncFail**: Run sync failure hooks (if applicable)

**Sync Strategies**:
- **Apply Strategy**: Use `kubectl apply` (util/kube/)
- **Hook Strategy**: Use Argo Hooks annotations for custom logic

### Stage 6: Resource Application and Polling
**Files Involved**:
- `util/kube/` (kubectl wrapper for apply/delete)
- Live state cache polling

**Process**:
1. For each resource in sync wave:
   - Apply manifest via kubectl (strategic merge patch)
   - Track applied resources with app instance label
2. Poll live state to check readiness:
   - Check resource health status
   - Wait for Deployment/StatefulSet replicas
   - Track completion per wave
3. Handle deletion (with prune strategy):
   - Execute PostDelete hooks if needed
   - Remove resources not in desired state

### Stage 7: Health Assessment and Final Status
**Files Involved**:
- `controller/health.go` (health assessment)
- gitops-engine health evaluation

**Process**:
1. Fetch live state of all resources
2. Apply health rules (from resource overrides)
3. Aggregate health: all healthy = Healthy, any degraded = Degraded
4. Update Application.Status.health.status
5. Update sync result with final reconciliation info
6. Log operation completion

**Key Status Fields Updated**:
- `status.sync.status` - Synced/OutOfSync/Unknown
- `status.sync.revision` - Git commit SHA applied
- `status.health.status` - Healthy/Degraded/Unknown
- `status.conditions[]` - Detailed condition messages
- `status.resources[]` - Per-resource status
- `status.operationState` - Last operation details

---

## 6. Adding a New Sync Strategy

To add a new sync strategy (e.g., a custom wave behavior or pre-sync orchestration), you would need to modify:

### 1. CRD Type Definition
**File**: `pkg/apis/application/v1alpha1/types.go`

Add new strategy type to SyncStrategy struct:
```go
type SyncStrategy struct {
    Apply *SyncStrategyApply `json:"apply,omitempty"`
    Hook  *SyncStrategyHook  `json:"hook,omitempty"`
    // Add new field:
    Custom *SyncStrategyCustom `json:"custom,omitempty"`
}

// New strategy type
type SyncStrategyCustom struct {
    // Define your options
    Option1 string `json:"option1,omitempty"`
    Option2 bool   `json:"option2,omitempty"`
}
```

### 2. Controller Sync Logic
**File**: `controller/sync.go`

Modify `SyncAppState()` function to handle new strategy:
```go
func (m *appStateManager) SyncAppState(app *v1alpha1.Application, state *v1alpha1.OperationState) {
    syncOp := state.SyncResult.Source
    syncStrategy := syncOp.SyncStrategy

    if syncStrategy.Custom != nil {
        // Implement custom sync logic
        // Set up special sync options via sync.WithXXX() calls
    }
}
```

### 3. Sync Options and Wave Handling
**File**: `controller/sync.go` (around line 355)

Add custom sync options when configuring gitops-engine sync:
```go
opts := []sync.SyncOpt{
    // ... existing opts ...
    sync.WithCustomOption(syncOp.SyncStrategy.Custom.Option1),
}
```

### 4. Wave Delay and Orchestration
**File**: `controller/sync.go` (delayBetweenSyncWaves function)

If implementing custom wave behavior, modify wave delay logic:
```go
func delayBetweenSyncWaves(phase common.SyncPhase, wave int, finalWave bool) error {
    // Add custom wave orchestration logic
}
```

### 5. Update OpenAPI Schema
**Files**: `pkg/apis/application/v1alpha1/generated.proto`, `pkg/apis/application/v1alpha1/openapi_generated.go`

These are auto-generated from kubebuilder annotations, so regenerate:
```bash
make manifests  # Regenerates CRD YAML
make codegen   # Regenerates Go code and schemas
```

### 6. Add Tests
**Files**:
- `controller/sync_test.go` - Unit tests for sync logic
- `test/e2e/sync_options_test.go` - E2E test for new strategy

Test structure:
```go
func TestCustomSyncStrategy(t *testing.T) {
    // Set up test application with custom strategy
    app := &v1alpha1.Application{
        Spec: v1alpha1.ApplicationSpec{
            SyncPolicy: &v1alpha1.SyncPolicy{
                SyncOptions: []string{"Custom=true"},
            },
        },
    }
    // Execute sync and verify behavior
}
```

### 7. Documentation and Examples
- Add example in manifests (docs, examples/)
- Update sync strategy documentation
- Add CRD example demonstrating new strategy usage

### 8. Validation (Optional)
**File**: `pkg/apis/application/v1alpha1/types.go` or separate validation file

Add validation logic for new strategy options:
```go
func (s *SyncStrategyCustom) Validate() error {
    // Validate option combinations
    return nil
}
```

### Sequence Summary
1. Define new `SyncStrategyCustom` type in v1alpha1
2. Handle strategy in `controller/sync.go:SyncAppState()`
3. Add custom sync configuration via sync.With*() calls
4. Update wave delay handling if needed
5. Regenerate CRD and OpenAPI schemas
6. Write unit and E2E tests
7. Update documentation and examples

The gitops-engine library (`github.com/argoproj/gitops-engine/pkg/sync`) provides the low-level sync machinery, so the new strategy should ultimately produce the correct sequence of kubectl operations (apply, delete, etc.).
