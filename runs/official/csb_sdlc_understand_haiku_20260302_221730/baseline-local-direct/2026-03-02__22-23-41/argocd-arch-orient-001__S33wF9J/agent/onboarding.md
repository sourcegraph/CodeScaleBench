# Argo CD Codebase Orientation

## 1. Main Entry Points

### 1.1 API Server (`argocd-server`)
**Location:** `/workspace/cmd/argocd-server/commands/argocd_server.go`

**Entry Point Function:** `NewCommand() *cobra.Command`

**Primary Responsibilities:**
- Serves the Argo CD REST and gRPC APIs for managing applications, projects, and clusters
- Provides the WebUI and authentication/authorization (RBAC, OIDC, LDAP)
- Orchestrates communication with other components (repo server, application controller, Redis)
- Handles webhook events from Git providers (GitHub, GitLab, Bitbucket)
- Manages application operations through the AppClient

**Key Configuration:**
- Uses Cobra/Spf13 for CLI flags
- Listens on port 8080 (default) for API server
- Communicates with repo server at `argocd-repo-server:8081` (configurable)
- Manages TLS, authentication, and OIDC configuration through `util/settings/settings.go`

---

### 1.2 Application Controller (`argocd-application-controller`)
**Location:** `/workspace/cmd/argocd-application-controller/commands/argocd_application_controller.go`

**Entry Point Function:** `NewCommand() *cobra.Command`

**Primary Responsibilities:**
- Implements the Kubernetes controller for the Application CRD
- Continuously monitors Application resources and reconciles desired state vs. live state
- Orchestrates the sync pipeline for applications
- Manages application health status and self-healing
- Handles application deletion and cascade cleanup
- Performs sharding and dynamic cluster distribution for scaling

**Key Configuration:**
- Default resync period: 180 seconds (configurable via flags)
- Uses gitops-engine for actual sync operations
- Implements work queues with rate limiting via `pkg/ratelimiter`
- Monitors repo server and manages caching via `util/cache/appstate`
- Supports multiple application namespaces

---

### 1.3 Repository Server (`argocd-repo-server`)
**Location:** `/workspace/cmd/argocd-repo-server/commands/argocd_repo_server.go`

**Entry Point Function:** `NewCommand() *cobra.Command`

**Primary Responsibilities:**
- Maintains a local cache of Git repositories containing application manifests
- Generates Kubernetes manifests from various sources (Kustomize, Helm, plain YAML, CMP)
- Serves manifests to the application controller via gRPC
- Handles Git operations and credential management
- Manages template rendering and build processes
- Supports custom plugins via Config Management Plugin (CMP) interface

**Key Configuration:**
- Listens on port 8081 (default) for gRPC service
- Exposes metrics on port 8084
- Supports TLS and plaintext modes
- Manages Git submodule resolution
- Implements exponential backoff for failed generation attempts

---

### 1.4 ApplicationSet Controller (`argocd-applicationset-controller`)
**Location:** `/workspace/cmd/argocd-applicationset-controller/commands/applicationset_controller.go`

**Entry Point Function:** `NewCommand() *cobra.Command` (in `command` package)

**Primary Responsibilities:**
- Implements controller-runtime based Kubernetes controller for the ApplicationSet CRD
- Generates multiple Application resources from a single ApplicationSet specification
- Supports multiple generators: List, Cluster, Git, Matrix, Merge, Pull Request, SCM Provider
- Handles templating of Application specs with generator-provided values
- Provides progressive sync capabilities for controlled deployments
- Manages ApplicationSet webhooks for Git provider integration

**Key Configuration:**
- Uses controller-runtime's manager pattern (sigs.k8s.io/controller-runtime)
- Integrates with repo server for manifest resolution
- Supports custom SCM providers with root CA configuration
- Implements policy-based ApplicationSet creation validation
- Leader election for HA deployments

---

## 2. Core Packages

### 2.1 API Types and CRDs (`pkg/apis/application/v1alpha1/`)
**Path:** `/workspace/pkg/apis/application/v1alpha1/`

**Responsibility:** Defines all CRD types for Argo CD
- **`types.go`** (141KB): Defines the core CRDs:
  - `Application`: The main resource representing a deployed application
  - `AppProject`: RBAC and policy boundaries for applications
  - `Repository`: Git repository connection details
- **`applicationset_types.go`**: Defines the ApplicationSet CRD for multi-application management
- **`app_project_types.go`**: Project policies and RBAC rules
- **Generated files**: `generated.pb.go` and `zz_generated.deepcopy.go` for protobuf and deep copy support

**Key Structs:**
```
- Application: spec (desired state), status (current state), operation (in-progress operations)
- ApplicationSpec: source, destination, syncPolicy, ignoreDifferences
- SyncPolicy: automated sync rules, sync strategies, window restrictions
- SyncStrategy: apply vs. hook strategies, force flags, resource selection
- SyncWave: ordering of resource application during sync
```

---

### 2.2 Application Controller (`controller/`)
**Path:** `/workspace/controller/`

**Responsibility:** Implements the main reconciliation loop for Applications

**Key Files:**
- **`appcontroller.go`** (92KB): Main controller implementation
  - `ApplicationController` struct: Implements the Kubernetes controller pattern
  - Reconcile loop: Watches Application resources and triggers syncs
  - Main entry point: `ReconcileSharded()` and `Reconcile()`

- **`state.go`**: Application state comparison and health assessment
  - `CompareAppState()`: Diffs desired vs. live state
  - Health calculation and resource tree construction

- **`sync.go`**: Sync orchestration
  - `SyncAppState()`: Orchestrates the sync operation
  - `delayBetweenSyncWaves()`: Implements sync wave hooks from gitops-engine
  - Uses `github.com/argoproj/gitops-engine/pkg/sync` for actual syncing

- **`hook.go`**: Post-delete hook execution
  - Manages hook lifecycle and health monitoring
  - Executes cleanup hooks when application deletion is requested

- **`health.go`**: Health assessment for resources
- **`cache/`**: Application state caching for performance optimization

---

### 2.3 Repository Server (`reposerver/`)
**Path:** `/workspace/reposerver/`

**Responsibility:** Git management and manifest generation

**Key Components:**
- **`repository/repository.go`** (111KB): Main manifest generation logic
  - `Service` struct: gRPC service implementation
  - `GenerateManifest()`: Main entry point for manifest generation
  - `GenerateManifests()`: Core logic supporting:
    - Kustomize rendering via `helmTemplate()` and `kustomizeTemplate()`
    - Helm chart templating
    - Plain YAML manifest discovery
    - Custom Plugin (CMP) execution
  - `findManifests()`: Discovers YAML files in directory structure

- **`cache/`**: Caches manifests and Git metadata to avoid redundant operations
- **`apiclient/`**: gRPC client stubs for communication
- **`metrics/`**: Prometheus metrics for repo operations

---

### 2.4 ApplicationSet Controllers (`applicationset/`)
**Path:** `/workspace/applicationset/`

**Responsibility:** ApplicationSet-specific logic and generators

**Key Directories:**
- **`controllers/applicationset_controller.go`**: Main ApplicationSet reconciliation
  - `ApplicationSetReconciler` struct with controller-runtime
  - Handles generation, templating, and Application creation

- **`generators/`**: Pluggable generator implementations
  - `cluster.go`: Cluster generator - generates Applications for each cluster
  - `git.go`: Git generator - generates from Git directory structure
  - `matrix.go`: Matrix generator - cartesian product of multiple generators
  - `merge.go`: Merge generator - combines multiple generators
  - `plugin.go`: Plugin/CMP generator support
  - `pull_request.go`: PR generator for GitOps workflows
  - `scm_provider.go`: SCM provider discovery (GitHub, GitLab, etc.)

- **`services/`**: Templating and application generation services

---

### 2.5 Client Libraries (`pkg/client/`)
**Path:** `/workspace/pkg/client/`

**Responsibility:** Generated Kubernetes client code for Argo CD CRDs

**Key Contents:**
- **`clientset/versioned/`**: Typed client for Application, AppProject, Repository resources
- **`listers/`**: Kubernetes list/get interfaces for caching
- **`informers/`**: Kubernetes informer factories for event-driven updates

Generated via `client-gen` from OpenAPI schema in the CRDs.

---

### 2.6 Utility Packages (`util/`)
**Path:** `/workspace/util/`

**Key Utilities:**
- **`settings/`**: Loads Argo CD configuration from Kubernetes ConfigMaps/Secrets
  - `ArgoCDSettings` struct: In-memory configuration state
  - `SettingsManager`: Watches and syncs configuration changes

- **`argo/`**: Argo-specific utilities
  - Normalizers for resource comparison
  - Health assessment helpers
  - Application traversal and resource collection

- **`cache/`**: Generic caching infrastructure
  - `appstate/`: Application state caching
  - Redis backing for distributed caching

- **`kube/`**: Kubernetes utilities
  - Resource patching and diff generation
  - Client creation and management

- **`git/`**: Git operations
  - Repository cloning and credential management
  - Commit/ref resolution

- **`helm/`**: Helm-specific operations
  - Chart fetching and template rendering

- **`db/`**: Database utilities for cluster storage
- **`env/`**: Environment variable parsing with type conversion

---

## 3. Configuration Loading

### 3.1 CLI Framework
**Framework:** Cobra + Spf13/pflag (Go's standard CLI framework)

**Pattern:**
```go
func NewCommand() *cobra.Command {
    command := &cobra.Command{
        Use: "argocd-server",
        RunE: func(c *cobra.Command, args []string) error {
            // Component startup logic
        },
    }

    // Add flags to command
    command.Flags().StringVar(&variable, "flag-name", defaultValue, "help text")
    command.Flags().IntVar(&intVar, "int-flag", 8080, "port")

    return command
}
```

**Example from argocd-server:**
- Flags support both CLI arguments and environment variables
- Defaults come from environment variables via `env.StringFromEnv()`, `env.ParseNumFromEnv()`, etc.
- TLS config loaded via `tls.AddTLSFlagsToCmd()`
- Cache config via `servercache.AddCacheFlagsToCmd()`

---

### 3.2 Runtime Configuration (ArgoCDSettings)
**Location:** `/workspace/util/settings/settings.go`

**Loading Mechanism:**
1. **SettingsManager** watches Kubernetes ConfigMaps and Secrets
2. **Configuration Sources:**
   - `argocd-cm`: Application-level ConfigMap (public)
   - `argocd-secret`: Secrets and credentials (restricted)
   - Parsed on-the-fly from ConfigMap data

3. **Key Configuration Struct:**
```go
type ArgoCDSettings struct {
    URL                          string           // External URL for SSO
    DexConfig                   string           // Dex OIDC config YAML
    ServerSignature             []byte           // JWT signing key
    Certificate                 *tls.Certificate // Server TLS cert
    KustomizeBuildOptions       string           // Kustomize CLI params
    AnonymousUserEnabled        bool             // Allow anonymous access
    UserSessionDuration         time.Duration    // Auth token TTL
    WebhookGitHubSecret         string           // Webhook authentication
    // ... many more fields for RBAC, UI, plugins, etc.
}
```

4. **Access Pattern:**
```go
settingsMgr := settings.NewSettingsManager(ctx, clientset, namespace)
argoSettings, err := settingsMgr.GetSettings()
```

---

### 3.3 Component-Specific Configuration

**argocd-server:**
- Flags: `--repo-server`, `--dex-server`, `--port`, `--address`, `--basehref`, `--logformat`
- Settings: Loaded via SettingsManager from ConfigMaps/Secrets
- Cache: Redis-backed via `servercache`

**argocd-application-controller:**
- Flags: `--repo-server-address`, `--resync-period`, `--self-heal-timeout`, `--metrics-port`, `--sharding-algorithm`
- Settings: Application RBAC and resource overrides
- Cache: Application state cache via `util/cache/appstate`

**argocd-repo-server:**
- Flags: `--port`, `--listen-host`, `--repo-cache-expiration`, `--parallelism-limit`
- Environment Variables: `ARGOCD_SYNC_WAVE_DELAY`, `ARGOCD_GIT_SUBMODULE_ENABLED`, git credentials

**argocd-applicationset-controller:**
- Flags: `--metrics-addr`, `--probe-bind-addr`, `--webhook-addr`, `--enable-leader-election`
- Uses controller-runtime manager configuration
- Settings: ApplicationSet generator policies

---

## 4. Test Structure

Argo CD has 266 test files organized into multiple categories:

### 4.1 Unit Tests
**Pattern:** Files named `*_test.go` co-located with implementation

**Examples:**
- `/workspace/controller/appcontroller_test.go`: Tests for controller reconciliation
- `/workspace/reposerver/repository/repository_test.go`: Tests for manifest generation
- `/workspace/applicationset/controllers/applicationset_controller_test.go`: ApplicationSet controller tests
- `/workspace/util/settings/settings_test.go`: Settings management tests

**Framework:** Go's built-in `testing` package with table-driven tests

**Typical Pattern:**
```go
func TestReconcile(t *testing.T) {
    tests := []struct {
        name    string
        app     *Application
        expected bool
    }{
        {"test case 1", app1, true},
    }
    for _, tt := range tests {
        t.Run(tt.name, func(t *testing.T) {
            result := Reconcile(tt.app)
            assert.Equal(t, tt.expected, result)
        })
    }
}
```

---

### 4.2 Integration Tests
**Location:** Various `*_test.go` files that spin up actual Kubernetes objects

**Approach:**
- Use `kubernetes.Interface` and `client.Client` to create real resources
- Use mocking for external services (Git, dex, etc.) via `github.com/stretchr/testify/mock`
- Example: `controller_test.go` creates Application CRs and tests reconciliation

**Test Utilities:**
- `/workspace/test/testutil.go`: Helper functions for test setup
- `/workspace/test/testdata.go`: Shared test data and fixtures
- Fixtures in `/workspace/test/fixture/`: Reusable test objects

---

### 4.3 End-to-End (E2E) Tests
**Location:** `/workspace/test/e2e/`

**Structure:**
- **Fixture-based:** Test fixtures in `/workspace/test/e2e/fixture/app/`, `/workspace/test/e2e/fixture/cluster/`, etc.
- **Real Kubernetes clusters:** Tests run against actual K8s clusters (usually Kind/Minikube)
- **Component stack:** Spins up full Argo CD stack (API server, controllers, repo server)
- **Git repository:** Uses real or mock Git repositories for testing

**Test Files:**
- `app_management_test.go` (95KB): Core application lifecycle tests
- `applicationset_test.go` (109KB): ApplicationSet generator and controller tests
- `helm_test.go`: Helm-specific rendering and caching tests
- `custom_tool_test.go`: Custom manifest generation tests
- `cluster_generator_test.go`: Cluster generator tests
- `app_autosync_test.go`: Automated sync policy tests
- `deployment_test.go`: Multi-application deployment scenarios

**Framework:** Go's `testing` package with custom harness at `/workspace/test/fixture/`

**Typical E2E Test:**
```go
func TestAppSync(t *testing.T) {
    Given(t).
        GitRepository().
        When().
        CreateApp().
        Sync().
        Then().
        Expect(SyncStatusIs(SyncStatusSynced)).
        Expect(Health(HealthStatusHealthy))
}
```

---

## 5. Application Sync Pipeline

The sync pipeline traces an Application resource from CRD definition to actual kubectl apply in the target cluster.

### Stage 1: CRD Definition & Validation
**Files:** `/workspace/pkg/apis/application/v1alpha1/types.go`

**Key Structs:**
- `Application`: Top-level CRD with `.spec` (desired), `.status` (observed), `.operation` (in-progress)
- `ApplicationSpec.Source`: Reference to Git repo, path, revision, target repository
- `ApplicationSpec.Destination`: Target K8s cluster, namespace, resource tracking method
- `ApplicationSpec.SyncPolicy`: Sync automation, strategy, and policies
- `ApplicationStatus.Sync`: Current sync state (synced/out-of-sync/unknown)
- `ApplicationStatus.Health`: Resource health aggregation

**Validation:**
- OpenAPI schema validation at `/workspace/pkg/apis/application/v1alpha1/openapi_generated.go`
- Custom validation rules in Application controller before processing

---

### Stage 2: Controller Reconciliation Loop
**Files:** `/workspace/controller/appcontroller.go`

**Flow:**
1. **Watcher:** Kubernetes informer triggers reconciliation on Application changes
2. **Reconcile Entry:** `ApplicationController.Reconcile(ctx, req)`
3. **State Retrieval:** Fetch Application CR from cluster
4. **Sharding Check:** Verify this controller instance owns this application (for multi-instance scaling)
5. **Lock Acquisition:** Distributed lock to prevent concurrent operations
6. **Sync Trigger Evaluation:**
   - Check sync windows (time-based gates)
   - Evaluate automated sync policies
   - Handle manual sync requests
   - Detect out-of-sync conditions

**Key Functions:**
- `Reconcile()`: Main loop implementation (~400 lines)
- `syncApp()`: Initiates sync operation
- `refreshAppStatus()`: Compares desired vs. live state
- `isSyncNeeded()`: Determines if application requires reconciliation

---

### Stage 3: Manifest Generation (Repo Server)
**Files:** `/workspace/reposerver/repository/repository.go`

**Flow:**
1. **Manifest Request:** Controller sends request to repo server with:
   - Git repository URL
   - Revision (commit SHA, branch, tag)
   - Application path in repo
   - Build parameters (Kustomize args, Helm values, etc.)

2. **GenerateManifest() Entry:** `/workspace/reposerver/repository/repository.go:515`

3. **Source Type Detection:** `GetAppSourceType()` determines manifest source:
   - Plain YAML directory
   - Kustomize build
   - Helm chart
   - Custom plugin (CMP)
   - Combination (multiple sources)

4. **Rendering by Type:**
   - **Kustomize:** `kustomizeTemplate()` runs `kustomize build`
   - **Helm:** `helmTemplate()` runs `helm template` with values
   - **Plain YAML:** `findManifests()` discovers `*.yaml`/`*.yml` files recursively
   - **CMP:** Executes custom tool via plugin interface

5. **Output:** Returns list of `unstructured.Unstructured` objects (K8s resources as YAML)

**Caching:**
- Results cached in Redis via `/workspace/reposerver/cache/`
- Cache key includes commit SHA + build parameters
- Avoids redundant manifest generation

---

### Stage 4: Sync Strategy & Execution
**Files:** `/workspace/controller/sync.go` + `/workspace/controller/state.go`

**Flow:**
1. **State Comparison:** `state.go` compares generated manifests vs. live cluster state
   - Uses gitops-engine's `diff` logic
   - Applies `ignoreDifferences` rules from ApplicationSpec
   - Determines resources to create/update/delete

2. **Sync Strategy Selection:** From `ApplicationSpec.SyncPolicy.SyncStrategy`:
   - **Apply Strategy:** Direct `kubectl apply` with optional force flag
   - **Hook Strategy:** Runs lifecycle hooks (PreSync, Sync, PostSync) annotated on resources

3. **Sync Wave Ordering:** Resources are synced in waves:
   - Wave number from `metadata.annotations['argocd.argoproj.io/sync-wave']`
   - Default wave = 0
   - Sequential execution with `delayBetweenSyncWaves()` hook
   - Allows staged rollouts and dependency ordering

4. **Gitops-Engine Integration:** `/workspace/controller/sync.go:348`
   ```go
   sync.WithOperationSettings(
       syncOp.DryRun,
       syncOp.Prune,  // Delete resources not in generated manifests
       syncOp.SyncStrategy.Force()
   )
   ```

5. **Resource Patching & Application:**
   - Strategic merge patch for ConfigMaps/Secrets
   - Three-way JSON merge patch for other resources
   - Respects Kubernetes server-side diff for validation
   - Updates metadata (tracking labels, finalizers)

6. **Hook Execution:** (if using SyncStrategyHook)
   - Pre-sync hooks: Run before applying any resources
   - Sync hooks: Run as part of the sync wave
   - Post-sync hooks: Run after all resources applied
   - Health checks: Monitor hook completion

---

### Stage 5: Status Update & Health Assessment
**Files:** `/workspace/controller/health.go`, `/workspace/controller/state.go`

**Flow:**
1. **Live State Query:** Queries K8s API for all deployed resources
2. **Health Assessment:** For each resource:
   - Calls `github.com/argoproj/gitops-engine/pkg/health.GetResourceHealth()`
   - Evaluates Deployment readiness, StatefulSet status, Pod conditions, etc.
   - Handles custom health via Lua scripts (configurable)

3. **Sync Status Determination:**
   - **Synced:** All resources match desired spec
   - **OutOfSync:** Differences detected
   - **Unknown:** Couldn't compare (missing permission, API error)

4. **Application Status Update:** `Application.Status` fields updated:
   ```
   .status.sync.status       = SyncStatusSynced
   .status.health.status     = HealthStatusHealthy
   .status.resources[]       = List of deployed resources with health
   .status.operationState    = Operation result (if applicable)
   ```

5. **Observability:**
   - Prometheus metrics via `/workspace/controller/metrics/`
   - Event recording to Kubernetes Event API
   - Condition updates for user visibility

---

### Stage 6: Recursive Resource Tracking
**Key Concept:** Argo CD automatically tracks child resources even if not explicitly in manifests

**Examples:**
- Deployment creates ReplicaSets, Pods
- StatefulSet creates PersistentVolumes
- Service creates Endpoints

**Implementation:** `state.go` uses Kubernetes ownership references and label-based tracking to build resource tree

**Resource Tree:** Stored in `Application.Status.Resources`, provides:
- Complete picture of all deployed K8s objects
- Dependency relationships
- Individual health status for each resource

---

## 6. Adding a New Sync Strategy

To add a new sync strategy (e.g., custom wave behavior, conditional resource application), follow this sequence:

### Step 1: Define Strategy Type in CRD
**File:** `/workspace/pkg/apis/application/v1alpha1/types.go`

**Action:** Add new strategy struct:
```go
// In SyncStrategy struct (around line 1342)
type SyncStrategy struct {
    Apply  *SyncStrategyApply  `json:"apply,omitempty"`
    Hook   *SyncStrategyHook   `json:"hook,omitempty"`
    // ADD YOUR NEW STRATEGY HERE:
    Custom *SyncStrategyCustom `json:"custom,omitempty"`
}

// Define your strategy options
type SyncStrategyCustom struct {
    // Fields for your strategy configuration
    WaveDelay    *int64
    ParallelWaves bool
}

// Update validation/helper methods
func (m *SyncStrategy) IsApplyStrategy() bool { /* update logic */ }
func (m *SyncStrategy) Force() bool { /* update logic */ }
```

---

### Step 2: Update Protobuf Definitions
**File:** `/workspace/pkg/apis/application/v1alpha1/generated.proto`

**Action:** Add proto message for new strategy:
```protobuf
message SyncStrategyCustom {
    optional int64 waveDelay = 1;
    optional bool parallelWaves = 2;
}

// Update SyncStrategy message
message SyncStrategy {
    optional SyncStrategyApply apply = 1;
    optional SyncStrategyHook hook = 2;
    optional SyncStrategyCustom custom = 3;  // ADD THIS
}
```

**Regenerate:** Run code generation:
```bash
cd /workspace
./hack/generate-api-docs.sh  # Regenerates generated.pb.go, zz_generated.deepcopy.go
```

---

### Step 3: Implement Strategy in Controller
**File:** `/workspace/controller/sync.go`

**Action:** Add handler in `SyncAppState()`:
```go
func (m *appStateManager) SyncAppState(app *v1alpha1.Application, state *v1alpha1.OperationState) {
    // ... existing code ...

    // Line ~348: Add condition for new strategy
    if syncOp.SyncStrategy != nil && syncOp.SyncStrategy.Custom != nil {
        // Implement custom sync behavior
        m.executeCustomSync(syncOp, app)
        return
    }

    // Continue with default or hook/apply strategies
}
```

**Implementation Pattern:**
```go
func (m *appStateManager) executeCustomSync(syncOp *v1alpha1.SyncOperation, app *v1alpha1.Application) {
    // 1. Get resources to sync from controller via GetRepoObjs()
    targets, _, _, err := m.GetRepoObjs(app, app.Spec.GetSources(), ...)

    // 2. Compare with live state from GetLiveObjs()
    liveObjs, err := m.GetLiveObjs(app, ...)

    // 3. Determine sync order based on custom logic
    // (e.g., custom wave algorithm, dependencies, conditions)
    syncOrder := m.calculateSyncOrder(targets, liveObjs, syncOp.SyncStrategy.Custom)

    // 4. Execute sync via gitops-engine
    syncOp := sync.SyncTask{
        // ... populate task fields ...
        // Pass custom hooks if needed:
        sync.WithSyncWaveHook(customWaveHook),
    }
    syncResult := sync.Sync(syncOp)

    // 5. Update application status
    state.SyncResult = syncResult
}
```

---

### Step 4: Add CLI Support
**File:** `/workspace/cmd/argocd/commands/app.go`

**Action:** Add flags for new strategy:
```go
// In NewAppSyncCommand() or similar (around line 600)
syncCmd.Flags().BoolVar(&customWaves, "custom-waves", false, "Enable custom wave behavior")
syncCmd.Flags().Int64Var(&waveDelay, "custom-wave-delay", 5, "Delay between custom waves in seconds")

// Parse and apply:
syncOp.SyncStrategy.Custom = &v1alpha1.SyncStrategyCustom{
    WaveDelay:    &waveDelay,
    ParallelWaves: customWaves,
}
```

---

### Step 5: Update ApplicationSet Integration (if needed)
**Files:** `/workspace/applicationset/services/`, `/workspace/server/application/`

**Action:** If ApplicationSet should support the new strategy:
1. Update ApplicationSet template generation in `/workspace/applicationset/services/`
2. Ensure Application spec generated from ApplicationSet includes new strategy fields

---

### Step 6: Add E2E Tests
**File:** `/workspace/test/e2e/` (create new file like `app_custom_sync_test.go`)

**Test Pattern:**
```go
func TestCustomSyncStrategy(t *testing.T) {
    Given(t).
        GitRepository().
        When().
        CreateApp(). // Includes SyncStrategy.Custom configuration
        Sync().
        Then().
        Expect(SyncStatusIs(SyncStatusSynced)).
        Expect(CustomWaveBehavior()).  // Custom assertion
}
```

---

### Step 7: Document Changes
1. Update OpenAPI schema (auto-generated)
2. Add usage examples in comments
3. Document strategy behavior in design doc

---

## Summary of Key Packages

| Package | Purpose | Key Files |
|---------|---------|-----------|
| `pkg/apis/application/v1alpha1/` | CRD definitions | `types.go`, `applicationset_types.go` |
| `controller/` | Application reconciliation | `appcontroller.go`, `sync.go`, `state.go` |
| `reposerver/` | Manifest generation | `repository/repository.go`, `cache/` |
| `applicationset/` | ApplicationSet support | `controllers/`, `generators/`, `services/` |
| `server/` | API server | `server.go`, `application/`, `applicationset/` |
| `util/settings/` | Configuration management | `settings.go` |
| `util/cache/` | Distributed caching | `appstate/` for Application caching |
| `pkg/client/` | Generated K8s clients | `clientset/`, `listers/`, `informers/` |

---

## Architecture Patterns

1. **Controller Pattern:** Kubernetes-native reconciliation with informers and work queues
2. **Multi-Component Communication:** gRPC for inter-service (API server ↔ repo server ↔ controller)
3. **Gitops-Engine Integration:** Leverages mature sync logic from `github.com/argoproj/gitops-engine`
4. **Distributed Configuration:** Kubernetes ConfigMaps/Secrets as source of truth
5. **Event-Driven:** Watchers, informers, and webhooks trigger reconciliation
6. **Caching Layers:** Multi-level (in-memory, Redis) for performance
7. **Pluggable Extensions:** CMP support, custom health rules via Lua, RBAC policies

---

## Getting Started

**Recommended Order for Exploration:**
1. Read `/workspace/pkg/apis/application/v1alpha1/types.go` to understand CRDs
2. Explore `/workspace/controller/appcontroller.go` reconciliation loop
3. Trace one full sync in `/workspace/controller/sync.go` and `/workspace/reposerver/repository/repository.go`
4. Review a simple E2E test in `/workspace/test/e2e/app_management_test.go`
5. Run `make test` locally to understand testing patterns
6. Deploy with `make manifests` and experiment with test applications
