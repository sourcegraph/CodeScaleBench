# Cilium eBPF Fault Isolation

This investigation explores how Cilium's architecture ensures that eBPF program failures on one Kubernetes node remain isolated and do not propagate to other nodes in the cluster.

## Q1: Per-Node eBPF Lifecycle

### How are eBPF programs compiled, loaded, and attached on each node independently?

**Component Responsible for Compilation:**
The **loader** component (`pkg/datapath/loader/loader.go:74-116`) is the central orchestrator. Each Cilium agent instance runs its own loader with exclusive control over compilation and loading:
- `pkg/datapath/loader/compile.go:170-244` - The `compile()` function invokes `clang` locally on each node
- `pkg/datapath/loader/base.go:63-75` - `writeNodeConfigHeader()` writes node-specific configuration to headers before compilation
- `daemon/cmd/daemon.go:128` - Each daemon instance holds a `loader datapath.Loader` field

**Node-Specific Configuration and Compilation:**
Each node's compiler receives node-local configuration via `LocalNodeConfiguration` (from `pkg/datapath/types/node.go:30`), which includes:
- Node IPv4/IPv6 addresses
- Enabled features (IPv4, IPv6, masquerading, etc.)
- Device list
- Network configuration specific to that node

The compilation process probes the kernel for supported BPF features:
- `pkg/datapath/loader/compile.go:135-157` - `getBPFCPU()` probes for v3/v2 ISA support using `probes.HaveV3ISA()`, `probes.HaveV2ISA()`, and `probes.HaveProgramHelper()`
- `pkg/datapath/loader/compile.go:191-192` - CPU version is passed to clang as `-mcpu=<v1|v2|v3>`, making bytecode kernel-version specific

**Template-Based Compilation:**
Cilium uses a template-based approach to reduce per-node compilation overhead:
- `pkg/datapath/loader/template.go:64-146` - Templates with dummy values are compiled once per architecture
- `pkg/datapath/loader/template.go:148-175` - `ELFMapSubstitutions()` and `ELFVariableSubstitutions()` apply node-specific variable values to the compiled ELF at **load time** (not compile time) via binary rewriting

**When Does It Become Node-Local:**
- **Compile time** (not node-local yet): Template eBPF source code is compiled with generic values
- **Load time** (becomes node-local): Binary substitutions embed node-specific values:
  - Interface MAC addresses (lines 185-193 of `loader.go`)
  - Node IP addresses for masquerading (lines 207-217)
  - Interface indices (`interface_ifindex`, line 205)
- **Attach time** (fully node-local): Programs are attached to node-local interfaces and maps via `pkg/datapath/loader/tc.go` (TC), `xdp.go` (XDP), etc.

## Q2: Deployment Architecture

### How does Cilium's deployment model ensure per-node isolation?

**Deployment Model: DaemonSet**
Each Cilium node runs an independent agent pod via a Kubernetes DaemonSet:
- `daemon/cmd/daemon_main.go:1636-1645` - `newDaemonPromise()` creates a new daemon per node
- Each daemon runs independently in its own pod on each node
- `daemon/cmd/daemon.go:92-150` - The `Daemon` struct holds per-node state: loader, policy repository, endpoint manager, etc.

**Per-Node Failure Isolation:**
When a node's agent fails to compile/load eBPF programs:
- **Compilation failure** (`pkg/datapath/loader/compile.go:217-243`): Errors are logged locally; if the context is cancelled, the error is joined with `context.Canceled`
- **Load failure**: The node's agent enters degraded mode or restarts; other nodes' agents continue normally
- **No cluster-wide state dependency**: Each node's loader is independent (see `pkg/datapath/loader/loader.go:106-116` - each node has its own `*loader` instance)

**Control Plane vs Data Plane Split:**
- **Control Plane** (API Server): Cluster-wide state (policies, services) is centralized
- **Data Plane** (eBPF, per-node): Each node independently translates control plane policies into local eBPF bytecode and manages kernel state
  - `daemon/cmd/daemon.go:100` - Each daemon has its own `policy policy.PolicyRepository`
  - `daemon/cmd/daemon.go:139` - Each daemon has its own `endpointManager endpointmanager.EndpointManager`

**Datapath Initialization Lock:**
- `pkg/endpoint/bpf.go:392-398` - Before regenerating an endpoint's eBPF, the endpoint waits for the node's datapath to be initialized, then acquires the compilation read lock
- `daemon/cmd/daemon.go:121` - `compilationLock datapath.CompilationLock` ensures only one node compiles at a time (local to the node)
- This prevents node A's compilation from affecting node B

## Q3: Policy Distribution vs. Enforcement

### How do cluster-wide policies become per-node eBPF programs?

**Policy Distribution: Cluster-Wide Resources**
CiliumNetworkPolicy resources are Kubernetes CRDs stored in etcd:
- Multiple nodes watch and receive the same policy resources via Kubernetes API server watchers
- `daemon/cmd/daemon.go:56` - Each daemon has `k8sWatcher *watchers.K8sWatcher`

**Per-Node Policy Translation:**
Each node independently resolves policies to endpoint-specific eBPF:
1. **Policy Repository** (`pkg/policy/repository.go:1-151`):
   - `daemon/cmd/daemon.go:100` holds `policy policy.PolicyRepository`
   - Each node maintains its own repository via `pkg/policy/repository.go:130-151` - the `PolicyRepository` interface

2. **Endpoint Policy Calculation** (`pkg/endpoint/policy.go:219-225`):
   - For each endpoint on a node, `GetSelectorPolicy()` is called with the node's local policy repository
   - Policy is resolved **per-node, per-endpoint** - no cross-node policy sharing

3. **eBPF Translation** (`pkg/endpoint/bpf.go:100-155`):
   - `writeEndpointConfig()` translates policy into endpoint-specific C header files
   - `pkg/datapath/linux/config/config.go:1045-1056` - Maps endpoint policies to eBPF map references (e.g., `cilium_policy_v2_<endpoint-id>`)

**Why One Node's Failure Doesn't Block Other Nodes:**
- If node A's policy compilation fails:
  - `pkg/datapath/loader/compile.go:232-236` - Error is logged locally
  - `pkg/endpoint/bpf.go:625-628` - The endpoint regeneration fails on node A only
  - Nodes B, C, D have independent policy repositories and loaders; they continue translating policies without waiting for node A

- Each node independently owns the decision to apply policies via its own loader (`pkg/datapath/loader/loader.go:382-399` - `Reinitialize()`)

## Q4: eBPF Map Scoping and State Isolation

### How is map state isolated across nodes?

**Map Naming and Node Isolation:**
eBPF maps use node-local naming with endpoint IDs:
- Template map name: `cilium_policy_v2_<template-id>` (where template-id = 65535)
- Per-endpoint map name: `cilium_policy_v2_<endpoint-id>` (using actual endpoint ID 1-65534)
- Substitution happens in `pkg/datapath/loader/template.go:162-175`:
  - `ELFMapSubstitutions()` replaces template map names with actual endpoint-specific names
  - Example: `cilium_policy_v2_65535` → `cilium_policy_v2_1042`

**BPFfs Pinning: Node-Local Hierarchies**
Maps are persisted to the BPF filesystem (bpffs) with strict node-local paths:
- `pkg/datapath/loader/paths.go:48-75` - Path hierarchy:
  ```
  /sys/fs/bpf/cilium/endpoints/<endpoint-id>/
  /sys/fs/bpf/cilium/devices/<device-name>/
  ```
- Each node has its own `/sys/fs/bpf/cilium` mount (not shared across nodes in Kubernetes)

**Map Load and Pinning** (`pkg/bpf/pinning.go:23-139`):
- `pkg/bpf/pinning.go:43-73` - `incompatibleMaps()` checks for existing pinned maps and validates compatibility
- `pkg/bpf/pinning.go:126-139` - `commitMapPins()` unpins old maps and replaces with new ones atomically
- Maps are pinned by name and endpoint ID, ensuring node isolation via filesystem paths

**Node-Local vs. Cluster-Wide Maps:**
- **Node-local maps** (per-endpoint, per-device):
  - Policy maps: `cilium_policy_v2_<endpoint-id>` (one per endpoint per node)
  - CT maps: `cilium_ct_tcp4_<endpoint-id>`, `cilium_ct_any4_<endpoint-id>` (from `pkg/maps/ctmap/ctmap.go:820-829`)
  - Calls maps: `cilium_calls_<endpoint-id>` (from `pkg/endpoint/bpf.go:87-94`)

- **Cluster-wide maps** (shared by all nodes, pinned globally):
  - `cilium_ipcache` - IP identity cache (read-only by endpoint eBPF)
  - `cilium_node_map` - Node metadata (read-only)
  - `cilium_lb_services_v2` - Load balancer state (read-only by endpoint eBPF)

**Failure Isolation in Maps:**
If node A fails to create or update a map:
- `pkg/endpoint/bpf.go:437-443` - Writing to endpoint map (`lxcmap.WriteEndpoint()`) is local to the node
- If write fails: Only the affected endpoint on node A is impacted
- Node B's `lxcmap.WriteEndpoint()` call continues independently; it uses node B's map instances via `pkg/maps/lxcmap` (each node has its own inode)

The key isolation mechanism is the **bpffs pinning path**, which is mounted per-node. In Kubernetes:
- Each node's `/sys/fs/bpf` is local to that node's filesystem
- Node A's `/sys/fs/bpf/cilium/endpoints/1042/` is not visible to node B
- Even if maps have identical names, they exist in separate bpffs instances

---

## Evidence

### Q1: Per-Node eBPF Lifecycle
- `pkg/datapath/loader/loader.go:74-116` - loader struct with templateCache for pre-compiled programs
- `pkg/datapath/loader/compile.go:170-244` - compile() function with clang invocation
- `pkg/datapath/loader/compile.go:135-157` - getBPFCPU() probes kernel for feature support
- `pkg/datapath/loader/template.go:64-146` - templateCfg wraps configurations for ELF rewriting
- `pkg/datapath/loader/loader.go:176-224` - hostRewrites() applies node-specific variable substitutions
- `pkg/datapath/types/node.go:30` - LocalNodeConfiguration struct
- `daemon/cmd/daemon.go:128` - loader field in Daemon struct

### Q2: Deployment Architecture
- `daemon/cmd/daemon.go:92-150` - Daemon struct with per-node state
- `daemon/cmd/daemon_main.go:1636-1645` - newDaemonPromise() creates independent daemon instances
- `daemon/cmd/daemon.go:100` - policy field (PolicyRepository) per daemon
- `daemon/cmd/daemon.go:121` - compilationLock for per-node synchronization
- `daemon/cmd/daemon.go:139` - endpointManager per daemon
- `pkg/endpoint/bpf.go:392-398` - DatapathInitialized() wait and compilation lock acquire

### Q3: Policy Distribution vs. Enforcement
- `pkg/policy/repository.go:130-151` - PolicyRepository interface
- `daemon/cmd/daemon.go:100` - Each daemon has its own policy repository
- `daemon/cmd/daemon.go:56` - k8sWatcher (per-daemon API server watcher)
- `pkg/endpoint/policy.go:219-225` - GetSelectorPolicy() called with node's repository
- `pkg/datapath/linux/config/config.go:1045-1056` - WriteEndpointConfig() maps policies to eBPF defines
- `pkg/datapath/loader/compile.go:232-236` - Compilation error logging (per-node)
- `pkg/endpoint/bpf.go:625-628` - Endpoint regeneration failure (per-node)

### Q4: eBPF Map Scoping and State Isolation
- `pkg/datapath/loader/template.go:162-175` - ELFMapSubstitutions() for map name rewriting
- `pkg/datapath/loader/paths.go:48-75` - bpffs path hierarchy (node-local directories)
- `pkg/bpf/pinning.go:43-73` - incompatibleMaps() for map validation
- `pkg/bpf/pinning.go:126-139` - commitMapPins() for pinning replacement
- `pkg/maps/ctmap/ctmap.go:820-829` - CT maps with endpoint IDs
- `pkg/endpoint/bpf.go:87-94` - callsMapPath() returns node-local path
- `pkg/endpoint/bpf.go:437-443` - lxcmap.WriteEndpoint() per-endpoint operation
- `pkg/maps/policymap/policymap.go:31-34` - MapName prefix with endpoint-specific suffix
- `bpf/include/linux/bpf.h:5063-5066` - BPF map lifecycle tied to pinning
