# Argo CD Sync Reconciliation Pipeline

## Q1: Reconciliation Triggering and Git Fetch

### Reconciliation Cycle Triggers

Argo CD triggers reconciliation through four primary mechanisms:

1. **Periodic Soft Refresh (Time-based)**
   - Default sync period controlled by `statusRefreshTimeout`
   - Triggered when `app.Status.ReconciledAt == nil || app.Status.ReconciledAt.Add(statusRefreshTimeout).Before(time.Now().UTC())`
   - File: `/workspace/controller/appcontroller.go:1892`

2. **Periodic Hard Refresh (Full Re-comparison)**
   - Controlled by `statusHardRefreshTimeout`
   - Triggers complete re-comparison when: `app.Status.ReconciledAt.Add(statusHardRefreshTimeout).Before(time.Now().UTC())`
   - File: `/workspace/controller/appcontroller.go:1893`

3. **Application Spec Changes (Resource Update Events)**
   - Detected via Kubernetes informer: `newApplicationInformerAndLister()`
   - Watches for changes to: `spec.source`, `spec.destination`, `spec.ignoreDifferences`, `spec.syncPolicy.managedNamespaceMetadata`
   - File: `/workspace/controller/appcontroller.go:2414-2441`

4. **Manual User-Requested Refresh**
   - Detected by: `if requestedType, ok := app.IsRefreshRequested(); ok`
   - Supports Normal or Hard refresh types
   - File: `/workspace/controller/appcontroller.go:1895`

5. **Live State Drift Detection (Related Resource Changes)**
   - LiveStateCache detects changes to managed resources
   - Calls `handleObjectUpdated()` with appropriate refresh level
   - File: `/workspace/controller/appcontroller.go:419-479`

### Controller-to-RepoServer Communication

**Primary Method**: `GetRepoObjs()` → `repoClient.GenerateManifest()`

**Request Flow**:
1. ApplicationController enqueues app in `appRefreshQueue`
2. `processAppRefreshQueueItem()` processes queue items
3. Calls `needRefreshAppStatus()` to determine refresh type (lines 1886-1937)
4. `GetRepoObjs()` creates gRPC connection and calls `GenerateManifest()`
5. File: `/workspace/controller/state.go:269`

**Detection Method**: `needRefreshAppStatus(app, statusRefreshTimeout, statusHardRefreshTimeout) (bool, RefreshType, CompareWith)`
- Checks timeout conditions and spec changes
- Returns boolean indicating if refresh is needed
- File: `/workspace/controller/appcontroller.go:1886-1937`

**Enqueue Method**: `requestAppRefresh(appName string, compareWith *CompareWith, after *time.Duration)`
- Stores refresh request in `ctrl.refreshRequestedApps[appName]`
- Adds app to `appRefreshQueue` with optional rate limiting
- File: `/workspace/controller/appcontroller.go:943-960`

### ManifestRequest Data Structure

**Type**: `apiclient.ManifestRequest` (gRPC message)

**Core Fields**:
- `Repo`: Repository credentials and authentication details
- `Revision`: Git revision, branch, or tag to fetch
- `AppName`: Application qualified name (namespace/name)
- `Namespace`: Target deployment namespace
- `ApplicationSource`: Kustomize/Helm/Plugin-specific configuration
- `Path`: Path within repository for manifest sources
- `Chart`: Helm chart name (for Helm sources)

**Build Environment Context**:
- `KubeVersion`: Target cluster Kubernetes version
- `ApiVersions`: Supported API versions from destination cluster
- `HelmOptions`: Helm rendering options
- `KustomizeOptions`: Kustomize build options
- `EnabledSourceTypes`: Available plugins and config management tools

**Request Modifiers**:
- `NoCache`: Bypass manifest caching
- `NoRevisionCache`: Force resolution of git revision
- `VerifySignature`: Enable GPG signature verification

**Multi-source Support**:
- `HasMultipleSources`: Boolean flag indicating multiple sources
- `RefSources`: Referenced source revisions map
- `Repos`: All permitted repositories for multi-source scenarios

**Security/Tracking**:
- `ProjectName`: AppProject name for RBAC
- `ProjectSourceRepos`: Permitted source repositories
- `TrackingMethod`: Resource tracking approach (annotation, label)

**File Reference**: `/workspace/reposerver/repository/repository.proto:10-45`
**Implementation**: `/workspace/controller/state.go:269-293`

### Git Repository Fetch and Caching Strategy

**Three-Level Cache Architecture**:

1. **Revision Cache (In-Memory)**
   - Caches resolved commit SHAs for branches/tags
   - Prevents duplicate `git ls-remote` calls
   - Default TTL: 3 minutes (ARGOCD_RECONCILIATION_TIMEOUT)
   - Lock timeout: 10 seconds prevents concurrent requests for same revision
   - File: `/workspace/reposerver/cache/cache.go`

2. **Manifest Cache**
   - Stores pre-generated manifests by source configuration hash
   - Cache key includes: ApplicationSource hash, cluster info, tracking method
   - Prevents redundant manifest generation for identical inputs
   - File: `/workspace/reposerver/repository/repository.go:289-454`

3. **Git Repository Cache (Disk-Based)**
   - Each repository gets randomized temp directory path
   - Initialized via: `s.gitRepoPaths.GetPath(git.NormalizeGitURL(repo.Repo))`
   - Default expiration: 24 hours (ARGOCD_REPO_CACHE_EXPIRATION)
   - File: `/workspace/reposerver/repository/repository.go:2409`

**Git Fetch Process**:

1. **Client Creation**: `newClient(repo *v1alpha1.Repository, opts ...git.ClientOpts) (git.Client, error)`
   - Gets or creates randomized repo path
   - Applies git credentials from secret store
   - File: `/workspace/reposerver/repository/repository.go:2408-2415`

2. **Revision Resolution**: `newClientResolveRevision(repo, revision, opts) (git.Client, string, error)`
   - Creates git client
   - Calls `gitClient.LsRemote(revision)` to resolve to commit SHA
   - Results cached in revision cache
   - File: `/workspace/reposerver/repository/repository.go:2419-2430`

3. **Repository Operation**: `runRepoOperation(ctx, revision, repo, source, ...)`
   - Acquires semaphore lock for parallelism control
   - For Git sources: `checkoutRevision()` performs:
     - `git fetch` to get latest refs
     - `git checkout <commit>` to checkout specific revision
     - Submodule handling (if enabled)
   - For Helm sources: Downloads and extracts chart
   - File: `/workspace/reposerver/repository/repository.go:289-454`

4. **Lock-Based Concurrency**: `repoLock.Lock(gitClient.Root(), revision, ...)`
   - Repository-level lock prevents duplicate concurrent fetches
   - Semaphore controls total parallelism
   - File: `/workspace/reposerver/repository/repository.go:383`

5. **Checkout Implementation**: `checkoutRevision(gitClient, revision, submoduleEnabled)`
   - Initializes directory with restricted permissions (0o700)
   - Performs git operations in locked directory
   - Removes permissions after completion (0o000)
   - File: `/workspace/reposerver/repository/repository.go:2495+`

---

## Q2: Manifest Generation and Rendering

### Config Management Tool Detection

**Two-Phase Detection**:

1. **Explicit Type from ApplicationSource Spec**
   - `GetAppSourceType()` checks `source.ExplicitType()`
   - If `source.Helm != nil` → Helm type
   - If `source.Kustomize != nil` → Kustomize type
   - If `source.Directory != nil` → Directory type
   - If `source.Plugin != nil` → Plugin type
   - Multiple types set triggers error
   - File: `/workspace/util/app/discovery/discovery.go:36-82`

2. **Automatic Discovery (if explicit type not set)**
   - **Config Management Plugin (CMP)**: First priority
     - Checks `common.GetPluginSockFilePath()` for available plugins
     - Queries each plugin via `DetectConfigManagementPlugin()` / `cmpSupports()`
     - Named plugins in ApplicationSource forced to be used
   - **Helm**: Looks for `Chart.yaml` in directory
   - **Kustomize**: Looks for `kustomization.yaml`, `kustomization.yml`, or `Kustomization`
   - **Directory**: Default fallback for plain YAML/JSON files

**Helper Method**: `(source *ApplicationSource) IsHelm() bool`
- Returns true if `source.Chart != ""`
- File: `/workspace/pkg/apis/application/v1alpha1/types.go`

### Manifest Generation Sequence

**Overall Flow**:

1. **GenerateManifest()** (gRPC entry point, lines 518-586)
   - Sets up cache function for early return on cache hit
   - File: `/workspace/reposerver/repository/repository.go:518-586`

2. **getManifestCacheEntry()** (manifest cache check)
   - Early return if manifest found and valid
   - Includes error caching mechanism

3. **runRepoOperation()** (Git/Helm preparation, lines 289-454)
   - For Helm: Resolves helm client & extracts chart
   - For Git: Clones/checkouts repo to specified revision
   - Acquires semaphore lock (parallelism control)
   - File: `/workspace/reposerver/repository/repository.go:289-454`

4. **runManifestGen()** (async operation setup)
   - Creates channels for async manifest generation
   - Handles multi-source reference resolution

5. **runManifestGenAsync()** (async execution, lines 704-812)
   - Handles multi-source RefSources references
   - Calls `GenerateManifests()`
   - Handles cache update on success or error caching on failure
   - File: `/workspace/reposerver/repository/repository.go:704-812`

6. **GenerateManifests()** (core generation logic, lines 1421-1522)
   - Determines source type via `GetAppSourceType()`
   - Routes to appropriate generator:
     - **Helm**: `helmTemplate()` - renders Helm chart
     - **Kustomize**: `kustomize.NewKustomizeApp().Build()` - builds Kustomize overlay
     - **Plugin/CMP**: `runConfigManagementPluginSidecars()` - executes CMP
     - **Directory**: `findManifests()` - discovers raw YAML/JSON files
   - Processes manifests (applies tracking labels, sets namespace)
   - Returns `ManifestResponse`
   - File: `/workspace/reposerver/repository/repository.go:1421-1522`

### Manifest Caching Mechanisms

**Cache Key Construction** (lines 293-304):
```
mfst|<trackingKey>|<appName>|<revision>|<namespace>|<appSourceHash+refSourceCommitSHAsHash+clusterInfoHash>|<installationID>
```

**Cache Key Components**:
- Tracking method and app label key
- Application name
- Git revision (resolved commit SHA)
- Target namespace
- Hash of ApplicationSource (all fields)
- Hash of referenced source commit SHAs (multi-source)
- Hash of cluster info (KubeVersion, APIVersions)
- Installation ID
- File: `/workspace/reposerver/cache/cache.go:293-304`

**Cache Storage Structure** (`CachedManifestResponse`):
- `ManifestResponse`: Generated manifests
- `CacheEntryHash`: FNV-64a hash for corruption detection
- `MostRecentError`: Last error message (for error caching)
- `FirstFailureTimestamp`: When errors started being cached
- `NumberOfConsecutiveFailures`: Failure count
- `NumberOfCachedResponsesReturned`: Cache hit count

**Cache Invalidation Triggers**:

1. **Hash Mismatch** (lines 347-359)
   - If FNV hash doesn't match, cache deleted (ErrCacheMiss)
   - File: `/workspace/reposerver/cache/cache.go:347-359`

2. **Request Flags**:
   - `NoCache=true`: Bypass manifest cache entirely
   - `NoRevisionCache=true`: Skip revision caching

3. **Error Cache Pause Mechanism** (lines 896-950)
   - On repeated failures exceeding `PauseGenerationAfterFailedGenerationAttempts`:
     - Returns cached error for `PauseGenerationOnFailureForMinutes` duration
     - OR after `PauseGenerationOnFailureForRequests` cached responses returned
     - Then resets and retries
   - File: `/workspace/reposerver/repository/repository.go:896-950`

4. **Source Changes**:
   - Cache key includes ref source commit SHAs, so any referenced source changes invalidate
   - Any change to ApplicationSource fields changes hash

5. **Configuration Changes**:
   - KubeVersion change
   - APIVersions change
   - Tracking method change
   - App label key change

**Expiration Times**:
- Repo cache: 24 hours (ARGOCD_REPO_CACHE_EXPIRATION)
- Revision cache: 3 minutes (ARGOCD_RECONCILIATION_TIMEOUT)
- Revision cache lock timeout: 10 seconds (ARGOCD_REVISION_CACHE_LOCK_TIMEOUT)

### ManifestResponse Data Structure

**Type**: `repository.ManifestResponse` (gRPC message)

**Response Fields** (from proto):
- `manifests`: Array of generated Kubernetes resources as JSON strings
  - Each resource is a JSON-encoded unstructured object with tracking labels
  - Contains all fields necessary for diff computation and sync
  - File: `/workspace/reposerver/repository/repository.proto:92-103`

- `namespace`: Target deployment namespace
  - Derived from ApplicationSource or default

- `revision`: Resolved git commit SHA
  - Returned even for Helm/chart sources (if deployed from git repo)
  - Used for reconciliation result tracking

- `sourceType`: String representation of source type
  - Values: "Helm", "Kustomize", "Directory", "Plugin"
  - Used to indicate which generation tool was used
  - File: `/workspace/reposerver/repository/repository.proto:92-103`

- `verifyResult`: GPG signature verification output
  - Non-empty only for signed Git commits
  - Contains git verify-commit output

- `commands`: Shell commands executed during generation
  - Examples: `helm template ...`, `kustomize build ...`, CMP command
  - Useful for debugging and auditing

**Processing Post-Generation**:
1. Manifests converted to unstructured.Unstructured objects
2. Tracking labels applied (via resource tracking method)
3. Namespace assigned to namespace-scoped resources
4. Ready for comparison against live cluster state

---

## Q3: Diff Computation Between Desired and Live State

### Live State Fetching Component

**Primary Interface**: `LiveStateCache` (`/workspace/controller/cache/cache.go`)

**Key Methods**:
- `GetVersionsInfo(serverURL string) (string, []kube.APIResourceInfo, error)` - Get cluster version and resource types
- `GetClusterCache(server string) (clustercache.ClusterCache, error)` - Get cluster-specific cache
- `GetManagedLiveObjs(a *appv1.Application, targetObjs []*unstructured.Unstructured) (map[kube.ResourceKey]*unstructured.Unstructured, error)` - Fetch live objects for application

**Implementation**:
- Built on `clustercache.ClusterCache` from gitops-engine
- Maintains watch on all cluster resources using Kubernetes informers
- Automatically syncs cluster state with configurable resync intervals (default: 12 hours)
- Caches resources with metadata: health status, networking info, pod info
- Filters resources by namespace and cluster-scoped resources
- Tracks app ownership using resource tracking labels/annotations
- File: `/workspace/controller/cache/cache.go`

**Integration in CompareAppState** (line 611):
```go
liveObjByKey, err := m.liveStateCache.GetManagedLiveObjs(app, targetObjs)
```
- File: `/workspace/controller/state.go:611`

### Resource Normalization Before Comparison

**Two-Stage Normalization Process**:

#### Stage 1: Pre-Diff Normalization (`preDiffNormalize()`, lines 412-446)
- **Resource Tracking Normalization**:
  - Creates `resourceTracking := argo.NewResourceTracking()`
  - Calls `resourceTracking.Normalize(target, live, appLabelKey, trackingMethod)`
  - Removes tracking labels/annotations that Argo CD adds
  - File: `/workspace/util/argo/diff/diff.go:412-446`

- **Managed Fields Normalization**:
  - For resources with `ManagedFieldsManagers` in ignoreDifferences
  - Calls `managedfields.Normalize(live, target, trustedManagers, ...)`
  - Gives precedence to trusted field managers (e.g., controllers)
  - Prevents false diffs from field ownership changes
  - File: `/workspace/util/argo/diff/diff.go:412-446`

#### Stage 2: Full Diff Normalization (Composable Normalizers)

**Type**: `composableNormalizer` with pluggable normalizer chain

**Normalizers Applied**:

1. **IgnoreNormalizer**:
   - Removes fields based on ignore rules from `ignoreDifferences`
   - Supports three specification formats:
     - **JSONPointers**: RFC 6902 JSON Patch format (e.g., `/spec/replicas`)
     - **JQPathExpressions**: JQ query language for complex field selection
     - **ManagedFieldsManagers**: Field ownership-based ignoring
   - File: `/workspace/util/argo/diff/diff.go`

2. **KnownTypesNormalizer**:
   - Re-formats custom Kubernetes fields for type consistency
   - Parses Kubernetes types: `core/Quantity`, `meta/v1/Duration`
   - Handles resource field parsing from `ResourceOverride`
   - Ensures numeric/string consistency between live and desired
   - File: `/workspace/util/argo/diff/normalize.go`

**DiffConfigBuilder Construction** (lines 704-761):
```go
diffConfigBuilder := argodiff.NewDiffConfigBuilder().
    WithDiffSettings(app.Spec.IgnoreDifferences, resourceOverrides,
        compareOptions.IgnoreAggregatedRoles, m.ignoreNormalizerOpts)
```
- File: `/workspace/controller/state.go:704-761`

### Diff Strategies

**Strategy Selection Based on Sync Options**:

1. **Standard 3-Way Merge Diff (Default)**
   - Uses kubectl's built-in 3-way merge algorithm
   - Compares: live state, desired state, last applied state
   - Detects user modifications vs deployment changes
   - Works with standard Kubernetes resources
   - File: `/workspace/controller/state.go` (default behavior)

2. **Structured Merge Diff (SMD)**
   - Uses Kubernetes structured merge patch algorithm
   - Tracks field ownership at the per-field level
   - Supports Server-Side Apply (SSA) compatible field tracking
   - **Enablement** (lines 754-756):
     ```go
     if app.Spec.SyncPolicy != nil && app.Spec.SyncPolicy.SyncOptions.HasOption("ServerSideApply=true") {
         diffConfigBuilder.WithStructuredMergeDiff(true)
     }
     ```
   - File: `/workspace/controller/state.go:754-756`

3. **Server-Side Dry-Run Diff (SSD)**
   - Performs dry-run apply on actual Kubernetes API server
   - Detects real-world conflicts before syncing
   - More accurate but slower and API-intensive
   - **Enablement** (lines 709-751):
     - Global default: `--server-side-diff` CLI flag
     - Per-app override: `argocd.argoproj.io/compare-result: ServerSideDiff=true` annotation
     - Per-app disable: `ServerSideDiff=false` annotation overrides global
     - File: `/workspace/controller/state.go:709-751`

### Diff Result Representation

**Data Structures** (from gitops-engine):

**DiffResult** (per-resource):
- `Modified: bool` - true if live differs from desired
- `NormalizedLive: []byte` - normalized live state as JSON
- `PredictedLive: []byte` - what live state will be after apply

**DiffResultList**:
- `Diffs: []DiffResult` - Results for each resource
- `Modified: bool` - Overall modification flag

**ResourceStatus** (per-resource):
```go
type ResourceStatus struct {
    Group                   string              // API group
    Kind                    string              // Resource kind
    Version                 string              // API version
    Name                    string              // Resource name
    Namespace               string              // Namespace
    Status                  SyncStatusCode      // Synced/OutOfSync/Unknown
    Health                  *HealthStatus       // Resource health
    RequiresPruning         bool                // Exists in cluster but not in Git
    RequiresDeletionConfirm bool                // Deletion requires confirmation
    Orphaned                bool                // Marked for deletion but not synced
}
```
- File: `/workspace/pkg/apis/application/v1alpha1/types.go`

**SyncStatusCode Values**:
```go
const (
    SyncStatusCodeUnknown   = "Unknown"   // Status unknown (comparison errors)
    SyncStatusCodeSynced    = "Synced"    // Desired == Live (after normalization)
    SyncStatusCodeOutOfSync = "OutOfSync" // Desired != Live
)
```

### Out-of-Sync Determination Logic

**SyncStatus Assignment** (lines 823-875):

A resource is marked **OutOfSync** if ANY of these conditions are true:

1. **DiffResult.Modified == true**
   - Live state differs from desired after normalization
   - File: `/workspace/controller/state.go:823-875`

2. **RequiresPruning: targetObj == nil && liveObj != nil**
   - Extra resource exists in cluster but not defined in Git
   - Can be excluded if `IgnoreExtraneous` annotation present
   - File: `/workspace/controller/state.go:823-875`

3. **Missing Resource: targetObj != nil && liveObj == nil**
   - Resource defined in Git but doesn't exist on cluster
   - Needs to be synced
   - File: `/workspace/controller/state.go:823-875`

4. **Comparison Failure: failedToLoadObjs == true**
   - If unable to load either desired or live objects
   - Status set to **Unknown** instead of OutOfSync
   - File: `/workspace/controller/state.go:823-875`

5. **Managed Namespace Changes: app.HasChangedManagedNamespaceMetadata()**
   - Namespace metadata managed by Argo CD changed
   - File: `/workspace/controller/state.go:823-875`

**Special Cases**:
- Managed namespaces with `managedNamespaceMetadata` excluded from out-of-sync check
- Resource hooks and skipped resources don't affect overall sync status
- Shared resources generate warnings but can still sync

---

## Q4: Sync Operation Execution

### Sync Phase and Wave Orchestration

**Three Sync Phases** (from gitops-engine `synccommon.SyncPhase`):

1. **PreSync Phase**
   - Executes before main resource application
   - Used for setup tasks: database migrations, data preparation
   - Can have multiple waves with configurable delays

2. **Sync Phase**
   - Main phase where resources are applied to cluster
   - Follows PreSync completion
   - Respects wave ordering (lowest to highest)

3. **PostSync Phase**
   - Executes after main resources are synced
   - Used for post-deployment validation or cleanup
   - Only if Sync phase succeeds

**Wave Orchestration**:

1. **Wave Extraction** (from `argocd.argoproj.io/sync-wave` annotation)
   - `syncwaves.Wave(obj)` reads annotation value
   - Converts to integer for ordering
   - Default wave: 0 if annotation absent
   - File: `/workspace/controller/sort_delete.go`

2. **Wave Delay Between Iterations** (lines 576-589)
   ```go
   func delayBetweenSyncWaves(phase common.SyncPhase, wave int, finalWave bool) error {
       if !finalWave {
           delaySec := 2  // Default 2 second delay
           if delaySecStr := os.Getenv(EnvVarSyncWaveDelay); delaySecStr != "" {
               // Configurable via ARGOCD_SYNC_WAVE_DELAY
           }
           time.Sleep(time.Duration(delaySec) * time.Second)
       }
   }
   ```
   - Default 2-second delay allows other controllers to react
   - Prevents race conditions between Argo CD assessment and reconciliation
   - File: `/workspace/controller/sync.go:576-589`

3. **Resource Ordering for Application**:
   - Resources applied in ascending wave order
   - Lowest wave numbers first, allowing dependencies
   - File: `/workspace/controller/state.go:799`

4. **Resource Ordering for Deletion** (Reverse Order)
   ```go
   sort.Sort(sort.Reverse(syncWaveSorter(objs)))
   ```
   - Resources pruned in descending wave order
   - Ensures dependencies deleted last
   - Prevents orphaned resources
   - File: `/workspace/controller/sort_delete.go:29`

### Client-Side vs Server-Side Apply

**Client-Side Apply (Default)**:
- **Implementation**: kubectl patch/update locally
- **Conflict Resolution**: Last-write-wins strategy
- **Marker**: `kubectl.kubernetes.io/last-applied-configuration` annotation
- **Strategy**: JSON patch applied locally before sending to server

**Server-Side Apply (SSA)**:

**Enablement** (line 381):
```go
sync.WithServerSideApply(syncOp.SyncOptions.HasOption(common.SyncOptionServerSideApply))
```
- File: `/workspace/controller/sync.go:381`

**Key Differences from Client-Side**:
- **Implementation**: kubectl apply --server-side
- **Conflict Resolution**: Field ownership tracking (no overwrites of unowned fields)
- **Marker**: Server-side field metadata (no annotations)
- **Merge Strategy**: Structured merge patches preserve other controllers' changes
- **Field Manager**: Uses `cdcommon.ArgoCDSSAManager` as identifier

**Related Configuration**:
- **Structured Merge Diff** (line 754-756): Enabled when SSA is used
  ```go
  if app.Spec.SyncPolicy != nil && app.Spec.SyncPolicy.SyncOptions.HasOption("ServerSideApply=true") {
      diffConfigBuilder.WithStructuredMergeDiff(true)
  }
  ```
  - File: `/workspace/controller/state.go:754-756`

- **Namespace Handling** (lines 48-55): SSA annotation enforcement
  - File: `/workspace/controller/sync_namespace.go:48-55`

- **Test Example**: `/workspace/test/e2e/app_sync_options_test.go:23-61`

### Resource Ordering Determination

**Wave Annotation Assignment**:
- `resState.SyncWave = int64(syncwaves.Wave(targetObj))` reads from target object
- Default wave: 0 if annotation absent
- File: `/workspace/controller/state.go:799`

**Ordering Pipeline in CompareAppState**:

1. **Target Objects Compilation** (lines 645-695):
   - Get manifests from repo server
   - Deduplicate resources
   - Filter excluded resources
   - Augment with managed namespace metadata
   - File: `/workspace/controller/state.go:645-695`

2. **Live State Matching** (via `sync.Reconcile()`):
   - Maps target objects to live cluster objects
   - Creates index by (Group, Kind, Namespace, Name)
   - File: `/workspace/controller/state.go:616-620`

3. **Resource Filtering** (line 695):
   ```go
   reconciliation := sync.Reconcile(targetObjs, liveObjByKey,
                                    app.Spec.Destination.Namespace, infoProvider)
   ```
   - gitops-engine orders based on resource type
   - File: `/workspace/controller/state.go:695`

4. **Wave Assignment During Comparison** (line 799):
   - Each target object gets SyncWave from annotation
   - Used by sync execution for ordering
   - File: `/workspace/controller/state.go:799`

5. **Sync Execution Ordering**:
   - gitops-engine processes `ReconciliationResult` with ordered Target and Live arrays
   - Resources applied according to wave ordering
   - File: `/workspace/controller/sync.go:390-416`

### Sync Status Tracking and Propagation

**Phase 1: Comparison Result Structure** (lines 920-951):
```go
compRes := comparisonResult{
    syncStatus:           &syncStatus,         // Overall sync state
    healthStatus:         healthStatus,        // Resource health
    resources:            resourceSummaries,   // Per-resource status
    managedResources:     managedResources,
    reconciliationResult: reconciliation,      // Target/Live resource mapping
    diffConfig:           diffConfig,
    diffResultList:       diffResults,         // Diff results per resource
}
```
- File: `/workspace/controller/state.go:920-951`

**Per-Resource Status Assignment** (lines 771-840):
```go
resState := v1alpha1.ResourceStatus{
    Namespace:       obj.GetNamespace(),
    Name:            obj.GetName(),
    Kind:            gvk.Kind,
    SyncWave:        int64(syncwaves.Wave(targetObj)),
    Status:          v1alpha1.SyncStatusCodeOutOfSync,  // or Synced
    RequiresPruning: targetObj == nil && liveObj != nil,
}
```
- File: `/workspace/controller/state.go:771-840`

**Phase 2: Sync Execution** (lines 390-416):
```go
syncCtx, cleanup, err := sync.NewSyncContext(
    compareResult.syncStatus.Revision,
    reconciliationResult,     // Target and Live resources
    restConfig,
    rawConfig,
    m.kubectl,
    app.Spec.Destination.Namespace,
    openAPISchema,
    opts...,  // ServerSideApply, hooks, etc.
)

if state.Phase == common.OperationTerminating {
    syncCtx.Terminate()
} else {
    syncCtx.Sync()  // Execute via gitops-engine
}

state.Phase, state.Message, resState = syncCtx.GetState()
```
- File: `/workspace/controller/sync.go:390-416`

**Resource Result Extraction** (lines 415-453):
```go
var resState []common.ResourceSyncResult
state.Phase, state.Message, resState = syncCtx.GetState()

for _, res := range resState {
    state.SyncResult.Resources = append(state.SyncResult.Resources,
        &v1alpha1.ResourceResult{
            HookType:  res.HookType,
            Group:     res.ResourceKey.Group,
            Kind:      res.ResourceKey.Kind,
            SyncPhase: res.SyncPhase,
            Status:    res.Status,
            Message:   res.Message,
        })
}
```
- File: `/workspace/controller/sync.go:415-453`

**Phase 3: Status Persistence** (`setOperationState()`, lines 1501-1575):

```go
func (ctrl *ApplicationController) setOperationState(app *appv1.Application,
                                                    state *appv1.OperationState) {
    if state.Phase.Completed() {
        now := metav1.Now()
        state.FinishedAt = &now
    }

    patch := map[string]interface{}{
        "status": map[string]interface{}{
            "operationState": state,
        },
    }

    if state.Phase.Completed() {
        patch["operation"] = nil  // Clear operation to indicate completion
    }

    ctrl.PatchAppWithWriteBack(context.Background(), app.Name, app.Namespace,
                               types.MergePatchType, patchJSON, ...)
}
```
- File: `/workspace/controller/appcontroller.go:1501-1575`

**OperationState Structure**:
```go
type OperationState struct {
    Operation Operation              // Original sync request
    Phase     synccommon.OperationPhase  // Running/Succeeded/Failed
    Message   string                 // Status message
    SyncResult *SyncOperationResult  // Per-resource results
    StartedAt metav1.Time            // When sync started
    FinishedAt *metav1.Time          // When sync completed
    RetryCount int64                 // Number of retries
}
```
- File: `/workspace/pkg/apis/application/v1alpha1/types.go:1369-1384`

**Phase 4: Operation Queuing and Processing** (lines 1365-1440):
```go
func (ctrl *ApplicationController) processRequestedAppOperation(app *appv1.Application) {
    state := &appv1.OperationState{
        Phase: synccommon.OperationRunning,
        Operation: *app.Operation,
        StartedAt: metav1.Now(),
    }
    ctrl.setOperationState(app, state)          // Initial patch

    ctrl.appStateManager.SyncAppState(app, state) // Execute

    ctrl.setOperationState(app, state)          // Final patch with results
}
```
- File: `/workspace/controller/appcontroller.go:1365-1440`

**Phase 5: Revision History Persistence** (lines 457-463):
```go
if !syncOp.DryRun && len(syncOp.Resources) == 0 && state.Phase.Successful() {
    err := m.persistRevisionHistory(app, compareResult.syncStatus.Revision,
                                    source, compareResult.syncStatus.Revisions,
                                    compareResult.syncStatus.ComparedTo.Sources,
                                    isMultiSourceRevision, state.StartedAt,
                                    state.Operation.InitiatedBy)
}
```
- File: `/workspace/controller/sync.go:457-463`

**ResourceResult Structure** (per-resource sync result):
```go
type ResourceResult struct {
    Group         string                    // API group
    Kind          string                    // Resource kind
    Namespace     string                    // Namespace
    Name          string                    // Resource name
    Status        synccommon.ResultCode     // Synced/OutOfSync/Unknown
    Message       string                    // Status message
    HookType      synccommon.HookType       // PreSync/Sync/PostSync/SyncFail/PostDelete
    HookPhase     synccommon.OperationPhase // Succeeded/Failed for hook results
    SyncPhase     synccommon.SyncPhase      // Which phase executed
}
```
- File: `/workspace/pkg/apis/application/v1alpha1/types.go:1600-1622`

**Complete Status Propagation Flow**:
```
Application.Operation (user request)
    ↓
processRequestedAppOperation()
    ├→ Create OperationState with Phase=Running
    ├→ setOperationState() [patches app.status.operationState]
    ├→ SyncAppState()
    │   ├→ CompareAppState() [builds comparison with per-resource sync status]
    │   ├→ sync.NewSyncContext() [initializes gitops-engine context]
    │   ├→ syncCtx.Sync() [executes actual apply with waves]
    │   └→ Extract ResourceSyncResults
    ├→ Map results to ResourceResult array
    ├→ Update state.SyncResult.Resources
    └→ setOperationState() [final patch with complete results]
        └→ Application.Status.OperationState contains:
            - Phase (Succeeded/Failed/Running/Unknown)
            - SyncResult with per-resource ResourceResult[]
            - FinishedAt timestamp
            - Revision/Revisions synced to
            - Retry count if applicable
```

### Sync Options Configuration

**Available Sync Options** (passed during operation):
- `ServerSideApply=true`: Use server-side apply
- `CreateNamespace=true`: Auto-create target namespace
- `PruneLast`: Delete resources after creating new ones
- `Replace`: Replace resources instead of merge
- `ApplyOutOfSyncOnly=true`: Only sync modified resources
- `DisableValidation`: Skip manifest validation
- `FailOnSharedResource=true`: Fail if shared resources detected
- `DeleteRequireConfirm`: Require confirmation for deletion
- `RespectIgnoreDifferences=true`: Apply ignore differences during sync

---

## Data Flow Summary

Complete transformation pipeline from Git fetch to cluster synchronization:

### 1. **Drift Detection and Refresh Triggering**
   - ApplicationController periodic timers or event watchers detect change need
   - `needRefreshAppStatus()` determines refresh necessity
   - Application enqueued in `appRefreshQueue`
   - **Data**: Application CRD with spec, status, refresh annotations

### 2. **Manifest Generation Request**
   - `processAppRefreshQueueItem()` processes queued applications
   - `GetRepoObjs()` constructs `ManifestRequest` with:
     - Repository credentials and revision
     - ApplicationSource (Helm/Kustomize/Plugin config)
     - Cluster version and API resources
     - Tracking method and resource overrides
   - gRPC call to RepoServer: `repoClient.GenerateManifest(ManifestRequest)`
   - **Data**: ManifestRequest protobuf message

### 3. **Repository Fetch and Git Operations**
   - RepoServer checks manifest cache (returns early if hit)
   - For cache miss: `runRepoOperation()` acquires semaphore lock
   - `newClientResolveRevision()` performs `git ls-remote` to resolve revision to commit SHA
   - `checkoutRevision()` performs:
     - `git fetch` to get latest refs
     - `git checkout <commit>` to specific revision
     - Handles submodules if enabled
   - Caches resolution results in revision cache (3 min TTL)
   - **Data**: Git commit SHA, repository files at checkout

### 4. **Config Management Tool Detection and Rendering**
   - `GetAppSourceType()` identifies tool (Helm/Kustomize/CMP/Directory)
   - Explicit type from spec takes precedence
   - Falls back to automatic discovery (CMP first, then Helm/Kustomize/Directory)
   - Routes to appropriate renderer:
     - Helm: `helmTemplate()` - renders chart with values
     - Kustomize: `kustomize.NewKustomizeApp().Build()` - builds overlay
     - CMP: `runConfigManagementPluginSidecars()` - executes plugin
     - Directory: `findManifests()` - discovers YAML/JSON files
   - Applies resource tracking labels
   - Returns `ManifestResponse` with:
     - Array of manifest JSON strings
     - Resolved revision (commit SHA)
     - Source type identifier
     - Commands executed
   - Caches result with 24-hour TTL
   - **Data**: ManifestResponse protobuf with generated manifests

### 5. **Live State Retrieval and Caching**
   - ApplicationController triggers `CompareAppState()`
   - `GetManagedLiveObjs()` queries LiveStateCache
   - LiveStateCache maintains watches on all cluster resources via informers
   - Returns map of cluster resources by ResourceKey: `map[kube.ResourceKey]*unstructured.Unstructured`
   - Cache automatically synced with configurable refresh (default: 12 hours)
   - **Data**: Live cluster resources as unstructured Kubernetes objects

### 6. **Resource Matching and Pairing**
   - `sync.Reconcile()` maps target manifests to live cluster objects
   - Builds index by (Group, Kind, Namespace, Name)
   - Creates parallel arrays of target and live objects
   - Returns `ReconciliationResult` with ordered Target/Live pairs
   - **Data**: Paired array of (target, live) resource tuples

### 7. **Diff Configuration Construction**
   - `DiffConfigBuilder` created with:
     - Application's `spec.ignoreDifferences` rules
     - System resource overrides
     - Ignore aggregated roles flag
     - Normalizer options
   - Selects diff strategy:
     - Default: 3-way merge diff
     - If `ServerSideApply=true`: Structured merge diff
     - If `--server-side-diff` enabled: Server-side dry-run diff
   - Returns `DiffConfig` with pluggable normalizers
   - **Data**: DiffConfig object with rules and strategy selection

### 8. **Normalization and Comparison**
   - `preDiffNormalize()` for each resource pair:
     - Removes tracking labels/annotations added by Argo CD
     - Normalizes managed fields if applicable
   - For each resource, pluggable normalizers applied:
     - IgnoreNormalizer: Removes fields per ignoreDifferences rules
     - KnownTypesNormalizer: Ensures type consistency
   - Uses selected diff strategy:
     - 3-way: Compares live vs desired vs last-applied
     - Structured: Uses field ownership tracking
     - Server-side: Dry-runs apply to detect conflicts
   - Returns `DiffResult` with `Modified` flag per resource
   - **Data**: DiffResult[] array with per-resource comparison results

### 9. **Sync Status Determination**
   - For each resource, determines sync status:
     - **Synced**: DiffResult.Modified=false AND resource exists
     - **OutOfSync**: DiffResult.Modified=true OR resource missing OR requires pruning
     - **Unknown**: Comparison failed
   - Builds `ResourceStatus` with:
     - Sync status (Synced/OutOfSync/Unknown)
     - Health status (Healthy/Progressing/Degraded/Unknown)
     - Wave assignment from annotation
     - Requires pruning/deletion confirm flags
   - Builds overall `SyncStatus`:
     - Status: OutOfSync if ANY resource out-of-sync
     - Revision: Git commit SHA
     - ComparedTo: Source and destination used
   - **Data**: ResourceStatus[] and SyncStatus in comparisonResult

### 10. **Application Status Update (Post-Comparison)**
   - Persists `Application.Status.SyncStatus` with:
     - Overall status (Synced/OutOfSync/Unknown)
     - Per-resource ResourceStatus array
     - Health status
     - Revision/Revisions
   - Updates `Application.Status.Conditions` with comparison result
   - Sets `Application.Status.ReconciledAt` timestamp
   - **Data**: Updated Application CRD status

### 11. **Sync Decision and Queuing**
   - ApplicationController checks `autoSync` policy:
     - If enabled and OutOfSync: Auto-enqueue in `appOperationQueue`
     - If manual sync requested: Manually enqueue in `appOperationQueue`
   - Creates `Operation` object with:
     - Sync type and parameters
     - Sync options (ServerSideApply, CreateNamespace, etc.)
     - Resource selectors (if partial sync)
   - **Data**: Application.Operation with sync details

### 12. **Operation Execution**
   - `processAppOperationQueueItem()` processes sync operations
   - Creates initial `OperationState`:
     - Phase: Running
     - StartedAt timestamp
   - Patches `Application.Status.OperationState` (initial state)
   - Calls `SyncAppState()` with comparison result
   - **Data**: OperationState with Phase=Running

### 13. **Sync Context Initialization**
   - `sync.NewSyncContext()` from gitops-engine:
     - Takes ReconciliationResult (target/live pairs)
     - Cluster connection info and kubectl client
     - OpenAPI schema for validation
     - Sync options (ServerSideApply, CreateNamespace, etc.)
     - Wave and hook information
   - Initializes gitops-engine sync engine
   - **Data**: SyncContext configured with all necessary information

### 14. **Sync Wave and Resource Ordering**
   - Resources extracted from ReconciliationResult
   - Sorted by wave annotation: `syncwaves.Wave(obj)`
   - Default wave: 0 if annotation absent
   - Waves sorted in ascending order for apply (lowest first)
   - Waves sorted in descending order for delete (highest first)
   - **Data**: Ordered resource list per wave

### 15. **PreSync Phase Execution**
   - gitops-engine processes resources with `SyncPhasePreSync` annotation
   - For each wave in PreSync resources:
     - Applies hooks and resources with `sync-wave` value
     - Waits for resource health validation
     - 2-second delay between waves (configurable)
     - Continues to next wave on success
   - Updates phase and message in state
   - If PreSync fails: Stops and returns failure
   - **Data**: ResourceSyncResult[] for PreSync phase

### 16. **Main Sync Phase Execution**
   - gitops-engine processes resources with `SyncPhaseSync` (default)
   - For each wave:
     - Determines apply method (client-side or server-side):
       - Client-side: Uses kubectl patch with 3-way merge
       - Server-side: Uses kubectl apply --server-side
     - Creates/updates resources in cluster
     - Polls health status after apply
     - 2-second delay between waves
   - Updates phase and message in state
   - Collects ResourceSyncResult per resource applied
   - **Data**: ResourceSyncResult[] with per-resource apply results

### 17. **PostSync Phase Execution**
   - Only if Sync phase completed successfully
   - gitops-engine processes resources with `SyncPhasePostSync` annotation
   - Similar wave ordering and health polling as Sync phase
   - Used for validation or cleanup hooks
   - Updates phase and message in state
   - **Data**: ResourceSyncResult[] for PostSync phase

### 18. **Health Assessment and Result Collection**
   - After each wave, health of deployed resources assessed
   - Updates ResourceSyncResult status:
     - Synced: Successfully applied
     - Failed: Apply failed
   - Maps results back to ResourceResult objects:
     - Group, Kind, Namespace, Name
     - Status (Synced/Failed/Unknown)
     - Message with error details
     - HookType and SyncPhase
   - Builds final SyncOperationResult with:
     - ResourceResult[] array
     - Overall phase (Succeeded/Failed)
     - Overall message
   - **Data**: SyncOperationResult with complete result details

### 19. **Operation State Finalization**
   - `syncCtx.GetState()` returns final state
   - Sets OperationState:
     - Phase: Succeeded/Failed/Unknown
     - Message: Overall operation message
     - SyncResult: SyncOperationResult with resources
     - FinishedAt: Current timestamp
   - **Data**: Completed OperationState

### 20. **Status Persistence to Application**
   - `setOperationState()` patches Application status:
     - Updates `status.operationState` with final state
     - Clears `status.operation` to indicate completion
     - Uses merge patch strategy
   - Updates Kubernetes API with operation results
   - **Data**: Patched Application CRD with operation results

### 21. **Revision History and Reconciliation State**
   - If sync succeeded and dry-run=false:
     - `persistRevisionHistory()` records successful deployment
     - Adds entry to Application.Status.History with:
       - Revision synced to
       - Source revision
       - Deployed by (initiating user/system)
       - Timestamp
   - Updates Application.Status.ReconciledAt with current time
   - **Data**: Updated Application.Status with history entry

### 22. **Return to Monitoring Loop**
   - ApplicationController resumes monitoring cycle
   - Watches for next drift detection event
   - Next reconciliation triggered by timer or new event
   - **Data**: Awaiting next event or timer trigger

---

## Evidence

### Core Controller Files

| File Path | Line References | Purpose |
|-----------|-----------------|---------|
| `/workspace/controller/appcontroller.go` | 1598-1640, 1886-1937, 2399-2472 | Main reconciliation loop, drift detection, queue processing |
| `/workspace/controller/appcontroller.go` | 1365-1440 | Operation queuing and sync initiation |
| `/workspace/controller/appcontroller.go` | 1501-1575 | Operation state persistence |
| `/workspace/controller/appcontroller.go` | 419-479 | Drift detection via live state changes |
| `/workspace/controller/appcontroller.go` | 943-960 | Refresh request enqueuing |

### State Management Files

| File Path | Line References | Purpose |
|-----------|-----------------|---------|
| `/workspace/controller/state.go` | 129-321 | ManifestRequest construction |
| `/workspace/controller/state.go` | 269 | gRPC GenerateManifest call |
| `/workspace/controller/state.go` | 611 | GetManagedLiveObjs call |
| `/workspace/controller/state.go` | 645-695 | Target object compilation |
| `/workspace/controller/state.go` | 695-721 | Comparison resource filtering |
| `/workspace/controller/state.go` | 704-761 | DiffConfig construction |
| `/workspace/controller/state.go` | 709-751 | Diff strategy selection (SSD, SMD, 3-way) |
| `/workspace/controller/state.go` | 754-756 | Structured merge diff enablement |
| `/workspace/controller/state.go` | 771-840 | Per-resource sync status determination |
| `/workspace/controller/state.go` | 799 | Wave assignment from annotation |
| `/workspace/controller/state.go` | 823-875 | Out-of-sync condition logic |
| `/workspace/controller/state.go` | 920-951 | Comparison result structure |

### Sync Execution Files

| File Path | Line References | Purpose |
|-----------|-----------------|---------|
| `/workspace/controller/sync.go` | 381 | ServerSideApply enablement |
| `/workspace/controller/sync.go` | 390-416 | Sync context initialization and execution |
| `/workspace/controller/sync.go` | 415-453 | Resource result extraction |
| `/workspace/controller/sync.go` | 457-463 | Revision history persistence |
| `/workspace/controller/sync.go` | 576-589 | Sync wave delay mechanism |

### RepoServer Files

| File Path | Line References | Purpose |
|-----------|-----------------|---------|
| `/workspace/reposerver/repository/repository.go` | 289-454 | runRepoOperation with git checkout |
| `/workspace/reposerver/repository/repository.go` | 309 | Git cache with withCache option |
| `/workspace/reposerver/repository/repository.go` | 383 | Repository lock mechanism |
| `/workspace/reposerver/repository/repository.go` | 518-586 | GenerateManifest entry point |
| `/workspace/reposerver/repository/repository.go` | 704-812 | runManifestGenAsync with caching |
| `/workspace/reposerver/repository/repository.go` | 896-950 | Error cache pause mechanism |
| `/workspace/reposerver/repository/repository.go` | 1421-1522 | GenerateManifests core logic with tool detection |
| `/workspace/reposerver/repository/repository.go` | 2408-2415 | Git client creation |
| `/workspace/reposerver/repository/repository.go` | 2419-2430 | Revision resolution |
| `/workspace/reposerver/repository/repository.go` | 2495+ | checkoutRevision implementation |

### Cache and Diff Files

| File Path | Line References | Purpose |
|-----------|-----------------|---------|
| `/workspace/reposerver/cache/cache.go` | 293-304 | Cache key construction |
| `/workspace/reposerver/cache/cache.go` | 347-359 | Cache hash validation |
| `/workspace/controller/cache/cache.go` | All | LiveStateCache interface and implementation |
| `/workspace/util/argo/diff/diff.go` | 412-446 | Pre-diff normalization |
| `/workspace/util/argo/diff/normalize.go` | All | Normalizer composition and application |

### Proto Definitions

| File Path | Line References | Purpose |
|-----------|-----------------|---------|
| `/workspace/reposerver/repository/repository.proto` | 10-45 | ManifestRequest message definition |
| `/workspace/reposerver/repository/repository.proto` | 92-103 | ManifestResponse message definition |

### API Type Definitions

| File Path | Line References | Purpose |
|-----------|-----------------|---------|
| `/workspace/pkg/apis/application/v1alpha1/types.go` | SyncStatus definition | Application sync status structure |
| `/workspace/pkg/apis/application/v1alpha1/types.go` | ResourceStatus definition | Per-resource sync status |
| `/workspace/pkg/apis/application/v1alpha1/types.go` | OperationState definition (1369-1384) | Sync operation state tracking |
| `/workspace/pkg/apis/application/v1alpha1/types.go` | ResourceResult definition (1600-1622) | Per-resource sync result |

### Ordering and Deletion

| File Path | Line References | Purpose |
|-----------|-----------------|---------|
| `/workspace/controller/sort_delete.go` | 29 | Reverse wave ordering for deletion |

### Related Utilities

| File Path | Purpose |
|-----------|---------|
| `/workspace/util/app/discovery/discovery.go:36-82` | Config management tool detection |
| `/workspace/controller/sync_namespace.go:48-55` | Namespace SSA handling |
| `/workspace/controller/hydrator/hydrator.go` | Manifest hydration |
| `/workspace/test/e2e/hook_test.go` | Sync phase demonstrations |
| `/workspace/test/e2e/app_sync_options_test.go:23-61` | ServerSideApply testing |

---

## Integration Points

### Primary Data Flow Paths

1. **Event → Reconciliation**:
   - Application watch → `newApplicationInformerAndLister()` → `addApplicationEventHandler()` → `requestAppRefresh()`

2. **Reconciliation → Manifest Generation**:
   - `processAppRefreshQueueItem()` → `CompareAppState()` → `GetRepoObjs()` → `repoClient.GenerateManifest()`

3. **Live State Retrieval**:
   - `CompareAppState()` → `liveStateCache.GetManagedLiveObjs()` → cluster informer watches

4. **Comparison → Status**:
   - `CompareAppState()` → diff engine → `ResourceStatus[]` → `SyncStatus` → Application.Status patch

5. **Sync Decision → Execution**:
   - Auto-sync check → `processRequestedAppOperation()` → `SyncAppState()` → gitops-engine → cluster update

### External Dependencies

- **gitops-engine** (`github.com/argoproj-labs/gitops-engine`): Provides diff algorithm, sync context, reconciliation logic
- **Kubernetes client** (`kubernetes/client-go`): Direct cluster communication
- **kubectl wrapper** (`pkg/kubectl`): Manifest application and validation
