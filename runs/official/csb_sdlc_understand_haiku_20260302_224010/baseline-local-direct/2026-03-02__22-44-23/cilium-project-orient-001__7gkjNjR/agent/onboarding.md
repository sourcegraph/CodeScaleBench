# Cilium Codebase Orientation

## 1. Main Entry Point

### Where the Agent Starts
The cilium-agent binary starts execution at `/workspace/daemon/main.go`, which is a minimal entry point:

```go
func main() {
    agentHive := hive.New(cmd.Agent)
    cmd.Execute(cmd.NewAgentCmd(agentHive))
}
```

### CLI Framework
Cilium uses **Cobra** (`github.com/spf13/cobra`) for CLI command structure. The root command is defined in `/workspace/daemon/cmd/root.go:NewAgentCmd()`, which:
- Sets up the `cilium-agent` command with version flag support
- Initializes the configuration via `option.InitConfig()`
- Validates daemon-specific options via `option.Config.Validate()`
- Runs the hive via `h.Run()`

### Dependency Injection Framework
Cilium uses **Hive** (`github.com/cilium/hive`) for dependency injection and component orchestration. The key implementation is in `/workspace/pkg/hive/hive.go`:

- **Hive wrapper**: `pkg/hive/hive.go` wraps `github.com/cilium/hive` with Cilium-specific defaults
- **Cells**: The Agent is composed of cells defined in `/workspace/daemon/cmd/cells.go`
- **Main Agent module**: `cmd.Agent` is a `cell.Module` that combines:
  - `Infrastructure` cell (external services like K8s client, metrics, API server)
  - `ControlPlane` cell (business logic: policies, endpoints, services)
  - `datapath.Cell` (BPF programs, maps, device management)

### Configuration Library
Cilium uses **Viper** (`github.com/spf13/viper`) for configuration binding and environment variable support. The hive is initialized with `EnvPrefix: "CILIUM_"`, so environment variables like `CILIUM_POLICY_ENFORCEMENT_MODE` map to config fields.

---

## 2. Core Packages

### Core Package Overview

1. **`pkg/policy`** - Network policy enforcement engine
   - `repository.go`: Central policy repository that holds all active policies
   - `l4.go`: Layer 4 (TCP/UDP) policy rules and port range matching
   - `rule.go`: Individual policy rule representation and matching logic
   - `mapstate.go`: Converts policies into BPF map state for datapath
   - Handles Ingress/Egress rules, CIDR-based policies, service-to-service policies

2. **`pkg/endpoint`** - Endpoint lifecycle and policy enforcement at pod level
   - `endpoint.go`: Core Endpoint struct managing pod networking, policy state
   - `bpf.go`: Synchronizes endpoint policy state to BPF programs
   - `policy.go`: Policy resolution and application per endpoint
   - `regeneration/`: Handles endpoint regeneration when policies change

3. **`pkg/datapath`** - Kernel interaction and BPF program management
   - `loader/`: Compiles and loads eBPF programs onto network interfaces
   - `linux/`: Linux-specific datapath implementation
   - `maps/`: BPF map definitions (policy_map, ipcache_map, etc.)
   - Manages TC/XDP program attachment, routes, iptables rules

4. **`pkg/k8s`** - Kubernetes integration and resource watchers
   - `watchers/`: Event watchers for K8s resources (Pods, Services, NetworkPolicies)
   - `apis/cilium.io/v2/`: CRD type definitions (CiliumNetworkPolicy, CiliumNode, etc.)
   - `resource/`: Generic resource streaming framework
   - `client/`: Kubernetes API client wrapper

5. **`pkg/bpf`** - eBPF program compilation and utilities
   - `maps/`: BPF map creation and management (`ctmap`, `lbmap`, `policymap`)
   - Program loading infrastructure

### Supporting Core Packages

6. **`pkg/option`** - Daemon configuration and options
   - `config.go`: `DaemonConfig` struct with 1500+ configuration fields
   - `option.go`: Runtime-mutable options and option library

7. **`pkg/endpointmanager`** - Tracks and manages all local endpoints
   - Central registry of local pods/containers

8. **`pkg/node`** - Node-level state and discovery
   - `manager/`: Node discovery and synchronization

9. **`pkg/identity/cache`** - Security identity allocation
   - Maps labels to security identities

10. **`pkg/ipcache`** - IP-to-identity mapping
    - Synchronizes IP allocations to BPF ipcache map

---

## 3. Configuration Loading

### Configuration Pipeline

Cilium supports multiple configuration formats and sources, applied in this order:

1. **Default values** - Built into code (e.g., `defaults.go`)
2. **Configuration files** - YAML/TOML from disk
3. **CLI flags** - Command-line arguments
4. **Environment variables** - Prefixed with `CILIUM_`

### Key Functions

- **`option.InitConfig()`** (`pkg/option/config.go:4215`) - Returns a function that:
  - Reads config file from standard locations
  - Binds Viper to Cobra flags
  - Sets up environment variable binding with `CILIUM_` prefix

- **`initDaemonConfig()`** (`daemon/cmd/config.go`) - Performs daemon-specific initialization:
  - Loads config file via Viper
  - Unmarshals into `option.DaemonConfig`
  - Validates configuration values

- **`initLogging()`** - Initializes logger with config

### Configuration Struct

The main config struct is **`option.DaemonConfig`** (`pkg/option/config.go:1401`) with fields including:
- BPF paths: `BpfDir`, `LibDir`, `RunDir`
- Datapath mode: `DatapathMode`, `RoutingMode`
- Device config: `DirectRoutingDevice`, `EnableRuntimeDeviceDetection`
- Policy enforcement: Policy mode, enforcement flags
- K8s integration: API server URL, service/pod watch settings
- Networking: IPAM mode, tunnel settings, encryption

### Dependency Injection

The hive provides `option.Config` as a singleton via:
```go
cell.Provide(func() *option.DaemonConfig { return option.Config })
```

Cells depend on this to access daemon configuration.

---

## 4. Test Structure

Cilium uses multiple complementary testing approaches:

### 1. Unit Tests (`*_test.go` files)
- Located alongside source code (e.g., `/workspace/pkg/policy/rule_test.go`)
- Use standard Go `testing` package with `testify` assertions
- Fast execution (milliseconds), no special privileges
- Example: `daemon/cmd/daemon_test.go` tests daemon initialization with mocked datapath

### 2. Privileged Tests (require root/CAP_SYS_ADMIN)
- Marked with `testutils.PrivilegedTest(t)` at test start
- Use network namespaces and raw socket operations
- Example: `/workspace/daemon/cmd/daemon_privileged_test.go` tests network device removal
- Can use `pkg/testutils/netns` for isolated network namespace testing

### 3. Control Plane Integration Tests
- Located in `/workspace/test/controlplane/`
- Use the **Ginkgo** BDD framework
- Test full control-plane behavior without requiring kernel eBPF support
- Test suites organized by feature:
  - `test/controlplane/node/` - Node state management
  - `test/controlplane/services/` - Service/loadbalancer handling
  - `test/controlplane/pod/` - Pod networking
- Run via: `go test ./test/controlplane/`

### 4. BPF/Datapath Tests
- Located in `/workspace/test/bpf/`
- Require running in VM/container with kernel eBPF support
- Test actual BPF program behavior

### 5. E2E Tests
- Located in `/workspace/test/` subdirectories (`k8s/`, `consul/`, `eks/`, etc.)
- Full integration testing against real/Kind Kubernetes clusters
- Ginkgo-based

### Test Framework Components
- **`pkg/testutils`**: Common test utilities (identity mocks, fake datapath)
- **`hivetest`**: Hive cell testing support
- **`pkg/datapath/fake/`**: Fake datapath implementation for non-privileged tests

### Running Tests
```bash
# Unit tests only
go test ./pkg/policy/...

# Unit + privileged tests (requires root)
go test -c && sudo ./cmd.test

# Control plane tests
go test ./test/controlplane/

# Scoped test compilation (avoids building entire codebase)
go test -p 1 ./daemon/cmd/... # Build only daemon/cmd tests
```

---

## 5. Network Policy Pipeline

Tracing a CiliumNetworkPolicy from CRD to eBPF enforcement:

### Stage 1: CRD Definition & API
**Location**: `pkg/k8s/apis/cilium.io/v2/cnp_types.go`

- **CiliumNetworkPolicy CRD**: Defines the K8s resource type
  - Fields: `Spec` (api.Rule), `Specs` (api.Rules), `Status`
  - Rules contain: EndpointSelector, Ingress[], Egress[], IngressDeny[], EgressDeny[]

- **Rule types** (`pkg/policy/api/rule.go`):
  - Each Rule has EndpointSelector to identify target pods
  - IngressRule/EgressRule contain L4Rules (ports, protocols)
  - L4Rules can have L7Rules (HTTP, Kafka, DNS filters)

### Stage 2: K8s Watcher & Policy Discovery
**Location**: `pkg/k8s/watchers/`, `daemon/k8s/resources.go`

- **K8s Resource Watching**:
  - `daemon/k8s/resources.go:ResourcesCell` provides `CiliumNetworkPolicies` resource.Resource
  - Watches for CNP creates/updates/deletes via K8s informer

- **Policy Watcher**:
  - `pkg/policy/k8s/` package handles CNP events
  - `onUpsert()`: Processes new/modified CNPs
  - `onDelete()`: Cleans up deleted policies
  - Caches CNPs in `cnpCache` map

### Stage 3: Policy Repository & Resolution
**Location**: `pkg/policy/repository.go`, `pkg/policy/distillery.go`

- **Policy Repository** (`policy.Repository`):
  - Central repository holding all active policies
  - `AddPolicy()`: Adds CNP to repository
  - `DeletePolicy()`: Removes CNP from repository
  - `GetPolicyEngine()`: Returns policy decision engine

- **Policy Resolution**:
  - `distillery.go`: Converts Rules into simplified per-endpoint allow/deny maps
  - Resolves label selectors to endpoint identities
  - Creates "MapState": decision about which traffic is allowed/denied

### Stage 4: Endpoint Regeneration & BPF Map Sync
**Location**: `pkg/endpoint/`, `daemon/cmd/endpoint.go`

- **Endpoint Policy Update Trigger**:
  - When policy is added/removed, affected endpoints are queued for regeneration
  - `Daemon.regenerateEndpoint()`: Updates single endpoint
  - `Daemon.datapathRegen()`: Batches multiple endpoint regenerations

- **Endpoint Regeneration Steps**:
  - Recalculate policy for endpoint (based on pod labels)
  - Regenerate BPF programs with new policies
  - Update BPF maps (policy_map, ipcache_map)
  - Reload TC/XDP programs on pod veth interface

- **BPF Map Update**:
  - `pkg/endpoint/bpf.go`: Synchronizes endpoint policy to BPF maps
  - `MapState` from repository is written to kernel BPF maps
  - Maps include: `policy_map` (policy decisions), `ipcache_map` (IP→identity)

### Stage 5: Datapath BPF Enforcement
**Location**: `pkg/datapath/loader/`, `bpf/` directory

- **BPF Program Compilation**:
  - `loader/compile.go`: Compiles C BPF programs
  - Template variables injected: policy decisions, endpoint config
  - Compiles per-endpoint BPF programs with inlined policy

- **BPF Program Loading**:
  - `loader/loader.go`: Loads compiled BPF to kernel
  - Attaches TC programs to veth interfaces
  - Attaches XDP programs for pre-filtering (optional)

- **Policy Enforcement**:
  - BPF programs check packet against policy_map
  - Decisions: `ALLOW`, `DENY`, `REDIRECT` (to proxy)
  - L7 proxying (HTTP, DNS, Kafka) for advanced filtering

### Data Flow Summary
```
CiliumNetworkPolicy CRD
    ↓ (K8s Watcher)
Policy Discovery & Cache (pkg/policy/k8s/)
    ↓ (Triggered by update)
Policy Repository Resolution (pkg/policy/)
    ↓ (Affects matching endpoints)
Endpoint Regeneration Queue (pkg/endpoint/)
    ↓ (For each endpoint)
BPF Map State Calculation (MapState)
    ↓ (Sync to kernel)
BPF Maps (policy_map, ipcache_map, ...)
    ↓ (Runtime lookup)
BPF Programs (on veth TC hook)
    → Packet ALLOW/DENY/REDIRECT decision
```

---

## 6. Adding a New Network Policy Type

To add a new type of network policy rule (e.g., a new L7 protocol filter), these packages need modification:

### Step 1: Define the Policy API Type
**File**: `pkg/policy/api/rule.go` or new `pkg/policy/api/l7_myprotocol.go`

```go
type MyProtocolRule struct {
    // Fields for L7 filter matching
    Port         *uint16
    Path         *string
    Method       *string
    // ... add kubebuilder tags for CRD validation
}
```

Add to existing L7Rule union or create new IngressRule type.

### Step 2: Create/Update CRD Type Definition
**File**: `pkg/k8s/apis/cilium.io/v2/cnp_types.go` or new file

- Ensure the Rule type includes your new filter type
- Add kubebuilder validation markers
- Generate CRD schema via `make generate`

### Step 3: Implement Policy Resolution Logic
**Files**: `pkg/policy/rule.go`, `pkg/policy/l4.go`

- Implement matching logic: `func (r *MyProtocolRule) Matches(...) bool`
- Convert rule to internal representation
- Handle selector matching and identity resolution
- Update `distillery.go` if MapState needs to represent the filter

### Step 4: Add BPF Map Support (if needed)
**Files**: `pkg/maps/`, `bpf/`

- If filter needs kernel support, define new BPF map structure
- Example: `policy_map` entry format might need new fields
- Update BPF programs to read/interpret new map fields

### Step 5: Implement Proxy Filter (if L7)
**Files**: `pkg/proxy/`, `pkg/envoy/` (for HTTP/Kafka/etc.)

- L7 filters typically offload to userspace proxy (Envoy, built-in DNS)
- Implement filter in proxy that understands your protocol
- Example: `/workspace/pkg/proxy/` has built-in DNS proxy logic

### Step 6: Add Endpoint Regeneration Support
**File**: `pkg/endpoint/regeneration/`

- Ensure endpoint regeneration includes your filter
- May need custom regeneration logic if filter has special requirements
- Update BPF program templates to include filter

### Step 7: Update Policy Watcher
**File**: `pkg/policy/k8s/cilium_network_policy.go`

- Add any special handling in `onUpsert()` if needed
- Example: Some filters require additional resource tracking

### Step 8: Add Test Coverage
**Files**: `pkg/policy/*_test.go`, `daemon/cmd/policy_test.go`

- Unit tests for matching logic
- Integration tests for endpoint regeneration
- Control plane tests for K8s resource handling

### Step 9: Documentation
- Update CRD examples in `/workspace/examples/`
- Document the new filter in `/workspace/Documentation/`

### Minimal Example: Adding IP Protocol Filter

1. **API definition** (`pkg/policy/api/rule.go`):
   ```go
   type IPProtocolFilter struct {
       Protocol uint8 // e.g., 6=TCP, 17=UDP
   }
   ```

2. **Resolution logic** (`pkg/policy/rule.go`):
   ```go
   func (f *IPProtocolFilter) Matches(protocol uint8) bool {
       return f.Protocol == protocol
   }
   ```

3. **BPF integration** (`bpf/`):
   - BPF program already has access to IP protocol field
   - Policy map lookup returns list of allowed protocols

4. **Test** (`pkg/policy/rule_test.go`):
   ```go
   func TestIPProtocolFilter_Matches(t *testing.T) {
       f := &IPProtocolFilter{Protocol: 6}
       assert.True(t, f.Matches(6))
       assert.False(t, f.Matches(17))
   }
   ```

### Architecture Considerations

- **Backward compatibility**: Ensure old policies still work with new filter type
- **Performance**: Filters that need kernel support should be inlined in BPF
- **Proxy support**: L7 filters may need userspace proxy (Envoy) integration
- **Test coverage**: Add tests at each layer (API, resolution, BPF, E2E)
- **Documentation**: Update examples and API documentation

The key insight is that Cilium's architecture cleanly separates policy definition (API), resolution (repository), endpoint application (regeneration), and kernel enforcement (BPF). Adding a new type involves implementing the appropriate logic at each layer.
