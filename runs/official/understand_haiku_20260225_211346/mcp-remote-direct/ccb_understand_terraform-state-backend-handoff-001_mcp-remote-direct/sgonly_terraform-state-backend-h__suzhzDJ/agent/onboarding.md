# Terraform State Backend Subsystem - Team Handoff Document

## Overview

This document provides a comprehensive guide to the Terraform state backend subsystem, responsible for managing how Terraform stores, retrieves, and locks state files across different storage backends and operational modes. This system enables both local development and large-scale remote state management across teams.

---

## 1. Purpose

### Problem Statement

Terraform's state file is critical—it maps the declared infrastructure in code to real-world resources. A robust backend system solves several key problems:

1. **Shared State Management**: Multiple team members need safe concurrent access to the same state
2. **State Persistence**: State must survive process restarts and failures
3. **Storage Flexibility**: Different organizations need different storage solutions (local files, S3, Terraform Cloud, etc.)
4. **State Integrity**: Concurrent writes must be atomic and prevent corruption
5. **Workspace Isolation**: Teams need multiple independent state files (workspaces) within a single backend

### Why Multiple Backend Types

Different environments have different requirements:

- **Local Backend** (`local`): Development, single-user, filesystem-based
- **S3 Backend** (`s3`): Team collaboration, AWS-native, with optional DynamoDB locking
- **Cloud/Remote Backend** (`cloud`/`remote`): Enterprise, full remote operations, HCP Terraform integration
- **Other Backends** (`azurerm`, `gcs`, `consul`, `pg`, `kubernetes`, etc.): Cloud-provider-specific and specialized solutions

### Key Responsibilities of a Backend

1. **State Manager Provisioning**: Provide a `statemgr.Full` implementation for state storage
2. **Configuration Management**: Define and validate backend configuration via schema
3. **Workspace Support**: Handle multiple named workspaces
4. **Optional Operation Execution**: Some backends (local, remote, cloud) can execute Terraform operations directly
5. **State Locking** (optional): Prevent concurrent modifications via mutual exclusion
6. **Metadata Preservation**: Track state serial/lineage for consistency verification

---

## 2. Dependencies

### Upstream Dependencies (What Calls Into Backends)

```
Command Layer
    ↓
meta_backend.go (Backend initialization)
    ↓
Backend Interface (Configuration & State Management)
```

**Key Entry Points:**
- `internal/command/meta_backend.go:Backend()` - CLI initializes backends and performs operations
- `internal/command/init.go` - Backend initialization and reconfiguration
- `internal/command/output.go` - Reads outputs from state via backend
- Various operation commands (`plan.go`, `apply.go`, etc.)

### Internal Dependencies (What Backends Use)

1. **State Manager Interfaces** (`internal/states/statemgr/`):
   - `statemgr.Full`: Union of Transient, Persistent, and Locker interfaces
   - `statemgr.Locker`: State locking via Lock/Unlock
   - `statemgr.Persistent`: RefreshState/PersistState for durable storage
   - `statemgr.Transient`: Reader/Writer for in-memory state

2. **State Objects** (`internal/states/`):
   - `states.State`: The actual state data structure
   - `statefile.File`: Serialized state with metadata (serial, lineage, version)

3. **Configuration System**:
   - `internal/configs/configschema`: Schema definition for backend configuration
   - `cty.Value`: Configuration values after parsing
   - `tfdiags.Diagnostics`: Error and warning reporting

4. **Local Backend** (`internal/backend/local/`):
   - Wraps remote/simple backends and adds operation execution
   - Manages state locking, refreshing, and persistence
   - Integrates with `terraform.Context` for plan/apply operations

5. **Backend Initialization** (`internal/backend/init/`):
   - Global registry of all available backends
   - Backend lookup and instantiation

### Downstream Dependencies (What Backends Call)

1. **Storage Providers**:
   - S3: AWS SDK v2 (`aws-sdk-go-v2`)
   - GCS: Google Cloud Client Library
   - Azure: Azure SDK for Go
   - PostgreSQL: `pq` driver
   - Consul: Consul HTTP API
   - Kubernetes: Kubernetes client library

2. **Operation Execution** (for OperationsBackend implementations):
   - `terraform.Context` and graph builders for plan/apply
   - Provider system for resource operations
   - Module loader for configuration loading

### Integration with Broader Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI Commands                          │
│                   (plan, apply, init, etc)                  │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ↓
      ┌──────────────────────────────┐
      │  Backend Interface            │
      │  (ConfigSchema, Configure,    │
      │   StateMgr, Workspaces)       │
      └────────┬─────────────────────┘
               │
        ┌──────┴────────┬──────────────────┐
        ↓               ↓                  ↓
    Local Backend   Remote Backend    Other Backends
    (executes ops) (remote ops)       (state only)
        │               │                  │
        └───────┬───────┴──────┬───────────┘
                ↓              ↓
          State Manager  Configuration
          (statemgr)     Schema
                │              │
          ┌─────┴──────────────┴──────┐
          ↓                           ↓
    Storage Providers       State Objects
    (S3, GCS, etc)         & Serialization
```

---

## 3. Relevant Components

### Main Backend Interface

**File**: `internal/backend/backend.go`

**Core Interface**:
```go
type Backend interface {
    // Schema and configuration
    ConfigSchema() *configschema.Block
    PrepareConfig(cty.Value) (cty.Value, tfdiags.Diagnostics)
    Configure(cty.Value) tfdiags.Diagnostics

    // State management
    StateMgr(workspace string) (statemgr.Full, error)
    DeleteWorkspace(name string, force bool) error
    Workspaces() ([]string, error)
}
```

**Key Constants**:
- `DefaultStateName = "default"` - Every backend must have this workspace
- `ErrWorkspacesNotSupported` - Returned by single-workspace backends
- `ErrDefaultWorkspaceNotSupported` - Some backends don't support default

### State Manager Interfaces

**File**: `internal/states/statemgr/`

**Core Hierarchy**:
```
Full (union of all below)
  ├── Storage
  │   ├── Transient (Reader + Writer)
  │   └── Persistent (Refresher + Persister + OutputReader)
  └── Locker (Lock + Unlock for mutual exclusion)
```

**Transient Interface** (`transient.go`):
- `State() *states.State` - Get current state snapshot
- `WriteState(*states.State) error` - Update in-memory state

**Persistent Interface** (`persistent.go`):
- `RefreshState() error` - Load state from durable storage
- `PersistState(*schemarepo.Schemas) error` - Save state to durable storage
- `GetRootOutputValues(ctx) (map[string]*states.OutputValue, error)` - Output-only reads

**Locker Interface** (`locker.go`):
- `Lock(info *LockInfo) (string, error)` - Acquire mutual exclusion lock
- `Unlock(id string) error` - Release lock
- `LockWithContext(ctx, Locker, LockInfo) (string, error)` - Helper with retry logic

**Optional Interfaces**:
- `Migrator` - Preserves serial/lineage during state migrations
- `PersistentMeta` - Query snapshot metadata (serial, lineage, version)
- `IntermediateStateConditionalPersister` - Control intermediate state snapshot rules

### Backend Initialization System

**File**: `internal/backend/init/init.go`

**Global Registry**:
```go
var backends map[string]backend.InitFn  // Global backend registry

// Available backends (as of v1.9.0):
// "local" -> local.New()
// "s3" -> s3.New()
// "azurerm" -> azure.New()
// "gcs" -> gcs.New()
// "consul" -> consul.New()
// "http" -> http.New()
// "inmem" -> inmem.New()  // Testing only
// "kubernetes" -> kubernetes.New()
// "oss" -> oss.New()
// "pg" -> pg.New()
// "remote" -> remote.New()
// "cloud" -> cloud.New()  // HCP Terraform
```

**Functions**:
- `Init(disco *Disco)` - Initialize the registry (called at startup)
- `Backend(name string) backend.InitFn` - Lookup a backend factory
- `Set(name string, f backend.InitFn)` - Register a custom backend

### Local Backend

**Files**: `internal/backend/local/`
- `backend.go` - Core Local type and state management
- `backend_local.go` - Enhanced operations (plan, apply, refresh)
- `backend_plan.go` - Plan execution
- `backend_apply.go` - Apply execution
- `backend_refresh.go` - Refresh execution
- `cli.go` - CLI integration and prompts
- `hook_state.go` - State update hooks for intermediate snapshots

**Key Type**:
```go
type Local struct {
    StatePath string                    // Path to state file
    StateOutPath string                 // Output path (defaults to StatePath)
    StateBackupPath string              // Backup location
    StateWorkspaceDir string            // Directory for named workspaces

    Backend backend.Backend             // Wrapped remote backend (if any)
    ContextOpts *terraform.ContextOpts  // Context configuration
    states map[string]statemgr.Full    // Cached state managers
}
```

**Implements**:
- `backend.Backend` (basic state management)
- `backendrun.OperationsBackend` (can execute plan/apply/refresh)
- `backendrun.Local` (local execution interface)

### Remote State Backends

**Files**: `internal/backend/remote-state/`

Each backend has a similar structure:
- `backend.go` - Backend implementation
- `client.go` - Storage client (S3, GCS, etc.)
- `backend_test.go` - Acceptance tests

**Main Implementations**:

1. **S3** (`s3/`): Most complex, provides full locking via DynamoDB
2. **GCS** (`gcs/`): Google Cloud Storage
3. **Azure** (`azure/`): Azure Blob Storage
4. **Consul** (`consul/`): Distributed key-value store
5. **PostgreSQL** (`pg/`): SQL-based state storage
6. **Kubernetes** (`kubernetes/`): K8s native state storage
7. **HTTP** (`http/`): Generic HTTP backend
8. **OSS** (`oss/`): Alibaba Object Storage Service
9. **COS** (`cos/`): Tencent Cloud Object Storage

### Cloud/Remote Backend

**Files**: `internal/cloud/`
- `backend.go` - Full HCP Terraform integration
- `state.go` - State manager with Terraform Cloud API
- `testing.go` - Test utilities

**Special Features**:
- Executes operations on HCP Terraform's servers
- Handles workspace-to-run mapping
- Version conflict detection
- Cost estimation and policy enforcement

### Backend Configuration Loading

**File**: `internal/command/meta_backend.go`

**Key Functions**:
- `Backend(opts *BackendOpts) (backendrun.OperationsBackend, tfdiags.Diagnostics)` - Load and initialize
- `BackendConfig()` - Get current backend configuration
- `backendMigrateState()` - Migrate state between backends
- `backendConfigNeedsMigration()` - Detect backend changes

---

## 4. Failure Modes

### Configuration Errors

**Detection**: `PrepareConfig()` and `Configure()` methods

Common issues:
- Missing required config values (bucket name, table name, etc.)
- Invalid credential formats
- Invalid region specifications
- Deprecated backend configurations

**Handling**: Returned as `tfdiags.Diagnostics` with contextual information

**Example S3 Validation** (`s3/backend.go:PrepareConfig()`):
```go
// Checks bucket existence, DynamoDB table, KMS key access, account IDs
// Returns clear diagnostics for missing/misconfigured resources
```

### State Locking Failures

**Lock Contention**: When state is already locked

**Mechanism** (`locker.go:LockWithContext()`):
```go
// Retry logic with exponential backoff
// Max delay: 16 seconds
// Returns LockError with existing lock info
// Allows force-unlock via CLI
```

**Timeout Handling**:
- Context cancellation stops retry attempts
- Returns last LockError to user
- User can use `terraform force-unlock <ID>` to break stale locks

**Common Issues**:
- Process crash with held lock (state remains locked)
- Stale locks from failed CI/CD runs
- Network partitions preventing lock release

### Storage Unavailability

**S3 Examples**:
- Bucket doesn't exist → RefreshState/PersistState returns error
- No AWS credentials → Configure fails with auth error
- Network timeout → Persistence operations timeout
- S3 access denied → RefreshState/PersistState fails with 403

**Handling**:
- Operations fail with clear error messages
- Terraform aborts before state corruption
- User must resolve underlying issue (credentials, network, permissions)

### State Consistency Issues

**Serial/Lineage Mismatch** (`.stateSnapshotMeta()`):
- Serial is incremented with each successful persist
- Lineage tracks state file generations
- Mismatches indicate concurrent modifications or rollback attempts

**Detection**: In S3 backend's `PersistState()` via DynamoDB conditionally checked against expected serial/lineage

**Corruption Scenarios**:
1. Direct state file modification (bypassing backends)
2. Multiple concurrent Terraform runs without locking
3. Forced state overwrites without lineage/serial preservation

**Prevention**:
- Always use backends with locking support for team environments
- `terraform push`/`pull` preserve metadata via `Migrator` interface
- Versioning in remote storage (S3 versioning, Git, etc.)

### Configuration Change Detection

**File**: `meta_backend.go:BackendConfig()` and `backendConfigNeedsMigration()`

When backend type or config changes, Terraform detects and prompts user to:
1. Review differences
2. Choose to migrate state between backends
3. Confirm force migration if serial/lineage checks fail

### Workspace-Specific Failures

- `DeleteWorkspace("default", ...)` always fails - default is mandatory
- Creating workspaces on single-workspace backends returns `ErrWorkspacesNotSupported`
- Workspace directory corruption prevents new workspace creation

---

## 5. Testing

### Test Patterns

**File**: `internal/backend/testing.go`

Core test helpers:

1. **`TestBackendConfig(t, backend, hclBody)`**
   - Validates schema, prepares config, configures backend
   - Common starting point for all backend tests
   - Handles diagnostics and fails on errors

2. **`TestBackendStates(t, backend)`**
   - Creates multiple workspaces (foo, bar, default)
   - Writes distinct states to each
   - Verifies isolation and persistence
   - Tests workspace creation/deletion/listing
   - Ensures default workspace cannot be deleted

3. **`TestBackendStateLocks(t, b1, b2)`**
   - Creates two backend instances
   - Tests mutual exclusion (b1 locks, b2 cannot lock)
   - Verifies lock metadata (Who, Operation, Created)
   - Tests lock persistence and timeout

4. **`TestBackendStateForceUnlock(t, b1, b2)`**
   - Tests `-force-unlock` capability
   - Requires lock ID extraction from error

### Test Structure for New Backends

**File Pattern**: `internal/backend/remote-state/<BACKEND>/<backend>_test.go`

**Example: S3 Backend** (`s3/backend_test.go`):
```go
// Setup
func TestBackend(t *testing.T) {
    t.Parallel()
    testACC(t)  // Skip if not in acceptance test mode

    // Get AWS credentials and S3 bucket
    region := os.Getenv("AWS_DEFAULT_REGION")
    bucketName := "terraform-backends-tests-" + randomSuffix

    // Create two backend instances
    b1 := backend.TestBackendConfig(t, New(), backend.TestWrapConfig(map[string]interface{}{
        "bucket": bucketName,
        "key": "state",
        "region": region,
        "dynamodb_table": tableName,  // For locking
    }))

    b2 := backend.TestBackendConfig(t, New(), backend.TestWrapConfig(map[string]interface{}{...}))

    // Run standard tests
    backend.TestBackendStates(t, b1)
    backend.TestBackendStateLocks(t, b1, b2)
}
```

### Acceptance Test Setup

Backends that interact with external systems require acceptance tests:
- S3: Real AWS credentials
- GCS: Real GCP credentials
- Azure: Real Azure credentials
- Consul: Running Consul server
- PostgreSQL: Running Postgres server

**Gating**: Tests skip if `TF_ACC` environment variable not set

### State Manager Testing

**File**: `statemgr_fake.go` provides fake implementations:
- `fakeErrorFull` - Fails all operations
- Used for testing error handling in higher-level code

---

## 6. Debugging

### Logging

**Environment Variables**:
- `TF_LOG=DEBUG` - Enable debug logging
- `TF_LOG_PATH=/path/to/log` - Write to file
- `TF_LOG=TRACE` - Most verbose logging

**Log Output Locations**:
- Local backend: `internal/backend/local/` operations logged
- S3 backend: AWS SDK v2 logging, endpoint calls
- Locking: `statemgr.Locker` Lock/Unlock calls logged

**Key Log Messages**:
```
// Backend selection
"...Backend configuration changed!..."

// Lock operations
"TestBackend: testing state locking for %T"

// State refresh/persist
"refreshing state..."
"persisting state..."
```

### Verification Tools

**1. State Inspection** (`terraform state list/show`):
```bash
terraform state list                     # List all resources
terraform state show resource.id         # Show specific resource
terraform state pull > state.json        # Export state locally
```

**2. Lock Status Checking**:
```bash
terraform state show -raw output       # See lock metadata in outputs
# Or inspect storage directly (S3, DynamoDB, Consul, etc.)
```

**3. Remote State Diagnosis**:
```bash
# For S3 backend
aws s3api head-object --bucket BUCKET --key KEY  # Check state file
aws dynamodb scan --table-name TABLE              # Check locks

# For Consul
consul kv get terraform/state/default

# For PostgreSQL
SELECT * FROM states WHERE name = 'default';
```

**4. Configuration Inspection**:
```bash
terraform init -backend=false           # Skip backend init
terraform backends                      # List configured backends
cat .terraform/terraform.tfstate         # Backend state metadata
```

### Common Issues and Resolution

**Issue: State is locked by another process**

Diagnosis:
1. Check lock metadata: Extract lock ID from error message
2. Verify process is not actually running: `ps aux | grep terraform`
3. Check storage lock entry (DynamoDB, Consul, file system)

Resolution:
```bash
terraform force-unlock <LOCK_ID>
# or manually delete lock from storage if urgent
```

**Issue: State file corruption or serial mismatch**

Diagnosis:
```bash
terraform state pull | jq '.version, .serial, .lineage'
# Compare with remote storage
```

Resolution:
```bash
# Manual state push (preserves serial/lineage via Migrator)
terraform state push -force backup.tfstate

# Or export/import via pull/push
terraform state pull > backup.json
# ... make manual fixes ...
terraform state push backup.json
```

**Issue: Backend configuration conflicts**

Diagnosis:
```bash
# When backend config changes
terraform init  # Shows migration prompts
```

Resolution:
```bash
terraform init -migrate-state   # Automatic migration
# or
terraform init -reconfigure     # Abandon old backend
```

**Issue: S3 bucket access denied**

Diagnosis:
```bash
aws s3api head-object --bucket BUCKET --key KEY
# or
aws s3api get-bucket-versioning --bucket BUCKET
```

Resolution:
```bash
# Verify IAM policy includes:
# s3:GetObject, s3:PutObject, s3:DeleteObject
# s3:GetBucketVersioning (if using versioning)
# dynamodb:DescribeTable, dynamodb:PutItem, etc. (if using DynamoDB locks)
```

**Issue: Stale lock not releasing**

Diagnosis:
```bash
# For S3 + DynamoDB locking
aws dynamodb get-item --table-name LOCKS --key '{"LockID":{"S":"path/to/state"}}'

# Extract lock info
terraform state show terraform_remote_state  # Won't work if locked
```

Resolution:
```bash
# Delete stale lock
terraform force-unlock <LOCK_ID>

# Or directly from DynamoDB
aws dynamodb delete-item --table-name LOCKS \
  --key '{"LockID":{"S":"path/to/state"}}'
```

---

## 7. Adding a New Backend

### Overview

Adding a new backend requires implementing the `backend.Backend` interface and registering it in the initialization system. For remote-only backends (no operations), this is straightforward. For operation-executing backends, implementation is more complex.

### Step-by-Step Process

#### 1. Create Backend Package Structure

```
internal/backend/remote-state/<BACKEND>/
  ├── backend.go           # Core Backend type and methods
  ├── client.go            # Storage client implementation
  ├── backend_test.go      # Acceptance tests
  └── testdata/            # Test fixtures if needed
```

#### 2. Implement Backend Type

**File**: `backend.go`

```go
package mybackend

import (
    "github.com/hashicorp/terraform/internal/backend"
    "github.com/hashicorp/terraform/internal/configs/configschema"
    "github.com/zclconf/go-cty/cty"
    "github.com/hashicorp/terraform/internal/states/statemgr"
    "github.com/hashicorp/terraform/internal/tfdiags"
)

type Backend struct {
    // Storage configuration
    clientConfig *ClientConfig
    client       *Client

    // State managers cache
    states map[string]statemgr.Full
}

// ConfigSchema returns the schema for backend configuration
func (b *Backend) ConfigSchema() *configschema.Block {
    return &configschema.Block{
        Attributes: map[string]*configschema.Attribute{
            "bucket": {
                Type:        cty.String,
                Required:    true,
                Description: "The storage bucket",
            },
            "region": {
                Type:        cty.String,
                Optional:    true,
                Description: "Storage region",
            },
            // ... more config options
        },
    }
}

// PrepareConfig validates and prepares configuration
func (b *Backend) PrepareConfig(obj cty.Value) (cty.Value, tfdiags.Diagnostics) {
    var diags tfdiags.Diagnostics

    // Validate required fields are present
    if obj.IsNull() {
        diags = diags.Append(tfdiags.SimpleError("Backend configuration is required"))
        return obj, diags
    }

    // Insert defaults if needed
    // Return prepared config

    return obj, diags
}

// Configure initializes the backend with configuration
func (b *Backend) Configure(obj cty.Value) tfdiags.Diagnostics {
    var diags tfdiags.Diagnostics

    // Extract configuration values
    config := &ClientConfig{}

    val := obj.GetAttr("bucket")
    if !val.IsNull() {
        config.Bucket = val.AsString()
    }

    // Validate external resources (bucket exists, credentials valid, etc.)
    client, err := NewClient(config)
    if err != nil {
        diags = diags.Append(tfdiags.SimpleError(fmt.Sprintf(
            "Failed to configure backend: %s", err)))
        return diags
    }

    b.client = client
    b.states = make(map[string]statemgr.Full)

    return diags
}

// StateMgr returns a state manager for the given workspace
func (b *Backend) StateMgr(workspace string) (statemgr.Full, error) {
    // Return cached state manager if exists
    if s, ok := b.states[workspace]; ok {
        return s, nil
    }

    // Create new state manager
    s := &State{
        client:    b.client,
        workspace: workspace,
    }

    b.states[workspace] = s
    return s, nil
}

// Workspaces returns all available workspaces
func (b *Backend) Workspaces() ([]string, error) {
    // List all states in storage
    return b.client.ListStates()
}

// DeleteWorkspace deletes a workspace
func (b *Backend) DeleteWorkspace(name string, force bool) error {
    if name == backend.DefaultStateName {
        return fmt.Errorf("cannot delete default workspace")
    }

    delete(b.states, name)
    return b.client.DeleteState(name)
}

// New is the factory function
func New() backend.Backend {
    return &Backend{}
}
```

#### 3. Implement State Manager

**File**: `client.go` or `state.go`

```go
type State struct {
    client    *Client
    workspace string

    // In-memory state
    state *states.State

    // Metadata for locking (optional)
    lockID string
}

// Transient interface - Reader/Writer
func (s *State) State() *states.State {
    return s.state
}

func (s *State) WriteState(st *states.State) error {
    s.state = st
    return nil
}

// Persistent interface - Refresher/Persister
func (s *State) RefreshState() error {
    data, err := s.client.GetState(s.workspace)
    if err != nil {
        return err
    }

    // Deserialize JSON to states.State
    s.state = parseState(data)
    return nil
}

func (s *State) PersistState(schemas *schemarepo.Schemas) error {
    // Serialize state to JSON
    data := serializeState(s.state)

    // Write to storage with atomicity check
    return s.client.PutState(s.workspace, data, expectedSerial)
}

func (s *State) GetRootOutputValues(ctx context.Context) (map[string]*states.OutputValue, error) {
    if s.state == nil {
        return nil, nil
    }
    return s.state.RootModule().OutputValues, nil
}

// Optional Locker interface for state locking
func (s *State) Lock(info *statemgr.LockInfo) (string, error) {
    lockErr := s.client.AcquireLock(s.workspace, info)
    if lockErr != nil {
        return "", &statemgr.LockError{
            Info: info,
            Err:  lockErr,
        }
    }

    s.lockID = info.ID
    return info.ID, nil
}

func (s *State) Unlock(id string) error {
    return s.client.ReleaseLock(s.workspace, id)
}

// Verify implementation
var _ statemgr.Full = (*State)(nil)
```

#### 4. Implement Storage Client

**File**: `client.go`

```go
type Client struct {
    config *ClientConfig
    // SDK clients (AWS SDK, Google Cloud SDK, etc.)
}

type ClientConfig struct {
    Bucket string
    Region string
    // ... other config
}

func NewClient(config *ClientConfig) (*Client, error) {
    // Initialize SDK clients
    // Validate access (test credentials, list buckets, etc.)
    return &Client{config: config}, nil
}

func (c *Client) GetState(workspace string) ([]byte, error) {
    // Fetch state file from storage
    // Handle not-found gracefully
}

func (c *Client) PutState(workspace string, data []byte, serial uint64) error {
    // Write state with serial/lineage consistency check
    // Use atomicity features of storage backend
}

func (c *Client) DeleteState(workspace string) error {
    // Delete state file for workspace
}

func (c *Client) ListStates() ([]string, error) {
    // List all state files, return workspace names
}

func (c *Client) AcquireLock(workspace string, info *statemgr.LockInfo) error {
    // Implement mutual exclusion
    // Return error if already locked
}

func (c *Client) ReleaseLock(workspace string, id string) error {
    // Release lock
}
```

#### 5. Write Acceptance Tests

**File**: `backend_test.go`

```go
package mybackend

import (
    "os"
    "testing"

    "github.com/hashicorp/terraform/internal/backend"
)

func testACC(t *testing.T) {
    if os.Getenv("TF_ACC") == "" {
        t.Skip("skipping acceptance test")
    }
}

func TestBackend_impl(t *testing.T) {
    var _ backend.Backend = new(Backend)
}

func TestBackend(t *testing.T) {
    testACC(t)

    // Setup storage
    bucket := "tf-test-" + randomString()

    // Create backend
    b := backend.TestBackendConfig(t, New(), backend.TestWrapConfig(map[string]interface{}{
        "bucket": bucket,
    }))

    // Run standard tests
    backend.TestBackendStates(t, b)
}

func TestBackendStateLocks(t *testing.T) {
    testACC(t)

    bucket := "tf-test-" + randomString()

    b1 := backend.TestBackendConfig(t, New(), backend.TestWrapConfig(map[string]interface{}{
        "bucket": bucket,
    }))

    b2 := backend.TestBackendConfig(t, New(), backend.TestWrapConfig(map[string]interface{}{
        "bucket": bucket,
    }))

    backend.TestBackendStateLocks(t, b1, b2)
}
```

#### 6. Register Backend in Init System

**File**: `internal/backend/init/init.go`

```go
// Add import
import backendMyBackend "github.com/hashicorp/terraform/internal/backend/remote-state/mybackend"

// Add to backends map in Init()
func Init(services *disco.Disco) {
    backendsLock.Lock()
    defer backendsLock.Unlock()

    backends = map[string]backend.InitFn{
        // ... existing backends ...
        "mybackend": func() backend.Backend { return backendMyBackend.New() },
    }

    // ... rest of initialization ...
}
```

#### 7. (Optional) Implement Migration Support

If you want to preserve state serial/lineage during migrations:

```go
// Implement optional Migrator interface
func (s *State) StateForMigration() *statefile.File {
    return &statefile.File{
        State: s.state,
        Meta: statefile.Meta{
            Version:   statefile.Version,
            Lineage:   s.lineage,
            Serial:    s.serial,
            TfVersion: version.Version,
        },
    }
}

func (s *State) WriteStateForMigration(f *statefile.File, force bool) error {
    s.state = f.State
    s.lineage = f.Meta.Lineage
    s.serial = f.Meta.Serial

    // Validate if not forced
    if !force {
        // Check existing serial/lineage matches...
    }

    return s.PersistState(nil)
}
```

#### 8. (Optional) Implement Operation Support

For backends that execute operations (like local or remote backends):

```go
// Implement backendrun.OperationsBackend
func (b *Backend) Operation(ctx context.Context, op *backendrun.Operation) (*backendrun.RunningOperation, error) {
    // This is a local backend capability
    // Construct terraform.Context
    // Execute plan/apply/refresh
    // Return RunningOperation for tracking
}

func (b *Backend) ServiceDiscoveryAliases() ([]backendrun.HostAlias, error) {
    return nil, nil
}
```

### Key Implementation Considerations

1. **Concurrency**: State managers are used concurrently; use `states.SyncState` wrapper if needed

2. **Workspace Isolation**: Each workspace should be completely isolated in storage

3. **Default Workspace**: Must always exist; `DeleteWorkspace("default", ...)` must fail

4. **Metadata Preservation**: If possible, implement `Migrator` to preserve serial/lineage

5. **Error Handling**: Return contextual diagnostics; include helpful error messages

6. **Locking**: If supporting multiple concurrent clients, implement `Locker`

7. **Testing**: Run acceptance tests against real storage (not mocks)

8. **Documentation**: Add to website docs explaining configuration

### Common Patterns

**Configuration with Credentials**:
```go
// Support environment variables for credentials
access_key := os.Getenv("MY_BACKEND_ACCESS_KEY")
if access_key == "" {
    // Check configuration
}
```

**Graceful State Not Found**:
```go
func (c *Client) GetState(ws string) ([]byte, error) {
    data, err := c.storage.GetObject(ws)
    if err != nil && isNotFound(err) {
        return []byte(""), nil  // Empty state is valid
    }
    return data, err
}
```

**State Serialization**:
```go
// All backends use same serialization
import "github.com/hashicorp/terraform/internal/states/statefile"

func serializeState(st *states.State) []byte {
    f := &statefile.File{
        State: st,
        // Metadata set by Migrator interface
    }
    return f.Bytes()
}
```

---

## Key Files Reference

| File | Purpose |
|------|---------|
| `internal/backend/backend.go` | Backend interface definition |
| `internal/backend/init/init.go` | Backend registry and initialization |
| `internal/backend/local/` | Local execution backend |
| `internal/backend/remote/` | HCP Terraform remote backend |
| `internal/backend/remote-state/` | All remote state backends |
| `internal/states/statemgr/` | State manager interfaces |
| `internal/states/statemgr/locker.go` | State locking interface |
| `internal/states/statemgr/persistent.go` | Persistence interfaces |
| `internal/states/statemgr/migrate.go` | State migration utilities |
| `internal/command/meta_backend.go` | CLI backend integration |
| `internal/backend/testing.go` | Test helpers |
| `docs/architecture.md` | Architecture overview |

---

## Troubleshooting Reference

### Test Failures

```bash
# Run specific backend tests
go test -run TestBackend -v ./internal/backend/remote-state/s3/

# Run acceptance tests
TF_ACC=1 go test ./internal/backend/remote-state/s3/

# Debug test
go test -run TestBackend -v -timeout 30m ./internal/backend/remote-state/s3/
```

### State Locking Issues

```bash
# Check lock status in DynamoDB (S3 backend)
aws dynamodb scan --table-name terraform-locks

# Force unlock
terraform force-unlock <LOCK_ID>

# Check for stale locks
terraform state show -raw | jq '.lock'
```

### Backend Initialization Errors

```bash
# Test backend configuration
terraform init -backend-config="key=value"

# Reconfigure without migration
terraform init -reconfigure

# Debug backend loading
TF_LOG=DEBUG terraform init
```

---

## Summary

The Terraform backend subsystem is a well-designed abstraction that supports diverse state storage solutions while maintaining consistency and safety. Key design principles:

1. **Pluggable Architecture**: New backends can be added without modifying core logic
2. **Safety First**: Locking and metadata preservation prevent corruption
3. **Flexibility**: Support for single-user local development to large team remote operations
4. **Testability**: Standard test suite ensures consistency across backends
5. **Clear Contracts**: Interfaces define expectations explicitly

Understanding this system is essential for maintaining Terraform's state, extending backends to new platforms, and debugging deployment issues.
