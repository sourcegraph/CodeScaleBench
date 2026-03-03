# Cilium Codebase Orientation

## 1. Main Entry Point

### cilium-agent Binary Execution

The cilium-agent binary entry point is in **daemon/main.go**:

```go
func main() {
    agentHive := hive.New(cmd.Agent)
    cmd.Execute(cmd.NewAgentCmd(agentHive))
}
```

### Dependency Injection Framework: Hive

Cilium uses **Hive** (an external library wrapper at `pkg/hive/hive.go`) as its dependency injection framework. Hive is a modular dependency injection system that:

- Organizes code into **Cells** - reusable modules that provide dependencies and can depend on other cells
- Manages the lifecycle of components (start, run, stop)
- Supports configuration binding and provides automatic dependency resolution

### Agent Module Structure (daemon/cmd/cells.go)

The `cmd.Agent` is a cell module with three main sub-modules:

1. **Infrastructure Cell** (lines 75-126):
   - Provides low-level services (pprof, gops, metrics, K8s client)
   - Configuration and API server setup
   - CRD synchronization tracking

2. **ControlPlane Cell** (lines 128-270):
   - Control logic and business logic layer
   - Includes: LocalNode, EndpointManager, NodeManager, Policy, ServiceCache
   - K8s watchers for CiliumNetworkPolicy, NetworkPolicy, Services
   - PolicyK8s cell (watches and syncs K8s policies)
   - PolicyDirectory cell (watches policies from config files)

3. **Datapath Cell** (datapath.Cell):
   - Kernel-level networking with eBPF programs
   - BPF map management (lxcmap, policymap, ctmap, etc.)
   - Device and interface management

### CLI Command Structure

The daemon is initialized via `cmd.NewAgentCmd()` which creates the agent command using Cobra CLI framework.

---

## 2. Core Packages

### 1. **pkg/policy** - Policy Engine
- **Repository**: Core policy storage and management (`pkg/policy/repository.go`)
  - Maintains list of active Rules and their subject security identities
  - Provides SelectorCache (precomputed policy decisions)
  - Responsible for adding/deleting rules from the policy database
- **Rule Resolution**: Policy computation from endpoint labels and selectors (`pkg/policy/resolve.go`, `pkg/policy/l4.go`)
- **API Types**: L3/L4/L7 rule definitions (`pkg/policy/api/`)

### 2. **pkg/k8s/apis** - Kubernetes Integration
- **CRD Definitions**: CiliumNetworkPolicy, CiliumClusterwideNetworkPolicy, CiliumCIDRGroup
- **K8s Resource Watchers** (`pkg/k8s/watchers/`, `daemon/k8s/resources.go`)
  - Watches for K8s NetworkPolicy, Kubernetes Services, CiliumNetworkPolicy resources
  - Translates K8s CRDs into Cilium's internal policy format (api.Rules)

### 3. **pkg/endpoint** - Endpoint Management
- **Endpoint Lifecycle**: States like waiting-for-identity, regenerating, ready, disconnecting
- **Policy Calculation**: `regeneratePolicy()` computes policy for an endpoint based on repository rules
- **BPF Program Compilation**: Programs and maps for networking enforcement per endpoint
- **Endpoint Manager**: Maintains collection of locally running endpoints

### 4. **pkg/datapath** - Data Path / eBPF
- **Linux Datapath** (`pkg/datapath/linux/`):
  - BPF program compilation and loading
  - Map management (lxcmap, policymap, ctmap, etc.)
  - Device and interface handling
- **Loader** (`pkg/datapath/loader/`):
  - Loads compiled BPF programs to kernel hooks (ingress, egress)
  - Manages BPF map initialization
- **Maps** (`pkg/datapath/maps/`):
  - BPF map abstractions: lxcmap (endpoint metadata), policymap (policy decisions), ctmap (conntrack)

### 5. **pkg/ipam** - IP Address Management
- **IPAM Controller**: Manages IP allocation for endpoints
- **Metadata Manager** (`pkg/ipam/metadata/`): Tracks pod-to-IP associations
- **Multiple IPAM modes**: Kubernetes, EtcdOperator, CloudProvider-specific

### 6. **pkg/identity** - Identity Allocation
- **Identity Allocator**: Allocates unique identities for endpoint label combinations
- **Label-based Identity**: Each unique set of labels gets a numeric identity (1-16777215)
- **Stores identities in KVStore** (etcd or consul) for cluster-wide coordination

### 7. **pkg/maps** - BPF Map Management
- **lxcmap**: Endpoint metadata (IP, port, identity)
- **policymap**: Policy decisions (allow/deny/redirect per L4 protocol)
- **ctmap**: Connection tracking state
- **ipcache**: IP-to-Identity mapping cache (used for enforcement)

---

## 3. Configuration Loading

### Configuration Sources (in order of precedence)

Configuration is loaded through multiple sources, as defined in `pkg/option/config.go`:

1. **Command-line flags** - Highest precedence
2. **Configuration file** (--config, default: /etc/cilium/cilium.yaml)
3. **Configuration directory** (--config-dir, default: /etc/cilium/)
4. **Environment variables**
5. **Defaults** - Lowest precedence

### Configuration Framework

- **Library Used**: Viper (golang config binding library)
  - Integrated at `pkg/option/config.go` using `spf13/viper` and `spf13/pflag`
- **Flags Registration**: Done via Cobra commands with pflag integration

### DaemonConfig Struct

Location: `pkg/option/config.go:1400+`

The main configuration struct `DaemonConfig` contains:

- **BPF Settings**: `BpfDir`, `LibDir`, `RunDir`, `DatapathMode`, `RoutingMode`
- **Networking**: `HostV4Addr`, `HostV6Addr`, `IPv4Range`, `IPv6Range`, `MTU`, `DirectRoutingDevice`
- **Kubernetes**: `EnableK8s`, `K8sAPIServer`, `K8sKubeConfigPath`, `K8sServiceCacheSize`
- **Policy**: `EnablePolicy`, `PolicyTracing`, `PolicyVerdictNotify`
- **L7 Proxy**: `EnableL7Proxy`
- **Features**: `EnableXDPPrefilter`, `EnableNodePort`, `EnableServiceProxy`, `EnableHostPort`
- **Runtime Options** (`Opts *IntOptions`): Mutable options that can change at runtime

### Configuration Initialization Pipeline

1. **daemon/cmd/daemon.go**: `NewDaemon()` calls `option.Config.Validate()` and `option.Config.SetupLogging()`
2. **pkg/option/config.go**: `Validate()` performs validation and derives secondary values
3. **Hive cell** (daemon/cmd/cells.go): `cell.Provide(func() *option.DaemonConfig { return option.Config })`
   - Makes config available to all cells as a dependency

### Configuration Interfaces

- **Config Struct**: `pkg/option/config.go:DaemonConfig` - Main configuration object
- **Option Library**: `pkg/option/daemon.go` - Runtime mutable options
- **Validation**: `pkg/option/config.go:Validate()` - Comprehensive config validation

---

## 4. Test Structure

Cilium uses multiple testing approaches optimized for different levels:

### 1. **Unit Tests** (Standard Go Tests)
- Located alongside source code: `*_test.go` files
- Run with: `go test ./pkg/...`
- Example: `pkg/policy/repository_test.go`, `pkg/endpoint/endpoint_test.go`
- Non-privileged tests that don't require kernel capabilities

### 2. **Privileged Tests**
- Marked with `testutils.PrivilegedTest(tb)` (pkg/testutils/privileged.go)
- Require root or specific Linux capabilities
- Skipped by default, run with: `PRIVILEGED_TESTS=1 go test ./pkg/...`
- Test BPF program loading, network device manipulation, etc.
- Example: Tests that load BPF programs or manipulate kernel state

### 3. **Integration Tests**
- Marked with `testutils.IntegrationTest(tb)` (pkg/testutils/privileged.go)
- Run with: `INTEGRATION_TESTS=1 go test ./pkg/...`
- Test full subsystem interactions (e.g., daemon + endpoints + policy)
- Example: `daemon/cmd/daemon_test.go` - DaemonSuite, DaemonEtcdSuite

### 4. **BPF Unit and Integration Tests**
- Located in: `test/bpf/` and files like `bpf/tests/` directories
- Framework: BPF_PROG_RUN feature (in-kernel eBPF execution without attachment)
- Tests verify eBPF program logic independently
- Documentation: `Documentation/contributing/testing/bpf.rst`

### 5. **End-to-End (E2E) Tests**
- Located in: `test/` directory (test/k8s/, test/runtime/, test/controlplane/, etc.)
- Framework: Ginkgo (BDD testing framework) + test helpers
- Run full Cilium deployments in VMs or K8s clusters
- Tests: NetworkPolicy enforcement, service load balancing, DNS proxy, etc.
- Run with: `make integration-tests` or Ginkgo directly

### 6. **Test Utilities and Helpers**
- **pkg/testutils/**: Common testing utilities (privileged/integration detection)
- **test/helpers/**: E2E test framework (K8s manifests, CLI utilities, config)
- **test/ginkgo-ext/**: Ginkgo extensions for Cilium-specific testing

---

## 5. Network Policy Pipeline

The journey of a CiliumNetworkPolicy (CNP) from CRD definition to eBPF enforcement involves 4+ major stages:

### Stage 1: CRD Watch and Parsing
**Components**: `daemon/k8s/resources.go`, `pkg/policy/k8s/watcher.go`

```
CiliumNetworkPolicy CRD (K8s API Server)
    ↓ (K8s client watches)
PolicyWatcher (pkg/policy/k8s/watcher.go)
    ↓ (Parse CNP)
cilium_v2.CiliumNetworkPolicy object
```

- **Class**: `CiliumNetworkPolicy` defined in `pkg/k8s/apis/cilium.io/v2/cnp_types.go`
- **K8s Watcher**: Uses `resource.Resource[*cilium_v2.CiliumNetworkPolicy]` to watch API server
- **Parsing**: `cilium_v2.CiliumNetworkPolicy.Parse()` converts to internal `api.Rules`

### Stage 2: Policy Translation and Rule Addition
**Components**: `pkg/policy/k8s/cilium_network_policy.go`, `pkg/policy/repository.go`

```
api.Rules (Cilium internal format)
    ↓ (PolicyAdd)
PolicyRepository.AddRulesLocked()
    ↓ (Process selectors)
SelectorCache (precomputed policy decisions)
    ↓ (Update revision)
Policy revision incremented
```

- **Translation**: `resolveCiliumNetworkPolicyRefs()` handles policy references (e.g., CiliumCIDRGroups)
- **Source Tracking**: Rules are tagged with source (e.g., `source.CustomResource`)
- **SelectorCache**: Pre-computes which endpoints match which policy selectors for efficiency

### Stage 3: Endpoint Selection and Policy Regeneration
**Components**: `pkg/endpoint/policy.go`, `pkg/endpoint/endpoint.go`, `pkg/endpointmanager/`

```
Policy Revision Change (e.g., via policy trigger)
    ↓ (Policy Trigger in pkg/policy/trigger.go)
EndpointManager.RegenerateAllEndpoints(metadata)
    ↓ (For each affected endpoint)
Endpoint.Regenerate(regenMetadata)
    ↓ (State: StateWaitingToRegenerate)
Endpoint.regenerate() (worker pool)
    ↓ (State: StateRegenerating)
regeneratePolicy() - Recompute policy from repository
```

- **Policy Trigger**: Monitors policy repository changes and queues endpoint regenerations
- **Regeneration Levels**:
  - `RegenerateWithoutDatapath` - Policy-only changes (no BPF reload)
  - `RegenerateWithDatapath` - Policy + BPF program recompilation required
- **Endpoint State Machine**: Moves through: WaitingForIdentity → WaitingToRegenerate → Regenerating → Ready

### Stage 4: BPF Program Compilation and Map Synchronization
**Components**: `pkg/datapath/loader/`, `pkg/datapath/linux/`, `pkg/endpoint/bpf.go`

```
Endpoint.generateMapState()
    ↓ (Policy to map entries)
PolicyMap construction (Map[UID+Protocol → Action])
    ↓ (Compile BPF)
Loader.CompileOrLoad()
    ↓ (Write to kernel)
BPF programs loaded to TC ingress/egress + attached to veth
    ↓ (Update maps)
Maps updated:
  - lxcmap: Endpoint metadata
  - policymap: Policy decisions for this endpoint
  - ipcache: IP-to-Identity mapping
```

- **toMapState()** (pkg/policy/l4.go): Converts policy rules to BPF map entries
- **PolicyMap**: Stores decisions per (endpoint_id + protocol) → (action: allow/deny/redirect)
- **Map Synchronization**: `synchronizeProxyState()` ensures proxy redirects are set up
- **BPF Attachment**: Programs attached to veth interface ingress/egress hooks

### Stage 5: Enforcement in Data Path
**Location**: `bpf/` directory (eBPF C code)

The compiled BPF programs run on every packet:
1. **Ingress**: Check source identity against policy rules
2. **Egress**: Check destination identity/address against policy rules
3. **Decision**: Allow, deny, or redirect to proxy based on policymap lookup
4. **Counters**: Update metrics in maps for monitoring

### Full Policy Path Summary

```
CiliumNetworkPolicy CRD
    ↓ K8s Watcher (pkg/policy/k8s/)
    ↓ Parse & Translate (api.Rules)
    ↓ Add to Repository (pkg/policy/)
    ↓ Policy Trigger (pkg/policy/trigger.go)
    ↓ Select Affected Endpoints (via SelectorCache)
    ↓ Queue Endpoint Regeneration
    ↓ Regenerate Policy (pkg/endpoint/policy.go)
    ↓ Compile BPF Programs (pkg/datapath/loader/)
    ↓ Load to Kernel + Update Maps
    ↓ Enforce in Data Path (bpf/)
```

---

## 6. Adding a New Network Policy Type

To add a new L7 protocol filter (e.g., a new L7 protocol like "gRPC"), follow this sequence:

### Phase 1: API Layer - Define the New Rule Type

**File**: `pkg/policy/api/rule.go` (or similar)

1. Add a new struct for your protocol in the Cilium API types:
```go
type GRPCRule struct {
    Method string
    Service string
}

type Rule struct {
    // ... existing fields ...
    ToGRPC *[]GRPCRule
}
```

2. Update validation in `pkg/policy/api/rule_validation.go`:
```go
func (pr *PortRule) Validate() error {
    // Add validation for ToGRPC fields
}
```

### Phase 2: K8s CRD Integration

**File**: `pkg/k8s/apis/cilium.io/v2/cnp_types.go`

1. Update the CiliumNetworkPolicy OpenAPI/CRD spec to allow the new rule type:
```go
type Rule struct {
    // ... existing fields ...
    GRPC *GRPCRule `json:"grpc,omitempty"`
}
```

2. Update the parsing in `Parse()` method:
```go
func (cnp *CiliumNetworkPolicy) Parse() (api.Rules, error) {
    // Parse GRPC rules and convert to internal format
}
```

### Phase 3: Policy Resolver - Compute What Applies

**File**: `pkg/policy/resolve.go` and `pkg/policy/l4.go`

1. Update the policy resolver to handle the new rule type:
```go
func (l4policy L4DirectionPolicy) toMapState(p *EndpointPolicy) {
    // Add handling for GRPC rules
    // Translate to policymap entries
}
```

2. Create a filter implementation in `pkg/policy/l4.go`:
```go
type L7Rule struct {
    // ... existing L7 types ...
    GRPCRules []GRPCRule
}
```

### Phase 4: Envoy Proxy Integration (L7 Enforcement)

**File**: `pkg/envoy/` or `pkg/proxy/`

1. Update L7 proxy handler if needed for your protocol
2. Generate Envoy configuration for the new protocol (if needed)
3. **File**: `pkg/ciliumenvoyconfig/` - Configuration generation

### Phase 5: Endpoint BPF Program Updates

**File**: `bpf/` directory (C code)

1. Update BPF programs to recognize the new L7 protocol:
   - `bpf/lib/lb.h` - Load balancing policies
   - `bpf/lib/policy.h` - Policy enforcement

2. If protocol requires deep packet inspection (DPI), add DPI code to recognize your protocol

3. If protocol requires redirection to Envoy proxy, ensure proxy redirect logic works

### Phase 6: Testing

1. **Unit Tests**: Add tests in `pkg/policy/api/rule_validation_test.go`
2. **Policy Resolver Tests**: `pkg/policy/resolve_test.go`, `pkg/policy/l4_test.go`
3. **Integration Tests**: `daemon/cmd/daemon_test.go` - Test with actual endpoints
4. **BPF Tests**: `test/bpf/` - Test BPF program compilation and execution
5. **E2E Tests**: `test/k8s/` - Full Cilium deployment tests

### Example Files to Modify (in Order)

| Phase | Files |
|-------|-------|
| 1. API | `pkg/policy/api/rule.go`, `pkg/policy/api/rule_validation.go` |
| 2. K8s | `pkg/k8s/apis/cilium.io/v2/cnp_types.go`, `pkg/policy/k8s/cilium_network_policy.go` |
| 3. Resolve | `pkg/policy/resolve.go`, `pkg/policy/l4.go` |
| 4. Proxy | `pkg/ciliumenvoyconfig/`, `pkg/envoy/` |
| 5. BPF | `bpf/lib/policy.h`, `bpf/lib/lb.h`, `bpf/` programs |
| 6. Tests | `*_test.go` files, `test/bpf/`, `test/k8s/` |

### Documentation

- Update CRD documentation: `Documentation/network/policy/`
- Add examples: `Documentation/policy/l7/` (for L7-specific rules)
- Update API docs (auto-generated from CRD)

---

## Key Architectural Patterns

1. **Hive Dependency Injection**: All major components are cells in the Hive module system
2. **Event-Driven Regeneration**: Policy changes trigger endpoint regenerations via triggers
3. **Kernel-User Space Separation**: User-space manages policy logic, kernel (eBPF) enforces it
4. **Identity-Based Segmentation**: Cilium assigns numeric identities to label sets, uses identities for fast policy decisions
5. **BPF Maps as State Store**: Runtime state (endpoints, policies) stored in kernel BPF maps, synchronized from user-space

---
