# Terraform State Backend Subsystem Handoff Document

## 1. Purpose

The state backend subsystem provides an abstraction layer that allows Terraform to manage state in multiple ways while maintaining a consistent interface. It solves the following problems:

- **Local vs. Remote Operations**: The same CLI can operate both locally (storing state on disk) and remotely (e.g., via HCP Terraform, Terraform Cloud, or cloud storage services)
- **Multiple Storage Backends**: Supports various storage systems (S3, Azure Storage, Google Cloud Storage, Consul, Kubernetes, etc.) without CLI changes
- **Team Collaboration**: Enables state sharing and locking for teams using remote backends
- **Workspace Management**: Provides isolation between different infrastructure environments (default workspace plus named workspaces)
- **State Locking**: Prevents concurrent modifications through distributed locking mechanisms

### Why Multiple Backend Types?

Different environments have different requirements:
- **Local**: Simple single-user development, no network dependency
- **S3**: AWS-native teams, mature ecosystem, cost-effective
- **Azure/GCS**: Native cloud provider solutions
- **Remote/Cloud**: Enterprise features, VCS integration, state history, policy
- **Consul/etcd**: Kubernetes-native, distributed systems teams
- **HTTP**: Custom solutions, on-premises backends

## 2. Dependencies

### Upstream Dependencies (Who Calls Backends)

The backend system is invoked by the **command package** (CLI commands):

| Component | File | Purpose |
|-----------|------|---------|
| `ApplyCommand` | `internal/command/apply.go` | Orchestrates apply operations |
| `PlanCommand` | `internal/command/plan.go` | Orchestrates plan operations |
| `RefreshCommand` | `internal/command/refresh.go` | Orchestrates refresh operations |
| `MetaBackend` | `internal/command/meta_backend.go` | Backend initialization and management |
| `Meta` | `internal/command/meta.go` | Provides `RunOperation()` to execute backends |

**Call Flow**: Commands → `Meta.RunOperation()` → `backendrun.OperationsBackend.Operation()`

### Downstream Dependencies (What Backends Call)

Backends depend on these systems:

| Component | Package | Purpose |
|-----------|---------|---------|
| Terraform Core | `internal/terraform` | Execution context (Plan, Apply, Import) |
| State Management | `internal/states`, `internal/states/statemgr` | State representation and persistence |
| Remote State | `internal/states/remote` | Client interface for remote state backends |
| Configuration | `internal/configs` | HCL configuration parsing |
| Diagnostics | `internal/tfdiags` | Error/warning reporting |
| Providers | Provider protocol | Provider plugins for resource management |

### Architecture Integration

```
┌─────────────────────────────────────────┐
│         CLI Commands                     │
│  (apply, plan, refresh, destroy, etc.)  │
└────────────────┬────────────────────────┘
                 │
         ┌───────▼──────────┐
         │ Meta.RunOperation│
         └───────┬──────────┘
                 │
    ┌────────────▼───────────────┐
    │ OperationsBackend.Operation│ (interface)
    └────────────┬───────────────┘
                 │
    ┌────────────▼─────────────────────────────┐
    │  Backend Implementations                  │
    │  ├─ Local (local operations)              │
    │  ├─ Remote (Terraform Cloud/Enterprise)  │
    │  └─ Cloud (HCP Terraform)                │
    └────────────┬─────────────────────────────┘
                 │
    ┌────────────▼──────────────────────────────┐
    │  Terraform Core (terraform.Context)       │
    │  ├─ Plan execution                        │
    │  ├─ Apply execution                       │
    │  └─ Provider interaction                  │
    └─────────────────────────────────────────────┘
                 │
    ┌────────────▼──────────────────────────────┐
    │  State Management (statemgr)              │
    │  ├─ Persistent (read/write state)        │
    │  ├─ Locker (distributed locking)         │
    │  └─ Transient (in-memory state)          │
    └──────────────────────────────────────────┘
```

## 3. Relevant Components

### Directory Structure

```
internal/backend/
├── backend.go                 # Core Backend interface
├── backendbase/               # Base utilities
├── backendrun/                # Operation/CLI/Local interfaces
│   ├── operation.go           # Operation struct definition
│   ├── cli.go                 # CLI interface
│   └── local_run.go           # Local backend run interface
├── init/                      # Backend registration
│   └── init.go                # Backend factory initialization
├── local/                     # Local backend implementation
│   ├── backend.go             # Local backend struct
│   ├── backend_apply.go       # Apply operation implementation
│   ├── backend_plan.go        # Plan operation implementation
│   ├── backend_refresh.go     # Refresh operation implementation
│   ├── cli.go                 # CLI initialization
│   └── hook_state.go          # State persistence hooks
├── remote/                    # Terraform Cloud/Enterprise backend
│   └── backend.go             # Remote operations backend
├── remote-state/              # Remote state storage backends
│   ├── s3/                    # AWS S3 backend
│   ├── azure/                 # Azure Storage backend
│   ├── gcs/                   # Google Cloud Storage backend
│   ├── consul/                # Consul backend
│   ├── http/                  # Generic HTTP backend
│   ├── kubernetes/            # Kubernetes backend
│   ├── pg/                    # PostgreSQL backend
│   ├── oss/                   # Aliyun OSS backend
│   ├── cos/                   # Tencent COS backend
│   └── inmem/                 # In-memory backend (testing)
└── testing.go                 # Testing utilities

internal/states/
├── statemgr/                  # State manager interfaces
│   ├── statemgr.go            # Full interface (Storage + Locker)
│   ├── persistent.go          # Persistent, Refresher, Persister
│   ├── locker.go              # Locker, LockInfo, LockError
│   ├── filesystem.go          # Local filesystem state storage
│   ├── lock.go                # LockDisabled wrapper
│   └── transient.go           # In-memory state
└── remote/                    # Remote state client
    └── remote.go              # Client, ClientLocker interfaces
```

### Core Interfaces

#### Backend Interface (internal/backend/backend.go:43-106)
```go
type Backend interface {
    ConfigSchema() *configschema.Block
    PrepareConfig(cty.Value) (cty.Value, tfdiags.Diagnostics)
    Configure(cty.Value) tfdiags.Diagnostics
    StateMgr(workspace string) (statemgr.Full, error)
    DeleteWorkspace(name string, force bool) error
    Workspaces() ([]string, error)
}
```

**Key Methods**:
- `ConfigSchema()`: Describes expected configuration structure
- `PrepareConfig()`: Validates and normalizes config before Configure
- `Configure()`: One-time initialization with validated config
- `StateMgr()`: Returns state manager for a workspace
- `Workspaces()`: Lists all available workspaces
- `DeleteWorkspace()`: Removes a workspace

#### OperationsBackend Interface (internal/backend/backendrun/operation.go:37-52)
```go
type OperationsBackend interface {
    backend.Backend
    Operation(context.Context, *Operation) (*RunningOperation, error)
    ServiceDiscoveryAliases() ([]HostAlias, error)
}
```

Only implemented by:
- `Local` (local operations backend)
- `Remote` (Terraform Cloud/Enterprise)
- `Cloud` (HCP Terraform)

#### Local Interface (internal/backend/backendrun/local_run.go:22-33)
```go
type Local interface {
    LocalRun(*Operation) (*LocalRun, statemgr.Full, tfdiags.Diagnostics)
}
```

Enables console, import, graph operations that need direct config access.

#### CLI Interface (internal/backend/backendrun/cli.go:28-39)
```go
type CLI interface {
    backend.Backend
    CLIInit(*CLIOpts) error
}
```

Allows backends to receive CLI configuration (flags, streams, context options).

### State Management Interfaces (internal/states/statemgr/)

#### Full Interface (statemgr.go:26-29)
```go
type Full interface {
    Storage
    Locker
}
```

The "all-in-one" interface that backends return via `StateMgr()`.

#### Storage Interface (statemgr.go:12-15)
```go
type Storage interface {
    Transient  // In-memory state access
    Persistent // Disk/remote storage access
}
```

#### Persistent Interface (persistent.go:25-29)
```go
type Persistent interface {
    Refresher
    Persister
    OutputReader
}
```

- `Refresher`: Read from persistent storage
- `Persister`: Write to persistent storage
- `OutputReader`: Get output values

#### Locker Interface (locker.go:48-65)
```go
type Locker interface {
    Lock(info *LockInfo) (string, error)
    Unlock(id string) error
}
```

**Lock Retry**: Use `LockWithContext()` (locker.go:75-111) for automatic retry with backoff.

**Lock Error Handling**: `LockError` (locker.go:212-227) contains:
- `Info *LockInfo` - Details about existing lock
- `Err error` - Underlying error

**LockInfo Structure** (locker.go:118-141):
```go
type LockInfo struct {
    ID        string    // Lock ID (returned by Lock)
    Operation string    // Operation type
    Info      string    // Extra info
    Who       string    // user@hostname
    Version   string    // Terraform version
    Created   time.Time // Lock creation time
    Path      string    // State file path
}
```

### Remote State Client Interface (internal/states/remote/remote.go:13-38)
```go
type Client interface {
    Get() (*Payload, error)
}

type ClientLocker interface {
    Client
    Lock(info *LockInfo) (string, error)
    Unlock(id string) error
}
```

Used by remote state backends (S3, Azure, GCS, etc.) to implement state persistence.

### Operation Struct (internal/backend/backendrun/operation.go:69-157)

Key fields:
- `Type OperationType` - operation type (Plan, Apply, Refresh, etc.)
- `ConfigDir string` - path to terraform configuration
- `ConfigLoader *configload.Loader` - loader for config
- `Workspace string` - workspace name
- `DependencyLocks *depsfile.Locks` - locked dependencies
- `PlanFile *planfile.WrappedPlanFile` - plan file to apply
- `AutoApprove bool` - skip approval for apply
- `Variables map[string]UnparsedVariableValue` - TF variables
- `View views.Operation` - UI rendering
- `UIIn terraform.UIInput` - user input
- `UIOut terraform.UIOutput` - user output
- `StateLocker clistate.Locker` - for locking with UI feedback

### Concrete Backend Implementations

#### Local Backend (internal/backend/local/)

**Key Files**:
- `backend.go` - Backend implementation
- `backend_plan.go` - Plan execution
- `backend_apply.go` - Apply execution
- `backend_refresh.go` - Refresh execution
- `hook_state.go` - State persistence during execution

**Features**:
- Only OperationsBackend that performs actual terraform operations locally
- Supports all Terraform operations (plan, apply, refresh, import, destroy, etc.)
- Can delegate state storage to another backend via `Backend` field
- State stored in local filesystem by default (`terraform.tfstate`)
- Workspaces stored in `terraform.tfstate.d/` directory
- State locking via filesystem lock files (platform-specific)

#### S3 Backend (internal/backend/remote-state/s3/)

**Key Files**:
- `backend.go` - Backend struct and ConfigSchema
- `client.go` - Remote client for S3 operations
- `backend_state.go` - State manager factory

**Features**:
- Remote-only backend (no operations)
- State stored in S3 bucket
- Optional state locking via DynamoDB
- MD5 checksum verification for consistency
- Server-side encryption support
- Multi-workspace support (via key prefix)

**Lock Flow**:
```
Lock() → DynamoDB PutItem (conditional, fails if exists)
         → Returns lock ID
Unlock() → DynamoDB Delete (conditional, fails if ID mismatch)
```

#### Other Remote State Backends

Similar pattern to S3:
- **Azure** (azure/): Azure Blob Storage + Azure Locks
- **GCS** (gcs/): Google Cloud Storage + GCS object metadata
- **Consul** (consul/): Consul KV store + Consul sessions
- **PostgreSQL** (pg/): PostgreSQL table + row-level locks
- **Kubernetes** (kubernetes/): Kubernetes Secrets + Leases
- **Aliyun OSS** (oss/): Aliyun OSS + OTS table
- **Tencent COS** (cos/): Tencent COS + DynamoDB-like service
- **HTTP** (http/): Generic HTTP endpoint

#### Remote Backend (internal/backend/remote/)

- Terraform Cloud/Enterprise operations backend
- Supports state storage and execution in Terraform Cloud
- Implements OperationsBackend for plan/apply execution

#### Cloud Backend (internal/cloud/)

- HCP Terraform operations backend
- Modern implementation of Terraform Cloud support
- Implements OperationsBackend

### Backend Registration (internal/backend/init/init.go)

**Initialization**:
```go
func Init(services *disco.Disco) {
    backends = map[string]backend.InitFn{
        "local":      func() backend.Backend { return backendLocal.New() },
        "remote":     func() backend.Backend { return backendRemote.New(services) },
        "s3":         func() backend.Backend { return backendS3.New() },
        "azurerm":    func() backend.Backend { return backendAzure.New() },
        "gcs":        func() backend.Backend { return backendGCS.New() },
        // ... other backends
    }
}
```

**Accessing Backends**:
```go
func Backend(name string) backend.InitFn {
    // Returns InitFn that creates new backend instance
}

func Set(name string, f backend.InitFn) {
    // Override/register backends (for plugins or testing)
}
```

**Removed Backends** (stored in `RemovedBackends` map):
- artifactory (v1.3+)
- azure (replaced by azurerm)
- etcd, etcdv3 (v1.3+)
- manta (v1.3+)
- swift (v1.3+)

## 4. Failure Modes

### State Locking Failures

#### Stale Locks
- **Problem**: Lock exists but is held by a crashed process
- **Detection**: `LockWithContext()` retries with backoff (1s→16s)
- **Resolution**: `-force-unlock <lock-id>` forces lock release
- **Mitigation**: Lock timeout mechanisms (if supported by backend)

**Example**: S3 backend doesn't have automatic timeout; DynamoDB entry persists until manually removed.

#### Lock Contention
- **Problem**: Multiple processes waiting for same lock
- **Behavior**: `LockWithContext()` exponentially backs off (max 16s delay)
- **Timeout**: Context timeout determines how long to retry
- **User Impact**: User sees "Error acquiring lock" after timeout

#### Lock ID Mismatch
- **Problem**: Unlock called with wrong lock ID
- **Detection**: Backend verifies ID matches before unlocking
- **Resolution**: Correct ID required (visible in lock error output)

### State Storage Failures

#### Storage Unavailable
- **Local**: File permission errors, disk full
  - Error propagates immediately
  - Transactional write ensures consistency
- **Remote**: Network timeout, service outage
  - Backend-specific retry logic
  - Some backends have consistency checks (e.g., S3 checksum)

#### Concurrent Modifications
- **Problem**: Two processes write state simultaneously
- **Prevention**: Locker interface prevents (via locking)
- **Without Locking**: Backends use serial numbers in state
  - Higher serial = newer state
  - Prevents overwriting newer states with old ones
  - Not reliable without locking!

#### Corruption Detection
- **Checksums**: S3 backend verifies MD5
  - Retries with timeout (10s by default)
  - Returns `ErrBadChecksum` if mismatch persists
- **Serial Number Mismatch**: State manager detects serial jumps
  - Indicates concurrent write by another process
  - User warned about potential corruption

### Configuration Errors

#### Missing Required Config
- **Detection**: `ConfigSchema()` marks fields as Required
- **Validation**: `PrepareConfig()` checks for nil/empty values
- **Error**: Diagnostic error blocks `Configure()`

#### Invalid Config Values
- **Detection**: `PrepareConfig()` validates types and ranges
- **Example S3**: Bucket name validation, region validation
- **Example Local**: Path validation (not empty)

#### Missing Workspace
- **Error**: `ErrDefaultWorkspaceNotSupported` (some backends)
- **Meaning**: Backend requires named workspace, doesn't support "default"
- **User Solution**: Create workspace with `terraform workspace new`

#### Workspace Not Supported
- **Error**: `ErrWorkspacesNotSupported` (simple backends)
- **Meaning**: Backend doesn't support multiple workspaces
- **Example**: Some HTTP backends only support single state

### State Lock Error Handling

The system uses `statemgr.LockError` for specific handling:

```go
type LockError struct {
    Info *LockInfo  // Lock held by other process
    Err  error      // Underlying error
}
```

**Detection**:
```go
lockID, err := locker.Lock(info)
if lockErr, ok := err.(*statemgr.LockError); ok {
    // Another process holds the lock
    // lockErr.Info contains lock holder details
    // Can force unlock with lockErr.Info.ID
}
```

**Force Unlock** (command: `terraform force-unlock <lock-id>`):
```go
// Extract lock ID from error output
// Call: locker.Unlock(lockID) with the ID from LockInfo
// Requires user confirmation in CLI
```

## 5. Testing

### Test Utilities (internal/backend/testing.go)

#### TestBackendConfig
```go
func TestBackendConfig(t *testing.T, b Backend, c hcl.Body) Backend
```
- Validates and configures backend
- Uses schema to parse config
- Calls PrepareConfig and Configure
- Panics on error (test failure)

#### TestWrapConfig
```go
func TestWrapConfig(raw map[string]interface{}) hcl.Body
```
- Converts raw data to HCL body for testing
- Used with TestBackendConfig

#### TestBackendStates
```go
func TestBackendStates(t *testing.T, b Backend)
```
- Tests workspace functionality
- Creates/deletes workspaces
- Verifies state isolation
- Skips if `ErrWorkspacesNotSupported`

#### TestBackendStateLocks
```go
func TestBackendStateLocks(t *testing.T, b1, b2 Backend)
```
- Tests locking with two backend instances
- Verifies mutual exclusion
- Tests lock timeout/retry
- Skips if backend doesn't implement Locker

#### TestBackendStateForceUnlock
```go
func TestBackendStateForceUnlock(t *testing.T, b1, b2 Backend)
```
- Tests force-unlock functionality
- Extracts lock ID from LockError
- Verifies can unlock with extracted ID

### Backend Test Patterns

#### Basic Backend Test
```go
func TestBackend(t *testing.T) {
    // Create backend instance
    b := New()

    // Configure with test config
    backend.TestBackendConfig(t, b, backend.TestWrapConfig(map[string]interface{}{
        "bucket": "test-bucket",
        "key": "terraform.tfstate",
    }))

    // Test workspace functionality
    backend.TestBackendStates(t, b)

    // Test locking (needs two instances)
    b2 := New()
    backend.TestBackendConfig(t, b2, ...)
    backend.TestBackendStateLocks(t, b, b2)
}
```

#### Acceptance Tests

Backends implement acceptance tests that:
1. Use real cloud services (requires credentials)
2. Follow pattern: create resource → test operations → destroy
3. Set environment variable to run: `TF_ACC=1 go test`

**S3 Example**:
- Creates temp bucket
- Tests state storage
- Tests locking via DynamoDB
- Tests force-unlock
- Cleans up resources

### Test Location Patterns

| Type | Location | Files |
|------|----------|-------|
| Unit Tests | Same directory | `*_test.go` |
| Acceptance | Same directory | `backend_complete_test.go` (S3) |
| Integration | `internal/backend/local/` | `backend_test.go` |

**Example Files**:
- `internal/backend/testing.go` - Testing utilities
- `internal/backend/remote-state/s3/backend_test.go` - S3 unit tests
- `internal/backend/remote-state/s3/backend_complete_test.go` - S3 acceptance tests
- `internal/backend/local/backend_test.go` - Local backend tests

## 6. Debugging

### Logging

**Terraform Logging** (set `TF_LOG` environment variable):
```bash
TF_LOG=TRACE terraform apply    # Detailed backend operations
TF_LOG=DEBUG terraform apply    # Debug-level logging
TF_LOG=INFO terraform apply     # Info messages
```

**Log Locations** (for backends):
- Local backend: Logs to stderr, includes state paths
- Remote backends: Backend-specific logging
  - S3: AWS SDK logging
  - Consul: Consul client logging
  - HTTP: Request/response details

**Key Log Points**:
```go
// Local backend state locking
log.Printf("[TRACE] backend/local: requesting state lock for workspace %q", workspace)

// Remote client operations
log.Printf("[TRACE] s3: downloading remote state")

// Lock acquisition
log.Printf("[ERROR] state lock error: %s", lockErr.Error())
```

### State Lock Troubleshooting

#### Check Lock Status

**S3 Backend**:
```bash
# Check DynamoDB lock entry
aws dynamodb scan --table-name terraform-locks \
    --region us-west-2
```

**Consul Backend**:
```bash
# Check Consul session
consul session list

# Check key holding lock
consul kv get -recurse terraform/
```

**Kubernetes Backend**:
```bash
kubectl get leases -n default

# Check secret
kubectl get secret terraform-lock -o yaml
```

#### Verify State Consistency

**Local Filesystem**:
```bash
# Check state file
cat terraform.tfstate

# Check backup
cat terraform.tfstate.backup

# Check workspace directory
ls -la terraform.tfstate.d/
```

**Remote (S3)**:
```bash
# Verify state exists in S3
aws s3 ls s3://my-bucket/terraform.tfstate

# Check DynamoDB checksum
aws dynamodb get-item --table-name terraform-locks \
    --key '{"LockID":{"S":"my-bucket/terraform.tfstate"}}'
```

### Debugging State Corruption

**Symptoms**:
- Checksum mismatch errors (S3)
- Serial number mismatches
- Lock contention without lock

**Investigation Steps**:

1. **Check Lock Status**
   ```bash
   terraform force-unlock  # Shows current lock ID
   ```

2. **Verify Recent Writes**
   ```bash
   # Local: Check file modification time
   stat terraform.tfstate

   # S3: Check object metadata
   aws s3api head-object --bucket my-bucket --key terraform.tfstate
   ```

3. **Compare State Versions**
   ```bash
   # Save current state
   terraform state pull > current.json

   # Check state history (if available)
   # Different by backend
   ```

4. **Check for Concurrent Operations**
   ```bash
   # Local: Check if process is running
   ps aux | grep terraform

   # Remote: Check lock holder details in error message
   terraform apply 2>&1 | grep "Who:"
   ```

### Debug Mode for Backend Development

**Enable Detailed Logging**:
```bash
TF_LOG=TRACE TF_LOG_PATH=/tmp/tf-debug.log terraform apply
```

**Test Specific Backend**:
```bash
# Run tests with output
go test -v ./internal/backend/remote-state/s3 -run TestBackend

# Run acceptance tests
TF_ACC=1 go test -v ./internal/backend/remote-state/s3 -run TestBackendComplete
```

**Inspect Backend Instance**:
```go
// In code, add debug print to backend Configure
func (b *Backend) Configure(obj cty.Value) tfdiags.Diagnostics {
    log.Printf("[DEBUG] Backend configuration: %#v", b)
    // ... rest of method
}
```

## 7. Adding a New Backend

### Step-by-Step Process

#### Step 1: Create Backend Package

Create directory: `internal/backend/remote-state/mybackend/`

```
internal/backend/remote-state/mybackend/
├── backend.go       # Backend implementation
├── client.go        # Remote client (state storage)
├── backend_test.go  # Unit tests
└── testing.go       # Test utilities (optional)
```

#### Step 2: Implement Remote Client (client.go)

Implement `internal/states/remote.Client` interface:

```go
package mybackend

import (
    "github.com/hashicorp/terraform/internal/states/remote"
)

type RemoteClient struct {
    // Backend-specific fields
    config map[string]string
}

// Get retrieves state from remote storage
func (c *RemoteClient) Get() (*remote.Payload, error) {
    // Fetch state data from backend
    // Return:
    // - *remote.Payload with:
    //   - Data: []byte (state file contents)
    //   - MD5: []byte (MD5 hash of data)
    // - error if operation fails
    return &remote.Payload{
        Data: stateData,
        MD5:  md5Hash,
    }, nil
}

// Put stores state in remote storage
func (c *RemoteClient) Put(data []byte) error {
    // Store state data
    // Return error if fails
    return nil
}

// Delete removes state from remote storage
func (c *RemoteClient) Delete() error {
    // Remove state
    return nil
}
```

#### Step 3: Implement Locking (if supported)

Add to RemoteClient:

```go
// Lock implements statemgr.Locker
func (c *RemoteClient) Lock(info *statemgr.LockInfo) (string, error) {
    // Attempt to acquire lock
    // Return:
    // - lockID: unique ID for unlock
    // - statemgr.LockError if already locked (with existing lock info)
    // - error for other failures

    // Example: Try to create lock entry
    exists, existingLock := c.checkLock()
    if exists {
        return "", &statemgr.LockError{
            Info: existingLock,
            Err:  errors.New("state locked"),
        }
    }

    lockID := generateLockID()
    c.storeLock(lockID, info)
    return lockID, nil
}

// Unlock releases a lock
func (c *RemoteClient) Unlock(id string) error {
    // Verify lock ID matches
    // Remove lock
    // Return error if fails
    return c.removeLock(id)
}
```

#### Step 4: Implement Backend (backend.go)

```go
package mybackend

import (
    "github.com/hashicorp/terraform/internal/backend"
    "github.com/hashicorp/terraform/internal/configs/configschema"
    "github.com/hashicorp/terraform/internal/states/statemgr"
    "github.com/zclconf/go-cty/cty"
)

type Backend struct {
    // Schema-backed configuration
    // Typically use internal/legacy/helper/schema
    *schema.Backend

    // Backend-specific fields
    endpoint string
    bucket   string
    path     string
}

// New creates a new backend instance
func New() backend.Backend {
    s := &schema.Backend{
        Schema: map[string]*schema.Schema{
            "endpoint": {
                Type:        schema.TypeString,
                Required:    true,
                Description: "Backend endpoint URL",
            },
            "bucket": {
                Type:        schema.TypeString,
                Required:    true,
                Description: "Bucket/container name",
            },
            "path": {
                Type:        schema.TypeString,
                Optional:    true,
                Default:     "terraform.tfstate",
                Description: "Path to state file",
            },
        },
    }

    b := &Backend{Backend: s}
    b.Backend.ConfigureFunc = b.configure
    return b
}

// ConfigSchema returns the schema (via schema.Backend)
func (b *Backend) ConfigSchema() *configschema.Block {
    return b.Backend.ConfigSchema()
}

// PrepareConfig validates configuration (via schema.Backend)
func (b *Backend) PrepareConfig(obj cty.Value) (cty.Value, tfdiags.Diagnostics) {
    return b.Backend.PrepareConfig(obj)
}

// Configure initializes the backend with validated config
func (b *Backend) configure(ctx context.Context) error {
    // Extract config values
    data := b.Backend.Data.(*schema.ResourceData)

    b.endpoint = data.Get("endpoint").(string)
    b.bucket = data.Get("bucket").(string)
    b.path = data.Get("path").(string)

    // Initialize client
    // Test connection
    return nil
}

// StateMgr returns state manager for workspace
func (b *Backend) StateMgr(workspace string) (statemgr.Full, error) {
    if workspace != backend.DefaultStateName {
        // Some backends only support default workspace
        // return nil, backend.ErrWorkspacesNotSupported

        // Or support workspaces by modifying path
        // path = bucket + "/" + workspace + "/" + filename
    }

    client := &RemoteClient{
        config: map[string]string{
            "endpoint": b.endpoint,
            "bucket":   b.bucket,
            "path":     b.path,
        },
    }

    // Wrap in state manager
    stateMgr := statemgr.NewRemoteState(client)
    return stateMgr, nil
}

// Workspaces returns list of available workspaces
func (b *Backend) Workspaces() ([]string, error) {
    // Some backends don't support workspaces
    // return []string{backend.DefaultStateName}, nil

    // Or enumerate workspaces from backend
    workspaces := []string{backend.DefaultStateName}
    // ... query backend for other workspaces
    return workspaces, nil
}

// DeleteWorkspace removes a workspace
func (b *Backend) DeleteWorkspace(name string, force bool) error {
    if name == backend.DefaultStateName {
        return errors.New("cannot delete default workspace")
    }

    // Remove workspace state from backend
    return nil
}
```

#### Step 5: Register Backend

Edit `internal/backend/init/init.go`:

```go
import (
    // ... other imports
    backendMyBackend "github.com/hashicorp/terraform/internal/backend/remote-state/mybackend"
)

func Init(services *disco.Disco) {
    backendsLock.Lock()
    defer backendsLock.Unlock()

    backends = map[string]backend.InitFn{
        // ... existing backends ...
        "mybackend": func() backend.Backend { return backendMyBackend.New() },
    }
}
```

#### Step 6: Write Tests

```go
// backend_test.go
package mybackend

import (
    "testing"
    "github.com/hashicorp/terraform/internal/backend"
)

func TestBackend(t *testing.T) {
    b := New()
    backend.TestBackendConfig(t, b, backend.TestWrapConfig(map[string]interface{}{
        "endpoint": "http://localhost:9000",
        "bucket":   "test",
        "path":     "terraform.tfstate",
    }))

    // Test state management
    backend.TestBackendStates(t, b)

    // Test locking (if supported)
    b2 := New()
    backend.TestBackendConfig(t, b2, backend.TestWrapConfig(map[string]interface{}{
        "endpoint": "http://localhost:9000",
        "bucket":   "test",
        "path":     "terraform.tfstate",
    }))
    backend.TestBackendStateLocks(t, b, b2)
}

func TestBackendForceUnlock(t *testing.T) {
    b := New()
    backend.TestBackendConfig(t, b, backend.TestWrapConfig(map[string]interface{}{
        "endpoint": "http://localhost:9000",
        "bucket":   "test",
        "path":     "terraform.tfstate",
    }))

    b2 := New()
    backend.TestBackendConfig(t, b2, backend.TestWrapConfig(map[string]interface{}{
        "endpoint": "http://localhost:9000",
        "bucket":   "test",
        "path":     "terraform.tfstate",
    }))
    backend.TestBackendStateForceUnlock(t, b, b2)
}
```

#### Step 7: Document Backend

Add documentation in `website/docs/language/settings/backends/` directory with:
- Configuration reference
- Usage examples
- Locking support details
- Any limitations

#### Step 8: Build and Test

```bash
# Build Terraform
make build

# Run tests
go test -v ./internal/backend/remote-state/mybackend

# Run acceptance tests (requires test infrastructure)
TF_ACC=1 go test -v ./internal/backend/remote-state/mybackend -run TestBackendComplete
```

### Key Design Decisions

**When to Support Workspaces**:
- By default: only support `backend.DefaultStateName`
- Advanced: use prefix/suffix in path to support multiple workspaces
- Example: S3 uses key prefix (`workspace-path/terraform.tfstate`)

**When to Support Locking**:
- Simple backends (HTTP, in-memory): skip locking
- Production backends: implement via distributed locking
- Example: S3 uses DynamoDB, Consul uses sessions

**Configuration**:
- Use `internal/legacy/helper/schema` for config schema
- Provides ConfigSchema, PrepareConfig, Configure mechanisms
- Integrates with HCL validation system

**State Manager**:
- Use `statemgr.NewRemoteState()` to wrap RemoteClient
- Handles transient/persistent state separation
- Provides encryption/serialization

### Common Implementation Patterns

#### Pattern 1: Cloud Storage (S3, Azure, GCS)
```
RemoteClient → Cloud SDK → HTTP/HTTPS
State file stored as binary object
Optional: separate key for locking (DynamoDB, blob metadata, etc.)
```

#### Pattern 2: Distributed System (Consul, etcd)
```
RemoteClient → RPC/HTTP API → Distributed backend
State stored as value in key-value store
Locking via sessions/leases
```

#### Pattern 3: Database (PostgreSQL)
```
RemoteClient → SQL driver → Database
State stored in table row
Locking via row-level locks or separate lock table
```

#### Pattern 4: HTTP Custom Endpoint
```
RemoteClient → HTTP client → Custom HTTP server
GET request returns state
PUT request stores state
DELETE request removes state
No locking (server-side only or manual)
```

---

## Quick Reference

### Common Tasks

**View Current Backend**: `terraform show`

**Switch Backends**: Modify terraform block, run `terraform init`

**Migrate State**: `terraform state pull/push`

**Force Unlock**: `terraform force-unlock <lock-id>`

**Debug Backend Issues**: `TF_LOG=TRACE terraform apply`

### File Organization

| Purpose | Location |
|---------|----------|
| Core interfaces | `internal/backend/backend.go` |
| Operations | `internal/backend/backendrun/` |
| Local implementation | `internal/backend/local/` |
| Remote implementations | `internal/backend/remote-state/*/` |
| State management | `internal/states/statemgr/` |
| Remote client | `internal/states/remote/` |
| Testing utilities | `internal/backend/testing.go` |
| Registration | `internal/backend/init/init.go` |

### Key Types to Know

- `backend.Backend` - Primary interface
- `backendrun.OperationsBackend` - For plan/apply operations
- `statemgr.Full` - Complete state manager
- `statemgr.Locker` - Lock interface
- `statemgr.LockError` - Lock error details
- `remote.Client` - Remote state client
- `backendrun.Operation` - Operation parameters
- `backendrun.RunningOperation` - Operation result

---

*This document was created as a handoff guide for the Terraform state backend subsystem. For the latest information, refer to the official Terraform documentation and source code.*
