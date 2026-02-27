# Terraform State Backend Subsystem - Team Handoff Document

## Overview

The Terraform state backend subsystem is responsible for providing a pluggable abstraction layer for storing and managing state files, enabling Terraform to work seamlessly with both local and remote state storage. This document provides a comprehensive overview of the system architecture, key components, and operational patterns.

---

## 1. Purpose

### What Problem Does the State Backend Subsystem Solve?

The state backend system abstracts the underlying storage mechanism for Terraform state files, solving several critical problems:

1. **Storage Flexibility**: Enables Terraform to store state in diverse backends (local filesystem, AWS S3, Azure Blob Storage, Terraform Cloud, Consul, PostgreSQL, etc.) without changing core Terraform logic
2. **Team Collaboration**: Allows multiple team members to safely work on the same infrastructure by storing shared state in remote backends with locking mechanisms
3. **State Isolation**: Supports workspaces (named state files) for managing multiple environments (dev, staging, production) from a single configuration
4. **Operational Safety**: Provides state locking to prevent concurrent modifications that could corrupt state

### Why Different Backend Types?

Different backend types address different deployment scenarios:

- **Local Backend** (`terraform.tfstate`): Development and single-developer workflows; state stored on the filesystem
- **Remote State Backends** (S3, Azure, GCS, Consul, etc.): Team environments where state must be centralized and shared
- **Remote Backend (Terraform Cloud/Enterprise)**: Full managed solution with runs, teams, policies, and VCS integration
- **HTTP Backend**: Custom HTTP servers for specialized environments
- **Kubernetes Backend**: State storage within Kubernetes for cloud-native deployments
- **PostgreSQL Backend**: Enterprise databases for high-availability scenarios

### Key Responsibilities of a Backend

1. **Configuration Schema Definition**: Expose configuration options with validation
2. **State Management**: Provide access to state managers for reading, writing, and locking state
3. **Workspace Management**: Support multiple named workspaces (environments)
4. **Operation Execution** (for enhanced backends): Execute Terraform operations (plan, apply, refresh) locally or remotely
5. **Lock Management**: Coordinate state access across multiple processes/machines
6. **Version Compatibility**: Report Terraform version and handle version conflicts

---

## 2. Dependencies

### How the Backend System Integrates

```
CLI Commands (plan, apply, destroy, etc.)
    ↓
Command Package (`internal/command/`)
    ↓
Backend Interface (`internal/backend/backend.go`)
    ↓
Concrete Backends (local, remote, S3, Azure, etc.)
    ↓
State Management (`internal/states/statemgr/`)
    ↓
Persistent Storage (filesystem, S3, Consul, etc.)
```

### Upstream Dependencies (What Calls Into Backends)

- **CLI Commands**: All Terraform commands that need state (apply, plan, destroy, refresh, state, import, etc.) obtain the backend and state manager from CLI metadata
- **Command Package** (`internal/command/meta_backend.go`): Initializes and configures backends based on configuration
- **State Migration Logic** (`internal/command/meta_backend_migrate.go`): Handles migration when backend configuration changes
- **Workdir Package** (`internal/command/workdir/backend_state.go`): Manages workspace state transitions

### Downstream Dependencies (What Backends Call)

- **State Management System** (`internal/states/statemgr/`): Backends return state managers implementing `statemgr.Full` interface
- **Configuration Schema** (`internal/configs/configschema/`): Define backend configuration options
- **State File Format** (`internal/states/statefile/`): Serialize/deserialize state snapshots
- **Terraform Context** (`internal/terraform/context.go`): Execution context for operations
- **Cloud Integration** (`internal/cloud/`): Special integration with Terraform Cloud
- **Remote HTTP Client** (`internal/states/remote/`): HTTP-based state access for remote operations
- **Service Discovery** (`terraform-svchost/disco`): Finding remote backend services (Terraform Cloud, TFE)

### Key Integration Points

1. **Backend Selection**: Determined by `terraform { backend "type" { ... } }` block in configuration
2. **State Access Pattern**: CLI gets backend → calls `Backend.StateMgr(workspace)` → receives `statemgr.Full` → locks state → reads/writes state
3. **Configuration Flow**: Raw HCL config → schema validation → `PrepareConfig()` → `Configure()` → backend ready to use
4. **Operation Flow** (enhanced backends only): CLI → `Operation()` → backend executes plan/apply → returns running operation context

---

## 3. Relevant Components

### Main Directory Structure

```
internal/backend/
├── backend.go                  # Core Backend interface definition
├── backendbase/                # Base implementation helpers
│   ├── base.go                 # Base struct for backends with schema
│   ├── sdklike.go              # SDK-like default value handling
│   ├── helper.go               # Helper functions
│   └── *_test.go               # Tests
├── backendrun/                 # Operation execution interfaces
│   ├── operation.go            # Operation, OperationsBackend interfaces
│   ├── operation_type.go       # OperationType enum (refresh, plan, apply)
│   ├── cli.go                  # CLI-related interfaces
│   └── local_run.go            # Local operation execution
├── local/                       # Local backend implementation
│   ├── backend.go              # Local struct, implements Backend
│   ├── backend_plan.go         # Plan operation implementation
│   ├── backend_apply.go        # Apply operation implementation
│   ├── backend_refresh.go      # Refresh operation implementation
│   ├── hook_state.go           # State hook for intermediate persistence
│   ├── cli.go                  # CLI input/output handling
│   └── *_test.go               # Tests
├── remote/                      # Remote (Terraform Cloud) backend
│   ├── backend.go              # Remote struct, implements OperationsBackend
│   ├── backend_apply.go        # Remote apply logic
│   ├── backend_state.go        # Remote state management
│   └── *_test.go               # Tests
├── remote-state/               # Remote state backends (not operations)
│   ├── s3/                      # AWS S3 backend
│   ├── azure/                   # Azure Blob Storage backend
│   ├── gcs/                     # Google Cloud Storage backend
│   ├── consul/                  # HashiCorp Consul backend
│   ├── http/                    # Custom HTTP backend
│   ├── pg/                      # PostgreSQL backend
│   ├── kubernetes/              # Kubernetes backend
│   ├── oss/                     # Alibaba OSS backend
│   ├── cos/                     # Tencent COS backend
│   └── inmem/                   # In-memory backend (testing)
├── init/                        # Backend registration and initialization
│   ├── init.go                  # Backend registry, Init() function
│   └── *_test.go                # Tests
└── testing.go                   # Test utilities (TestBackendStates, TestBackendStateLocks)

internal/states/statemgr/       # State management implementation
├── statemgr.go                 # Full interface definition (Storage + Locker)
├── persistent.go               # Persistent interface (Refresher + Persister)
├── transient.go                # Transient interface (Reader + Writer)
├── locker.go                   # Locker interface, LockInfo, LockError, LockWithContext
├── lock.go                     # Lock info JSON marshaling
├── filesystem.go               # Filesystem state manager
├── filesystem_lock_unix.go     # Unix POSIX fcntl locking
├── filesystem_lock_windows.go  # Windows locking
├── transient_inmem.go          # In-memory transient storage
├── migrate.go                  # State migration between backends
└── *_test.go                   # Tests
```

### Critical Interfaces and Types

#### 1. Backend Interface (`internal/backend/backend.go`)

```go
type Backend interface {
    // ConfigSchema returns configuration schema for this backend
    ConfigSchema() *configschema.Block

    // PrepareConfig validates and inserts defaults (no side-effects)
    PrepareConfig(cty.Value) (cty.Value, tfdiags.Diagnostics)

    // Configure applies the configuration to the backend (side-effects OK)
    Configure(cty.Value) tfdiags.Diagnostics

    // StateMgr returns the state manager for a workspace
    StateMgr(workspace string) (statemgr.Full, error)

    // DeleteWorkspace removes a workspace (except "default")
    DeleteWorkspace(name string, force bool) error

    // Workspaces lists all available workspaces
    Workspaces() ([]string, error)
}
```

#### 2. State Manager Interface (`internal/states/statemgr/statemgr.go`)

```go
type Full interface {
    Storage     // Transient + Persistent combined
    Locker      // Lock/Unlock for concurrent access
}

type Storage interface {
    Transient   // Reader + Writer (in-memory snapshots)
    Persistent  // Refresher + Persister (persistent storage)
}

type Transient interface {
    Reader      // State() retrieves current state
    Writer      // WriteState(state) updates in-memory state
}

type Persistent interface {
    Refresher   // RefreshState() loads from storage
    Persister   // PersistState() saves to storage
    OutputReader // GetRootOutputValues() for outputs
}
```

#### 3. Locker Interface (`internal/states/statemgr/locker.go`)

```go
type Locker interface {
    // Lock acquires a lock, returns lock ID or LockError
    Lock(info *LockInfo) (string, error)

    // Unlock releases the lock by ID
    Unlock(id string) error
}

type LockInfo struct {
    ID        string    // Unique lock ID
    Operation string    // "plan", "apply", "refresh"
    Info      string    // Extra caller-provided info
    Who       string    // user@hostname
    Version   string    // Terraform version
    Created   time.Time // Lock creation time
    Path      string    // Set by lock implementation
}

type LockError struct {
    Info *LockInfo  // Info about who holds the lock
    Err  error      // The underlying error
}

// LockWithContext provides retry logic with exponential backoff
func LockWithContext(ctx context.Context, s Locker, info *LockInfo) (string, error)
```

#### 4. OperationsBackend Interface (`internal/backend/backendrun/operation.go`)

Extends Backend with:
```go
type OperationsBackend interface {
    Backend

    // Operation executes a Terraform operation (plan, apply, refresh)
    Operation(context.Context, *Operation) (*RunningOperation, error)

    // ServiceDiscoveryAliases returns host aliases for discovery
    ServiceDiscoveryAliases() ([]HostAlias, error)
}
```

### Key Types and Their Purposes

1. **Local Backend** (`internal/backend/local/backend.go:Local`):
   - Implements `Backend` and `OperationsBackend`
   - Can wrap another backend for hybrid mode (local operations, remote state)
   - Field `Backend backend.Backend` allows nested backends
   - Manages workspaces as directories in `terraform.tfstate.d/`
   - Uses `statemgr.NewFilesystemBetweenPaths()` for state storage

2. **Remote Backend** (`internal/backend/remote/backend.go:Remote`):
   - Implements `OperationsBackend`
   - Executes operations on Terraform Cloud/Enterprise
   - Client field is `*tfe.Client` (Terraform Enterprise Go SDK)
   - Can fall back to local operations if configured
   - Implements run queue and state locking via TFE API

3. **Filesystem State Manager** (`internal/states/statemgr/filesystem.go:Filesystem`):
   - Implements `statemgr.Full` (both Persistent and Locker)
   - Uses POSIX fcntl locks (Unix) or Windows locks
   - Supports read/write paths (read old, write new)
   - Automatic backup on state modification
   - Uses `StateFile` struct for JSON serialization

4. **Base Backend** (`internal/backend/backendbase/base.go:Base`):
   - Partial implementation for backends
   - Implements `ConfigSchema()` and `PrepareConfig()` methods
   - Handles schema coercion and deprecated attribute warnings
   - Supports SDK-like defaults from environment variables

### Backend Registration System

**File**: `internal/backend/init/init.go`

```go
// Init() registers all built-in backends
func Init(services *disco.Disco)

// Available backends registered:
// - "local"        → Local filesystem backend
// - "remote"       → Terraform Cloud/Enterprise
// - "azurerm"      → Azure Blob Storage
// - "consul"       → HashiCorp Consul
// - "cos"          → Tencent Cloud Object Storage
// - "gcs"          → Google Cloud Storage
// - "http"         → Custom HTTP server
// - "inmem"        → In-memory (testing only)
// - "kubernetes"   → Kubernetes (CustomResourceDefinitions)
// - "oss"          → Alibaba Object Storage Service
// - "pg"           → PostgreSQL database
// - "s3"           → AWS S3 bucket
// - "cloud"        → HCP Terraform (internal alias)

var RemovedBackends map[string]string // Deprecated backends with messages
```

---

## 4. Failure Modes

### Common Failure Scenarios

#### 1. State Locking Failures

**Scenario**: Another Terraform process holds the state lock

**How It Happens**:
- Process A locks state for apply operation
- Process B tries to acquire lock → gets `*statemgr.LockError`
- `LockError` contains `LockInfo` with who holds the lock and when

**Lock Timeout Behavior**:
- `LockWithContext()` implements exponential backoff (1s → 2s → 4s → ... → 16s max)
- Retries until context timeout reached
- Returns last `LockError` if timeout exceeded

**Recovery**:
- Manual unlock via `terraform force-unlock <lock-id>` (if supported by backend)
- Wait for lock holder to finish and release lock
- Delete lock manually (dangerous, can corrupt state)

**Example Lock File** (S3 + DynamoDB):
```
DynamoDB item with:
  - LockID (hash key)
  - Info (JSON with operation, who, timestamp, version)
  - Digest (prevents modification)
```

#### 2. Storage Unavailability

**Scenario**: Backend storage becomes unreachable

**Examples**:
- S3 bucket doesn't exist or access denied
- Consul cluster is down
- Network connectivity lost
- Database connection timeout

**Behavior**:
- `RefreshState()` returns error
- `PersistState()` returns error
- State reads/writes fail mid-operation
- Local backend continues with cached state (risky)

**Detection**:
- Try-catch around state operations in CLI
- Specific error messages for authentication vs. network vs. not-found
- Azure backend checks for 404 vs. 401 vs. 503

#### 3. State Corruption

**Scenario**: State file becomes invalid or unreadable

**Causes**:
- Manual editing of state file with syntax errors
- Partial write due to crash
- Incompatible Terraform versions reading/writing state
- Concurrent writes without locking

**Prevention**:
- Atomic writes (write to temp file, rename)
- Serial number and lineage tracking
- Backup files on every write (configurable)
- Locking prevents concurrent writes

**Recovery**:
- Restore from backup file
- Revert to previous state version (if available)
- Manual state file repair (dangerous)
- `terraform state replace-provider` for provider issues

#### 4. Configuration Errors

**Scenario**: Invalid backend configuration

**Examples**:
- Missing required parameters (e.g., S3 bucket name)
- Invalid types (string instead of number)
- Deprecated attributes used
- Conflicting configuration options

**Detection**:
- `ConfigSchema()` validation
- `PrepareConfig()` checks for invalid values
- `Configure()` validates against external services
- Type coercion via `cty` library

**Behavior**:
- Early validation in `terraform init`
- Prevents backend initialization
- Useful error messages with HCL context

#### 5. Workspace Issues

**Scenario**: Workspace doesn't exist or can't be created

**Behavior**:
- Most backends auto-create workspaces on first access
- Some backends (local) create workspace directories explicitly
- Workspace deletion fails if state is locked
- Default workspace cannot be deleted

**Example Error**:
```
Error: Cannot delete default workspace
The "default" workspace cannot be deleted. You can create a new workspace
with the "workspace new" command and switch to it, but the default workspace
must always be available.
```

#### 6. Lock Contention and Stale Locks

**Scenario**: Lock exists but holder has crashed/disconnected

**Detection**:
- Lock holder metadata includes timestamp
- Can be detected via TFE API or external monitoring
- Consul has TTL mechanism for automatic cleanup

**Stale Lock Scenario**:
- Process A acquires lock and crashes
- Lock file remains with timestamps from now ± 10 hours ago
- Process B waits 10 minutes, gives up
- `terraform force-unlock <id>` needed to clean up

**Backend-Specific Handling**:
- **Local**: No automatic cleanup (manual deletion needed)
- **S3+DynamoDB**: Depends on TTL configuration
- **Consul**: Session timeout cleans up locks automatically
- **TFE**: API-managed, automatic cleanup on disconnect

#### 7. Version Conflicts

**Scenario**: Different Terraform versions writing to same state

**Behavior**:
- Newer versions can write state older versions can't read
- Compatibility tracked via `TerraformVersion` in state metadata
- Some backends enforce version matching (TFE)

**Detection**:
- Remote backend checks `VerifyWorkspaceTerraformVersion()`
- Compares configured version with actual version
- Can force continue with `ignoreVersionConflict` flag (risky)

### Debugging Techniques

1. **Lock Debugging**:
   - Check lock existence: `aws dynamodb scan --table-name terraform-locks` (S3)
   - View lock info: `consul kv get terraform-locks/` (Consul)
   - Force unlock (careful!): `terraform force-unlock <lock-id>`

2. **State Debugging**:
   - `terraform state list` - list resources
   - `terraform state show <resource>` - show resource details
   - `terraform state pull` - download state file
   - `terraform state push` - upload state file

3. **Backend Debugging**:
   - Set `TF_LOG=DEBUG` for verbose logging
   - Check backend-specific logs (CloudWatch for S3, etc.)
   - Verify backend configuration: `terraform show -json`
   - Test backend connectivity: `terraform validate`

---

## 5. Testing

### Test Architecture Overview

Backend testing follows patterns in `internal/backend/testing.go`:

1. **Configuration Testing** (`TestBackendConfig`):
   - Validate config schema
   - Apply defaults via `PrepareConfig()`
   - Call `Configure()`
   - Catch configuration errors early

2. **State Testing** (`TestBackendStates`):
   - Test workspace creation/listing/deletion
   - Verify workspace isolation
   - Test state persistence across reads/writes
   - Verify default workspace exists and can't be deleted

3. **Lock Testing** (`TestBackendStateLocks`):
   - Acquire lock from process A
   - Verify process B can't acquire lock
   - Release lock and verify process B can acquire
   - Test lock ID uniqueness
   - Test force-unlock behavior

### Testing Patterns

**Location**: `internal/backend/local/backend_test.go` (good example)

```go
func TestLocal_impl(t *testing.T) {
    // Verify Local implements required interfaces
    var _ backendrun.OperationsBackend = New()
    var _ backendrun.Local = New()
}

func TestLocal_backend(t *testing.T) {
    // Use generic backend tests
    b := New()
    backend.TestBackendStates(t, b)      // Test state management
    backend.TestBackendStateLocks(t, b, b) // Test locking
}
```

**Test Utilities**:
- `TestBackendConfig(t, backend, hcl.Body)` - Configure backend from HCL
- `TestWrapConfig(map[string]interface{})` - Convert Go map to HCL body
- `TestBackendStates(t, Backend)` - Generic workspace/state tests
- `TestBackendStateLocks(t, Backend, Backend)` - Locking tests (needs 2 instances)
- `TestBackendStateForceUnlock(t, Backend, Backend)` - Force-unlock tests

### Remote State Backend Testing

**Example**: `internal/backend/remote-state/s3/backend_test.go`

```go
func TestBackend(t *testing.T) {
    b := New()
    backend.TestBackendConfig(t, b, hcl.EmptyBody())
    backend.TestBackendStates(t, b)
    backend.TestBackendStateLocks(t, b, b)
}
```

**Characteristics**:
- Real integration with external services (AWS, Azure, etc.)
- Requires credentials (use environment variables)
- Can use mock servers for testing HTTP backend
- Cleanup of created state files/buckets needed

### Unit Testing for Locking

**File**: `internal/states/statemgr/lock_test.go`

Tests for `LockWithContext()`:
- Acquire lock
- Retry logic with backoff
- Context cancellation
- Lock error handling
- Lock info marshaling

### State File Testing

**File**: `internal/states/statemgr/filesystem_test.go`

Tests for `Filesystem` state manager:
- Read/write state files
- Backup file creation
- Lock acquisition/release
- File permissions
- Concurrent access (via locks)

---

## 6. Debugging

### Diagnosing Backend Issues

#### Enable Debug Logging

```bash
# Set debug level
export TF_LOG=DEBUG

# Set more detailed logging
export TF_LOG=TRACE

# Write to file instead of stderr
export TF_LOG_PATH=terraform-debug.log
```

**What Gets Logged**:
- Backend initialization sequence
- Configuration validation steps
- Lock acquisition attempts
- State read/write operations
- API calls to remote services

#### Verify Backend Configuration

```bash
# Show merged backend configuration
terraform show -json | jq '.backend'

# Test backend connectivity without applying
terraform init

# Check which workspace is active
terraform workspace show

# List available workspaces
terraform workspace list
```

#### Inspect State Files

```bash
# Download current state
terraform state pull > current.state

# View state in JSON format
terraform state pull | jq '.resources'

# List managed resources
terraform state list

# Show specific resource
terraform state show 'aws_instance.example'
```

#### Debug Lock Issues

```bash
# For S3 backend with DynamoDB locks
aws dynamodb scan \
  --table-name terraform-locks \
  --region us-east-1

# Check lock info (if available)
aws s3 getobject \
  --bucket my-bucket \
  --key env/prod/terraform.tfstate.d/default/.terraform.lock.hcl \
  /dev/stdout

# For Consul backend
consul kv get -detailed terraform/

# For HTTP backend
curl -H "Authorization: Bearer <token>" https://server.com/state
```

#### Force Unlock (Last Resort)

```bash
# List lock ID from error message, then:
terraform force-unlock <LOCK_ID>

# Danger: This bypasses the lock without coordinating with other processes!
# Only use if:
# 1. You're sure the lock holder has crashed/disconnected
# 2. No other process is accessing the state
```

#### Troubleshoot Specific Backend Types

**S3 Backend**:
```bash
# Verify bucket exists and accessible
aws s3 ls s3://my-bucket/terraform.tfstate

# Check S3 bucket versioning (helps with rollback)
aws s3api get-bucket-versioning --bucket my-bucket

# Check DynamoDB table for locks
aws dynamodb describe-table --table-name terraform-locks
```

**Azure Backend**:
```bash
# Check storage account access
az storage account show --name mystorageaccount

# List state files
az storage blob list --account-name mystorageaccount --container-name tfstate

# Check lock (if using leases)
az storage blob show --account-name mystorageaccount \
  --container-name tfstate --name terraform.tfstate
```

**Consul Backend**:
```bash
# List Consul keys
consul kv get -recurse terraform/

# Check specific state
consul kv get terraform/state/default

# Monitor lock holder
consul watch -type key -key "terraform/lock" cat
```

**Terraform Cloud Backend**:
```bash
# Check run status
terraform show

# View workspace settings
terraform workspace show

# Check API token validity (in ~/.terraform/rc or $TERRAFORM_CONFIG)
echo $TERRAFORM_CONFIG
```

#### Analyze State Lineage

```bash
# Extract state metadata
terraform state pull | jq '.terraform_version, .serial, .lineage'

# Compare with remote state
terraform refresh  # Updates local copy from remote
terraform state pull | jq '.terraform_version, .serial, .lineage'
```

---

## 7. Adding a New Backend

### Step-by-Step Process

#### 1. Understand Your Storage Backend

Before coding, understand:
- What is your storage system? (cloud provider API, database, message queue, etc.)
- Does it support atomic writes? (important for consistency)
- Does it support locking? (mutex, lease, TTL-based?)
- What credentials/config does it need?
- How do you handle concurrent access?

**Example**: Adding a new cloud provider storage backend

#### 2. Create Package Structure

```bash
mkdir -p internal/backend/remote-state/mybackend
cd internal/backend/remote-state/mybackend

# Create files
touch backend.go backend_state.go client.go client_test.go backend_test.go
```

#### 3. Implement the Backend Interface

**File**: `internal/backend/remote-state/mybackend/backend.go`

```go
package mybackend

import (
    "github.com/hashicorp/terraform/internal/backend"
    "github.com/hashicorp/terraform/internal/backend/backendbase"
    "github.com/hashicorp/terraform/internal/configs/configschema"
    "github.com/zclconf/go-cty/cty"
    "github.com/hashicorp/terraform/internal/tfdiags"
    "github.com/hashicorp/terraform/internal/states/statemgr"
)

// New is the factory function
func New() backend.Backend {
    return &Backend{
        Base: backendbase.Base{
            Schema: &configschema.Block{
                Attributes: map[string]*configschema.Attribute{
                    "endpoint": {
                        Type:        cty.String,
                        Required:    true,
                        Description: "API endpoint URL",
                    },
                    "token": {
                        Type:        cty.String,
                        Optional:    true,
                        Sensitive:   true,
                        Description: "Authentication token",
                    },
                    // Add more attributes based on your backend config
                },
            },
        },
    }
}

type Backend struct {
    backendbase.Base

    // Store configuration after Configure() is called
    endpoint string
    token    string

    // Store API client
    client *MyServiceClient

    // Cache of state managers per workspace
    states map[string]statemgr.Full
}

func (b *Backend) Configure(configVal cty.Value) tfdiags.Diagnostics {
    var diags tfdiags.Diagnostics

    // Extract config values
    b.endpoint = configVal.GetAttr("endpoint").AsString()
    b.token = configVal.GetAttr("token").AsString()

    // Initialize API client
    var err error
    b.client, err = NewClient(b.endpoint, b.token)
    if err != nil {
        diags = diags.Append(tfdiags.Error(
            "Failed to initialize backend",
            fmt.Sprintf("Could not create client: %s", err),
        ))
    }

    return diags
}

func (b *Backend) Workspaces() ([]string, error) {
    // List all workspaces from backend
    workspaces, err := b.client.ListWorkspaces()
    if err != nil {
        return nil, err
    }
    // Always include "default"
    if !contains(workspaces, backend.DefaultStateName) {
        workspaces = append([]string{backend.DefaultStateName}, workspaces...)
    }
    return workspaces, nil
}

func (b *Backend) DeleteWorkspace(name string, force bool) error {
    if name == backend.DefaultStateName {
        return fmt.Errorf("cannot delete default workspace")
    }
    delete(b.states, name)
    return b.client.DeleteWorkspace(name)
}

func (b *Backend) StateMgr(name string) (statemgr.Full, error) {
    // Return cached state manager if already created
    if s, ok := b.states[name]; ok {
        return s, nil
    }

    // Create new state manager
    s := NewStateManager(b.client, name)

    if b.states == nil {
        b.states = make(map[string]statemgr.Full)
    }
    b.states[name] = s

    return s, nil
}
```

#### 4. Implement State Manager

**File**: `internal/backend/remote-state/mybackend/backend_state.go`

```go
package mybackend

import (
    "encoding/json"
    "fmt"

    "github.com/hashicorp/terraform/internal/states"
    "github.com/hashicorp/terraform/internal/states/statemgr"
    "github.com/hashicorp/terraform/internal/states/statefile"
)

// StateManager implements statemgr.Full
type StateManager struct {
    client    *MyServiceClient
    workspace string

    // Transient storage (in-memory)
    state *states.State

    // Lock information
    lockID string
    lockInfo *statemgr.LockInfo
}

var _ statemgr.Full = (*StateManager)(nil)

func NewStateManager(client *MyServiceClient, workspace string) *StateManager {
    return &StateManager{
        client:    client,
        workspace: workspace,
    }
}

// Implement Reader interface (transient)
func (s *StateManager) State() *states.State {
    if s.state == nil {
        return nil
    }
    return s.state.DeepCopy()
}

// Implement Writer interface (transient)
func (s *StateManager) WriteState(state *states.State) error {
    s.state = state
    return nil
}

// Implement Refresher interface (persistent)
func (s *StateManager) RefreshState() error {
    payload, err := s.client.GetState(s.workspace)
    if err != nil {
        return err
    }

    file, err := statefile.Read(payload)
    if err != nil {
        return err
    }

    s.state = file.State
    return nil
}

// Implement Persister interface (persistent)
func (s *StateManager) PersistState(schemas *schemarepo.Schemas) error {
    if s.state == nil {
        return fmt.Errorf("no state to persist")
    }

    // Serialize state to file format
    stateFile := &statefile.File{
        State:   s.state,
        Version: statefile.Version,
    }

    // Marshal to JSON
    data, err := json.Marshal(stateFile)
    if err != nil {
        return err
    }

    // Write to backend
    return s.client.PutState(s.workspace, data)
}

// Implement Locker interface
func (s *StateManager) Lock(info *statemgr.LockInfo) (string, error) {
    if s.lockID != "" {
        return s.lockID, nil // Already locked
    }

    lockID, err := s.client.Lock(s.workspace, info)
    if err != nil {
        if conflictErr, ok := err.(ConflictError); ok {
            return "", &statemgr.LockError{
                Info: conflictErr.ExistingLock,
                Err:  conflictErr,
            }
        }
        return "", err
    }

    s.lockID = lockID
    s.lockInfo = info
    return lockID, nil
}

func (s *StateManager) Unlock(id string) error {
    if s.lockID != id {
        return fmt.Errorf("unlock ID does not match lock ID")
    }

    err := s.client.Unlock(s.workspace, id)
    if err == nil {
        s.lockID = ""
        s.lockInfo = nil
    }
    return err
}
```

#### 5. Implement API Client

**File**: `internal/backend/remote-state/mybackend/client.go`

```go
package mybackend

import (
    "fmt"
    "io"
)

type MyServiceClient struct {
    endpoint string
    token    string
    // HTTP client or SDK client
}

func NewClient(endpoint, token string) (*MyServiceClient, error) {
    // Validate connectivity
    client := &MyServiceClient{
        endpoint: endpoint,
        token:    token,
    }

    // Test connection
    if err := client.ping(); err != nil {
        return nil, fmt.Errorf("failed to connect to backend: %w", err)
    }

    return client, nil
}

func (c *MyServiceClient) ping() error {
    // Test API connectivity
    // Return error if unreachable
    return nil
}

func (c *MyServiceClient) GetState(workspace string) (io.ReadCloser, error) {
    // Fetch state file from backend
    // Return reader or error
    panic("implement me")
}

func (c *MyServiceClient) PutState(workspace string, data []byte) error {
    // Store state file in backend
    // Use atomic write if possible
    panic("implement me")
}

func (c *MyServiceClient) ListWorkspaces() ([]string, error) {
    // List available workspaces
    panic("implement me")
}

func (c *MyServiceClient) DeleteWorkspace(workspace string) error {
    // Delete workspace from backend
    panic("implement me")
}

func (c *MyServiceClient) Lock(workspace string, info *statemgr.LockInfo) (string, error) {
    // Acquire lock
    // Return lock ID or LockError if already locked
    panic("implement me")
}

func (c *MyServiceClient) Unlock(workspace string, lockID string) error {
    // Release lock by ID
    panic("implement me")
}
```

#### 6. Register Backend

**File**: `internal/backend/init/init.go` (modification)

```go
func Init(services *disco.Disco) {
    backendsLock.Lock()
    defer backendsLock.Unlock()

    backends = map[string]backend.InitFn{
        // ... existing backends ...
        "mybackend": func() backend.Backend { return mybackend.New() },
    }
}
```

Also add import:
```go
import (
    // ... other imports ...
    backendMyBackend "github.com/hashicorp/terraform/internal/backend/remote-state/mybackend"
)
```

#### 7. Write Tests

**File**: `internal/backend/remote-state/mybackend/backend_test.go`

```go
package mybackend

import (
    "testing"

    "github.com/hashicorp/terraform/internal/backend"
    "github.com/hashicorp/hcl/v2"
)

func TestBackend(t *testing.T) {
    // Create backend instance
    b := New()

    // Test configuration
    config := hcl.EmptyBody() // Or real config
    b = backend.TestBackendConfig(t, b, config).(*Backend)

    // Test state management
    backend.TestBackendStates(t, b)

    // Test locking (requires 2 instances)
    b2 := New()
    backend.TestBackendConfig(t, b2, config)
    backend.TestBackendStateLocks(t, b, b2)
}

func TestBackendStates(t *testing.T) {
    // Similar to local backend tests
}

func TestBackendLocks(t *testing.T) {
    // Test locking functionality
}
```

#### 8. Add Integration Tests (Optional)

For remote backends, add tests that:
- Create real resources
- Test authentication failures
- Test network timeouts
- Test concurrent access

```go
//go:build acceptance

func TestAccBackend_...(t *testing.T) {
    // Acceptance test with real backend
}
```

### Checklist for New Backend

- [ ] Package created in `internal/backend/remote-state/<name>/`
- [ ] `backend.go` implements `Backend` interface
- [ ] `backend_state.go` implements `statemgr.Full` interface
- [ ] `client.go` implements API client for your service
- [ ] Backend registered in `internal/backend/init/init.go`
- [ ] Tests written in `*_test.go` files
- [ ] Documentation added (in separate doc files)
- [ ] CI/CD configured for integration tests
- [ ] Error messages are user-friendly
- [ ] Supports workspace isolation
- [ ] Supports state locking (or returns clear error)
- [ ] Handles version conflicts gracefully

### Example: Testing Your New Backend

```bash
# Unit tests
cd internal/backend/remote-state/mybackend
go test -v

# Integration tests (requires credentials)
export MY_BACKEND_ENDPOINT=...
export MY_BACKEND_TOKEN=...
go test -v -tags=acceptance -run TestAcc

# Full backend test suite
cd ../../
go test -v ./... -run mybackend
```

---

## Common Patterns and Best Practices

### 1. Configuration Patterns

**Using backendbase.Base**:
- Reduces boilerplate for schema validation
- Automatically handles deprecated attributes
- Supports environment variable defaults via SDKLikeDefaults

**Example**: S3 backend uses backendbase but adds custom validation

```go
type Backend struct {
    backendbase.Base
    // ... custom fields ...
}
```

### 2. State Manager Patterns

**Pattern 1: Simple wrapper around external API**:
- Load state on demand via `RefreshState()`
- Cache in memory via `WriteState()`
- Persist back to storage via `PersistState()`

**Pattern 2: With explicit read/write paths**:
- Use `NewFilesystemBetweenPaths(readPath, writePath)`
- Useful for migration scenarios

### 3. Lock Implementation Patterns

**POSIX fcntl locks** (filesystem):
- Per-file locks using OS mechanisms
- Automatically released on process exit
- Works across NFS/CIFS

**API-based locks** (S3, Consul, HTTP):
- Explicit lock/unlock calls
- Must track lock ID for release
- Handle stale locks gracefully
- Return `*statemgr.LockError` on conflict

**TTL-based locks** (Consul):
- Lock with TTL that auto-expires
- Prevents stale locks permanently
- Renewal during operation

### 4. Error Handling Patterns

**Configuration Errors**:
- Return in `PrepareConfig()` for schema validation
- Return in `Configure()` for connectivity/credential tests
- Use `tfdiags` package for proper error reporting

**Runtime Errors**:
- Lock errors: wrap in `*statemgr.LockError` with holder info
- Storage errors: return raw error with context
- State file corruption: clear error message suggesting recovery steps

### 5. Testing Patterns

**Use generic backend tests**:
```go
backend.TestBackendStates(t, b)
backend.TestBackendStateLocks(t, b1, b2)
```

**Add backend-specific tests**:
- Configuration validation
- Authentication failures
- Network errors/timeouts
- Concurrent operations
- Workspace isolation

**Avoid hardcoded paths**:
- Use temporary directories
- Clean up after tests
- Support parallel test execution

---

## Quick Reference

### File Locations

| Component | Location |
|-----------|----------|
| Backend interface | `internal/backend/backend.go` |
| State manager interfaces | `internal/states/statemgr/*.go` |
| Local backend | `internal/backend/local/` |
| Remote backend | `internal/backend/remote/` |
| Remote state backends | `internal/backend/remote-state/` |
| Backend initialization | `internal/backend/init/init.go` |
| Backend tests | `internal/backend/testing.go` |

### Key Types

| Type | Location | Purpose |
|------|----------|---------|
| `Backend` | `backend/backend.go` | Main backend interface |
| `OperationsBackend` | `backendrun/operation.go` | Backend that executes operations |
| `statemgr.Full` | `states/statemgr/statemgr.go` | Full state manager |
| `statemgr.Locker` | `states/statemgr/locker.go` | Locking interface |
| `Filesystem` | `states/statemgr/filesystem.go` | File-based state manager |
| `Local` | `backend/local/backend.go` | Local operations backend |
| `Remote` | `backend/remote/backend.go` | Terraform Cloud operations backend |

### Common Operations

```go
// Get backend
b := init.Backend("local")() // Factory function

// Configure backend
diags := b.Configure(configVal)

// Get state manager
mgr, err := b.StateMgr("default")

// Lock state
info := statemgr.NewLockInfo()
info.Operation = "apply"
lockID, err := statemgr.LockWithContext(ctx, mgr, info)
defer mgr.Unlock(lockID)

// Read state
err := mgr.RefreshState()
state := mgr.State()

// Modify state
mgr.WriteState(newState)
err := mgr.PersistState(schemas)
```

---

## Key Takeaways

1. **Abstraction Layer**: Backend system allows Terraform to support multiple storage backends without changing core logic

2. **Interface-Based Design**: Backend and state manager interfaces enable pluggable implementations

3. **Locking is Critical**: State locking prevents corruption in team environments; implement it correctly

4. **State Managers Do Two Jobs**:
   - Transient (in-memory) for manipulation
   - Persistent (external storage) for durability

5. **Workspaces Enable Multi-Environment**: Each workspace is independent state, useful for dev/staging/prod

6. **Error Handling Matters**: Clear error messages help users recover from common failures

7. **Testing is Comprehensive**: Generic tests + backend-specific tests ensure reliability

8. **Adding Backends is Straightforward**: Follow the patterns in existing backends

---

## Additional Resources

- **Go Documentation**: State types in `internal/states/`
- **Configuration Schema**: `internal/configs/configschema/`
- **State File Format**: `internal/states/statefile/`
- **Terraform Documentation**: https://www.terraform.io/language/settings/backends
- **Testing Patterns**: Review `internal/backend/remote-state/s3/` for real-world example

---

**Document Version**: 1.0
**Last Updated**: February 2026
**Relevant Terraform Versions**: 1.3+

