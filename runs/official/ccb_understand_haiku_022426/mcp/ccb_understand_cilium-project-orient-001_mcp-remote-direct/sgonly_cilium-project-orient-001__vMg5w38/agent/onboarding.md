# Cilium Codebase Orientation

## 1. Main Entry Point

The cilium-agent binary starts execution through the following flow:

**Entry point:** `daemon/main.go:main()`
```go
func main() {
    agentHive := hive.New(cmd.Agent)
    cmd.Execute(cmd.NewAgentCmd(agentHive))
}
```

**Key Components:**

1. **Hive Dependency Injection Framework:** Cilium uses the Hive framework (github.com/cilium/hive) for dependency injection and component lifecycle management. The `hive.New(cmd.Agent)` creates a Hive instance with the Agent module.

2. **CLI Framework:** The agent uses Cobra (github.com/spf13/cobra) for command-line interface. The `cmd.NewAgentCmd()` creates a cobra.Command that handles the main agent execution flow.

3. **Configuration Loading:** Configuration is loaded through Viper (github.com/spf13/viper) in the OnInitialize hook at `daemon/cmd/root.go:65-75`, which calls:
   - `option.InitConfig()` - loads config from file or environment
   - `initDaemonConfig()` - applies daemon-specific config
   - `initLogging()` - sets up logging

4. **Main Hive Execution:** After initialization, `h.Run(logging.DefaultSlogLogger)` at `daemon/cmd/root.go:40` starts the Hive, which:
   - Instantiates all registered cells
   - Resolves dependencies
   - Starts all components in dependency order

**Agent Module Structure:** The Agent module is defined in `daemon/cmd/cells.go` and is composed of three main layers:

- **Infrastructure Module** (`daemon/cmd/cells.go:75-126`): Handles external services (Kubernetes client, metrics, pprof, gops)
- **ControlPlane Module** (`daemon/cmd/cells.go:132-330`): Core control logic (endpoints, policies, services, proxy, etc.)
- **Datapath Cell** (`daemon/cmd/cells.go:69`): Handles eBPF and kernel datapath integration

---

## 2. Core Packages

### 1. `pkg/endpoint/` - Endpoint Management
**Responsibility:** Manages individual endpoints (containers/pods/VMs) and their lifecycle
- **Key Files:**
  - `endpoint.go` - Defines the Endpoint struct with policy, identity, and BPF state
  - `policy.go` - Handles endpoint policy computation and synchronization
  - `bpf.go` - Manages endpoint BPF program management and policy map synchronization
  - `regenerator.go` - Orchestrates endpoint regeneration (rebuild BPF programs)
- **Key Interfaces:** EndpointManager manages collections of endpoints
- **Key Methods:**
  - `regeneratePolicy()` - Computes desired policy for an endpoint
  - `syncPolicyMaps()` - Syncs policy to eBPF policy maps

### 2. `pkg/policy/` - Network Policy Engine
**Responsibility:** Parses, stores, resolves, and distributes network policies
- **Key Files:**
  - `repository.go` - Central policy repository, stores all rules
  - `resolve.go` - Policy resolution algorithm (matches packets to rules)
  - `l4.go` - L4 policy structures (port/protocol based rules)
  - `rule.go` - Individual policy rule representation
  - `api/` - CRD API types for CiliumNetworkPolicy, ClusterwideCiliumNetworkPolicy
- **Key Interfaces:** PolicyContext, Repository
- **Key Methods:**
  - `Repository.AddListLocked()` - Add rules to repository
  - `Repository.Resolve()` - Resolve policy for a specific identity
  - `NewEndpointPolicy()` - Create endpoint-specific policy

### 3. `pkg/policy/k8s/` - Kubernetes Policy Watcher
**Responsibility:** Watches Kubernetes policy CRDs and translates them to internal policy rules
- **Key Files:**
  - `watcher.go` - Main policy watcher that watches K8s resources
  - `cilium_network_policy.go` - Handles CiliumNetworkPolicy (CNP) CR events
  - `network_policy.go` - Handles standard Kubernetes NetworkPolicy
  - `cilium_cidr_group.go` - Handles CiliumCIDRGroup references
  - `service.go` - Resolves ToServices rules to CIDR rules
- **Key Flow:** Watch resources → Parse rules → Add to Repository → Trigger endpoint regeneration

### 4. `pkg/k8s/` - Kubernetes Integration
**Responsibility:** Manages all Kubernetes integrations (client, watchers, resources)
- **Key Files:**
  - `k8s.go` - Kubernetes client initialization
  - `watchers/` - Event watchers for K8s resources (pods, services, namespaces, etc.)
  - `resource/` - SharedResourceLister integration for resource watching
- **Key Components:**
  - Pod watcher - Detects pod creation/deletion/label changes
  - Service watcher - Tracks Kubernetes services
  - Node watcher - Monitors node state

### 5. `pkg/datapath/` - Datapath and eBPF Integration
**Responsibility:** Manages the kernel-facing datapath, eBPF programs, and BPF maps
- **Key Subdirectories:**
  - `linux/` - Linux-specific datapath implementation (routing, eBPF compilation)
  - `maps/` - BPF map management (policy maps, CT maps, NAT maps, etc.)
  - `loader/` - eBPF program compilation and loading
  - `ipcache/` - Identity/CIDR to security identity mapping
- **Key Interfaces:** Datapath, DatapathConfiguration
- **Key Maps:** PolicyMap (enforces policy at packet level), ConntrackMap (tracks connections)

### 6. `pkg/identity/` - Identity Management
**Responsibility:** Manages security identities (labels → identity mapping) for endpoints and external entities
- **Key Concepts:**
  - Security identities uniquely identify workloads based on labels
  - Used for policy lookups and enforcement
  - Can be allocated from local KVStore or etcd (depending on mode)
- **Key Files:** `identity.go`, `allocator.go`

### 7. `pkg/endpointmanager/` - Endpoint Collection
**Responsibility:** Manages the collection of all endpoints on a node
- **Key Methods:**
  - `AddEndpoint()` - Register new endpoint
  - `RemoveEndpoint()` - Unregister endpoint
  - `RegenerateAllEndpoints()` - Trigger regeneration for all/affected endpoints
  - `GetEndpoint()` - Lookup endpoint by ID

---

## 3. Configuration Loading

Cilium loads configuration through a multi-step pipeline:

### Configuration Pipeline:

**Step 1: File/Environment Loading (`daemon/cmd/root.go:67`)**
```go
option.InitConfig(rootCmd, "cilium-agent", "cilium", h.Viper())
```
- Loads from YAML config file (default: `/etc/cilium/cilium.yaml`)
- Reads environment variables with `CILIUM_` prefix
- Uses Viper for configuration binding

**Step 2: Daemon Config Initialization (`daemon/cmd/root.go:72`)**
```go
initDaemonConfig(h.Viper())
```
- Populates the global `option.Config` struct with loaded values
- Validates configuration values
- Initializes derived configuration fields

**Step 3: Config Struct (`pkg/option/config.go:1401`)**
```go
type DaemonConfig struct {
    // Core settings
    BpfDir              string
    RunDir              string
    StateDir            string
    DatapathMode        string
    RoutingMode         string

    // Policy enforcement
    Opts *IntOptions    // Runtime-changeable options

    // Networking
    EnableIPv4          bool
    EnableIPv6          bool
    MTU                 int
    RoutingMode         string  // "native" or "tunnel"

    // BPF Maps sizing
    CTMapEntriesGlobalTCP  int
    CTMapEntriesGlobalAny  int
    NATMapEntriesGlobal    int
    PolicyMapEntries       int

    // ... 200+ more configuration fields
}
```

**Supported Config Formats:**
- YAML configuration files
- Environment variables (`CILIUM_*` prefix)
- Command-line flags (via Cobra)
- ConfigMap entries (in Kubernetes mode)

**Configuration Binding Library:** Viper handles all configuration source merging and precedence

**Hive Integration:** Configuration is exposed to all cells via dependency injection:
```go
cell.Provide(func() *option.DaemonConfig { return option.Config })
```

---

## 4. Test Structure

Cilium employs multiple testing approaches to ensure quality:

### 1. **Unit Tests** (Standard Go Tests)
- **Location:** `pkg/*_test.go`, `daemon/cmd/*_test.go`
- **Example:** `pkg/policy/repository_test.go`, `pkg/endpoint/policy_test.go`
- **Characteristics:**
  - Test individual functions and components in isolation
  - Use mocking and test helpers
  - Run quickly without special privileges
  - Test policy resolution, rule matching, label filtering, etc.
- **Run:** `go test ./pkg/policy/...`

### 2. **Privileged Tests**
- **Location:** `*_privileged_test.go` files (e.g., `daemon/cmd/daemon_privileged_test.go`)
- **Marker:** Functions call `testutils.PrivilegedTest(t)` at the start
- **Characteristics:**
  - Require elevated privileges (root/CAP_NET_ADMIN)
  - Test actual kernel interactions (netlink, BPF maps, network namespaces)
  - Create temporary network namespaces and test datapath
- **Example Use Cases:** Testing BPF map operations, network device configuration
- **Run:** `go test -run Privileged ./...` (requires root)

### 3. **Integration Tests** (Control Plane)
- **Location:** `test/controlplane/`
- **Framework:** Uses Ginkgo for test organization
- **Characteristics:**
  - Test the agent without privilege requirements
  - Mock Kubernetes API, datapath, and other external services
  - Test policy resolution, endpoint creation, identity allocation
  - Multi-step scenarios (pod creation → policy application → verification)
- **Example:** Tests that verify CiliumNetworkPolicy rules are correctly resolved for endpoints
- **Run:** `ginkgo ./test/controlplane/...`

### 4. **BPF Tests**
- **Location:** `test/bpf/`
- **Framework:** Custom BPF test framework
- **Characteristics:**
  - Test eBPF program correctness
  - Use the kernel's BPF verifier
  - Test packet processing, map operations, policy enforcement at the BPF level
  - May use test data packets and simulated network scenarios
- **Example:** Testing BPF CT map lookups, policy map enforcement logic

### 5. **End-to-End Tests**
- **Location:** `test/runtime/`, `test/k8s/`
- **Characteristics:**
  - Run against actual Kubernetes clusters (local or cloud)
  - Test full system behavior (policy application, connectivity, performance)
  - Slow and require significant resources
  - Verify real-world scenarios
- **Example Tests:** Policy enforcement on live pods, service load balancing, networking features
- **CI Integration:** Run in CI pipelines with provisioned Kubernetes clusters

### 6. **Fuzzing Tests**
- **Location:** `test/fuzzing/`
- **Framework:** Go's native fuzzing support
- **Characteristics:** Fuzz-test policy parsing, rule matching, and other critical components for robustness

---

## 5. Network Policy Pipeline

A CiliumNetworkPolicy flows through the following stages from CRD definition to eBPF enforcement:

### **Stage 1: CRD Definition and K8s Watcher**
- **File:** CiliumNetworkPolicy YAML in Kubernetes cluster
- **Type Definition:** `pkg/k8s/apis/cilium.io/v2/cnp_types.go` (CiliumNetworkPolicySpec)
- **Key Fields:** `IngressRules`, `EgressRules`, `EndpointSelector`, `Labels`
- **Component:** K8s API server stores the CRD
- **Trigger:** K8s watcher detects CREATE/UPDATE/DELETE events

**Files:**
- `pkg/policy/k8s/watcher.go` - Main watcher loop
- `pkg/policy/k8s/cilium_network_policy.go` - CNP-specific handling

### **Stage 2: Policy Parsing and Repository Import**
- **Process:**
  1. K8s watcher receives CNP event via shared informer
  2. Calls `policyWatcher.onUpsert()` → `resolveCiliumNetworkPolicyRefs()` in `pkg/policy/k8s/cilium_network_policy.go:113`
  3. Resolves external references (CiliumCIDRGroups, ToServices) to inline rules
  4. Calls `policyManager.PolicyAdd(rules, opts)` in `daemon/cmd/policy.go:265`
  5. Policy repository (pkg/policy/repository.go) adds rules with `AddListLocked()`

- **Output:** Policy rules now in the central `Repository` with unique revision number
- **Reference:** `daemon/cmd/daemon_main.go:1670` - `Policy *policy.Repository` is the central store

### **Stage 3: Endpoint Policy Calculation**
- **Trigger:** When rules are added to repository, endpoints need regeneration
- **Process:**
  1. Policy change triggers `endpointManager.RegenerateAllEndpoints()` call
  2. For each endpoint, `regeneratePolicy()` is called in `pkg/endpoint/policy.go:200`
  3. Endpoint computes its desired policy by:
     - Matching endpoint's labels against rule selectors
     - Resolving policy for endpoint's security identity
     - Computing L3/L4 policy map entries
     - Computing L7 proxy rules

- **Component:** `pkg/endpoint/policy.go` - `regeneratePolicy()` method
- **Output:** `EndpointPolicy` struct with computed allow/deny rules

### **Stage 4: BPF Map Synchronization**
- **Process:**
  1. After policy computation, endpoint regenerates BPF programs in `pkg/endpoint/bpf.go:regenerate()`
  2. Calls `syncPolicyMaps()` in `pkg/endpoint/bpf.go:1348`
  3. Translates endpoint policy to BPF map format:
     - **Source/Dest Key:** Security identity + port/protocol
     - **Map Entry:** Allow/Deny/Redirect decision
  4. Updates BPF policy map (per-endpoint map) via `policymap.UpdatePolicyMaps()`
  5. Updates global maps: CT maps, NAT maps, etc.

- **BPF Maps:**
  - Per-endpoint policy map in `pkg/maps/policymap/policymap.go`
  - Global CT map (connection tracking) in `pkg/maps/ctmap/`
  - Global NAT map in `pkg/maps/nat/`

- **Reference:** `pkg/endpoint/bpf.go:916-920` - Endpoint syncs policy maps after BPF program regeneration

### **Stage 5: Runtime Enforcement**
- **Kernel eBPF Execution:**
  1. Incoming packet hits cilium_host or cilium_veth program
  2. Program performs identity lookup via `ipcache` map (IP → security identity)
  3. Looks up policy entry in endpoint's policy map using (source_id, dest_id, port, protocol)
  4. Returns verdict: ALLOW, DENY, or REDIRECT (for proxy)
  5. Packet is forwarded, dropped, or redirected to proxy accordingly

- **Components:**
  - `pkg/datapath/ipcache/` - Identity cache map
  - `pkg/maps/policymap/` - Policy decision map
  - BPF programs in `bpf/` directory

---

## 6. Adding a New Network Policy Type

To add support for a new L7 protocol filter (e.g., a new protocol like "custom-proto"):

### **Step 1: Define the L7 Rule Type**
- **File:** `pkg/policy/api/rules.go` or `pkg/policy/api/l7.go`
- **Action:** Create a new struct for the L7 rule:
  ```go
  type CustomProtoRule struct {
    // Define rule fields (e.g., methods, headers, etc.)
    Methods []string `json:"methods,omitempty"`
  }

  type PortRuleL7 struct {
    CustomProto *CustomProtoRule `json:"customProto,omitempty"`
  }
  ```
- **Reference:** See existing examples: `HTTPRule`, `DNSRule`, `TLSRule` in the same file

### **Step 2: Update Policy Rule Validation**
- **File:** `pkg/policy/api/rule_validation.go`
- **Action:** Add validation logic in `Sanitize()` method to validate rule fields
- **Ensure:**
  - Field type checking
  - Value range validation
  - Conflict detection (e.g., can't use custom-proto with certain other rules)

### **Step 3: Update L4 Policy Resolution**
- **File:** `pkg/policy/l4.go` and `pkg/policy/rule.go`
- **Action:** Extend L4 policy resolution to handle the new L7 rule type
  - In `createL4Filter()`, add case for the new protocol
  - Ensure L7 rule is stored in `L4Filter.L7Rules` field
  - Handle protocol-specific merge logic

### **Step 4: Implement Envoy Integration (if needed for proxy enforcement)**
- **File:** `pkg/envoy/xds_server.go`
- **Action:** If the protocol needs proxy enforcement:
  - Add protocol handler in `getL7Rules()` function (line 1030)
  - Translate rules to Envoy protobuf format
  - Create corresponding Envoy filter chain

- **Reference:** See `HTTP`, `DNS`, `gRPC` implementations

### **Step 5: Update BPF Enforcement**
- **File:** `bpf/lib/` (BPF header files) and `bpf/cilium/*.c` (BPF programs)
- **Action:** If policy enforcement happens in BPF (not via proxy):
  - Add BPF code to parse protocol headers
  - Implement rule matching logic
  - Return correct verdict (ALLOW/DROP/REDIRECT)

- **Reference:** Look at existing L3/L4 enforcement in `bpf/lib/policy.h`

### **Step 6: Add Tests**
- **Files to update:**
  - `pkg/policy/api/rules_test.go` - Test rule validation/sanitization
  - `pkg/policy/l4_test.go` - Test L4 policy resolution with new rule type
  - `pkg/envoy/xds_server_test.go` - Test Envoy translation (if applicable)
  - `test/controlplane/` - Integration test for full policy flow

- **Test Checklist:**
  - Rule parsing and validation
  - Policy resolution with new rules
  - Endpoint policy computation
  - BPF map synchronization
  - End-to-end policy enforcement

### **Step 7: Update CRD Definition** (if exposing via CiliumNetworkPolicy)
- **File:** `pkg/k8s/apis/cilium.io/v2/cnp_types.go`
- **Action:** Add new rule type to CiliumNetworkPolicy/EgressRule/IngressRule spec
- **Generate:** Run `make generate-k8s-api` to regenerate deepcopy, validation, and client code

### **Step 8: Update K8s Policy Watcher** (if needed for translation)
- **File:** `pkg/policy/k8s/cilium_network_policy.go`
- **Action:** If new rule type references external resources, add translation logic
- **Example:** If "ToServices" rules need expansion, add logic in `resolveToServices()`

### **Verification Sequence:**
1. Unit tests pass: `go test ./pkg/policy/api/... ./pkg/policy/...`
2. Control plane integration tests pass: `ginkgo ./test/controlplane/...`
3. Privileged tests pass (if BPF enforcement): `go test -run Privileged ./...`
4. End-to-end tests pass on real cluster: `test/k8s/` or `test/runtime/`

