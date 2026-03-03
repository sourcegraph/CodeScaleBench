# Cilium eBPF Fault Isolation

## Q1: Per-Node eBPF Lifecycle

### Compilation Phase

eBPF programs are compiled **independently on each node** with node-specific configuration:

- **Compilation Location**: `pkg/datapath/loader/compile.go:170-257` - The `compile()` function runs the Clang compiler with node-specific CPU probe results (`getBPFCPU()` at line 134-157)
- **Kernel Version Detection**: `pkg/datapath/loader/compile.go:143-154` - At runtime, each node probes its kernel to determine BPF instruction set support (v1, v2, or v3), affecting which version of compiled bytecode is produced
- **Per-Node Configuration Headers**:
  - `pkg/datapath/loader/base.go:63-75` - `writeNodeConfigHeader()` writes node-specific configuration (IP addresses, device info) to `${StateDir}/node_config.h`
  - Each node generates its own headers in `pkg/datapath/loader/base.go:46-61` - `writeNetdevHeader()` creates device-specific configuration based on local network interfaces

### Loading and Attachment Phase

Compilation output is **loaded and attached locally** on each node:

- **Per-Node Load Paths**: `pkg/datapath/loader/loader.go:700-732` - `ReloadDatapath()` compiles and loads eBPF programs into the **endpoint-specific state directory** (`ep.StateDir()`). Maps are pinned with **node-local paths** via `LocalMapPath()` (see Q4 below)
- **Template Cache**: `pkg/datapath/loader/loader.go:74-89` - The loader maintains an `objectCache` with pre-compiled templates cached in `${StateDir}/templates`, ensuring compilation failures on one node don't affect cached state on other nodes

### Per-Node Initialization

Each node's Cilium daemon independently initializes the datapath:

- **Reinitialize Cycle**: `pkg/datapath/loader/base.go:382-546` - Each node calls `Reinitialize()` to:
  - Lock the compilation lock (line 392) to synchronize endpoint builds with base program compilation
  - Compile node-local programs (XDP at line 502, socket LB at line 489, alignchecker at line 507)
  - Attach programs to **locally discovered network devices** via `attachNetworkDevices()` (line 421-496)
  - The BPF filesystem path is determined per-node via `CiliumPath()` in `pkg/bpf/bpffs_linux.go:57-60`

**Key Isolation Mechanism**: Node-to-node compilation is independent. If Node A's kernel doesn't support a feature (e.g., newer BPF instruction set), its compiler produces v1 bytecode while Node B produces v3 bytecode. Each node's daemon independently handles compilation errors without affecting others.

---

## Q2: Deployment Architecture

### DaemonSet Deployment Model

Cilium uses a **Kubernetes DaemonSet** to ensure per-node isolation:

- **Deployment**: `install/kubernetes/cilium/templates/cilium-agent/daemonset.yaml:15-16` - Cilium agents run as a DaemonSet (`kind: DaemonSet`), ensuring exactly one Cilium pod runs on each node
- **Host Namespace Access**: Each pod mounts the host's BPF filesystem and network namespaces (required for eBPF program attachment to host network devices)

### Per-Node Agent Independence

Each node runs its own independent Cilium agent process:

- **Daemon Structure**: `daemon/cmd/daemon.go:92-195` - Each node has its own `Daemon` instance with:
  - **Independent Loader**: `loader datapath.Loader` (line 128) - Each daemon has its own loader instance that manages that node's BPF compilation and loading
  - **Independent Policy Repository**: `policy policy.PolicyRepository` (line 100) - Each node maintains its own in-memory copy of policy rules
  - **Independent Endpoint Manager**: `endpointManager endpointmanager.EndpointManager` (line 139) - Each node tracks only its local endpoints
  - **Compilation Lock**: `compilationLock datapath.CompilationLock` (line 121) - Synchronizes per-node endpoint regeneration with base program compilation

### Failure Isolation

When one node's agent fails to compile or load eBPF programs:

1. **Endpoint-Level Isolation**: `pkg/endpoint/bpf.go:548-569` - If `ReloadDatapath()` fails (line 566), the error is caught and logged per-endpoint. The endpoint transitions to an error state, but other endpoints on other nodes are unaffected
2. **No Cluster-Wide Propagation**:
   - The compilation lock (`compilationLock`) is **node-local** (line 392 of base.go)
   - Policy distribution to the failing node is unaffected by the local compilation failure
   - Other nodes continue compiling and loading their own programs independently

### Control Plane vs. Data Plane Separation

- **Control Plane**: Cilium Operator (separate deployment) manages CRD controllers and syncs policies to all nodes via etcd/API server
- **Data Plane**: Each node's agent independently implements policies by compiling and loading eBPF programs. A failure in the data plane (eBPF compilation/load) on Node A does not affect Node B's control plane synchronization or data plane execution

---

## Q3: Policy Distribution vs. Enforcement

### Policy Distribution

Cluster-wide policies are **distributed to all nodes equally**:

- **Source**: CiliumNetworkPolicy and NetworkPolicy resources are stored in Kubernetes API and distributed via watchers
- **Distribution Mechanism**: Each node's Cilium agent watches the API server independently (`pkg/k8s/watchers` - see `daemon/cmd/daemon.go:148`)
- **No Per-Node Compilation Blocking**: Policy rules are loaded into each node's in-memory `Repository` (see `pkg/policy/repository.go:160-191`). A policy rule is **not** compiled into eBPF bytecode until an endpoint needs it

### Policy Compilation (Per-Endpoint)

Policies are compiled to eBPF **only when endpoints require them**:

- **Policy Cache**: `pkg/policy/distillery.go:15-50` - The `policyCache` caches resolved policies per security identity
- **On-Demand Compilation**: `pkg/policy/distillery.go:66-102` - `updateSelectorPolicy()` resolves policies for specific identities only when endpoints with those identities are regenerated (line 73-101)
- **No Cross-Node Blocking**: If Node A's endpoint fails to compile policy into eBPF, only that endpoint is affected. Node B's endpoints compile and enforce their policies independently

### Per-Endpoint BPF Program Generation

Each endpoint's eBPF program encodes its policies:

- **Endpoint Policy Map**: `pkg/endpoint/bpf.go:86-89` - Each endpoint has a per-endpoint policy map at `LocalMapPath(policymap.MapName, e.ID)` (e.g., `cilium_ep_policy_00001`)
- **Policy Synchronization**: `pkg/endpoint/bpf.go:534-546` - `policyMapSync()` syncs the resolved policy into the endpoint's BPF map. If this fails, the map remains in its previous state and only this endpoint is affected

### Translation to Bytecode

Policy rules are compiled to eBPF bytecode in the `ReloadDatapath()` cycle:

- **Template Cache Compilation**: `pkg/datapath/loader/loader.go:708` - Each endpoint's eBPF program is compiled using the `templateCache.fetchOrCompile()` with that endpoint's specific policy configuration
- **Compilation Failure Isolation**: If compilation fails for endpoint E on Node A, other endpoints on Node A and all endpoints on Node B continue operating with their existing eBPF programs

---

## Q4: eBPF Map Scoping and State Isolation

### Per-Node BPF Filesystem Isolation

eBPF maps are **pinned to the BPF filesystem** on each node independently:

- **BPFfs Root**: `pkg/bpf/bpffs_linux.go:57-60` - `CiliumPath()` returns `/sys/fs/bpf/cilium` or a per-node custom path (determined at runtime)
- **Node-Local Mounting**: Each node mounts its own BPF filesystem instance. The mount is local to the node's kernel, completely isolating maps from other nodes

### Map Scoping Mechanisms

**1. Per-Endpoint Local Maps**:
- **LocalMapPath()**: `pkg/bpf/bpffs_linux.go:112-114` - Maps are pinned with endpoint-specific IDs in their names
  - Example: `cilium_ep_policy_00001`, `cilium_calls_00001`, `cilium_ct4_00001`
  - Format: `${name}${endpoint_id}` (line 107-109)
- **Pin Paths**: Each endpoint stores its maps in `${BPFfs}/cilium/lxc/${endpoint_id}/` directory hierarchy

**2. Per-Node Global Maps** (shared across endpoints on a node):
- **Global CT Maps**: `pkg/maps/ctmap/ctmap.go:62-72` - Connection tracking maps like `cilium_ct6_global`, `cilium_ct4_global`
- **Global Policy Maps**: `pkg/maps/policymap/` - Shared across endpoints
- **These are pinned to `${BPFfs}/tc/globals/` (line 347, 395 of loader.go) - node-local by virtue of the mounted BPFfs**

**3. Host Maps** (isolated per-host endpoint):
- **Calls Map**: `pkg/maps/callsmap/callsmap.go:8-19` - Each host endpoint has `cilium_calls_hostns_`, distinct from endpoint calls maps
- **Netdev Maps**: Per-interface netdev maps like `cilium_calls_netdev_${if_index}` (line 221 of loader.go)

### Map Isolation Properties

**Maps are Node-Local**:

1. **No Cluster-Wide Sharing**: eBPF maps exist only in kernel memory on each node and are pinned to that node's BPFfs. There is no mechanism to share them across nodes
2. **Namespace Isolation**: Each node's BPF filesystem is a separate mount; even if two nodes share the same `StateDir` path (e.g., via NFS - unusual), their kernels would have separate BPFfs mounts with independent map instances

### Failure Isolation: Map Creation/Update

If a node fails to create or update a map:

- **Local Failure**: `pkg/endpoint/bpf.go:473-478` - If `lxcmap.WriteEndpoint()` fails to update the endpoint info in the endpoints map, the error is returned and the endpoint regeneration fails locally
- **Endpoint-Scoped Impact**: Only that endpoint cannot process traffic. Endpoints with already-created maps continue operating
- **Other Nodes Unaffected**: Node B's maps are completely independent. Node B's endpoints continue to create, update, and use their own maps

### Connection Tracking Map Isolation

- **Per-Node CT State**: Each node maintains its own connection tracking maps (`cilium_ct4_local_*`, `cilium_ct4_global`)
- **No Cross-Node Entries**: CT tables store connection state for flows on that node only. Traffic that transitions between nodes is treated as new connections at each node's boundary
- **GC Independence**: `pkg/maps/ctmap/gc/gc.go` - Garbage collection of CT entries runs independently per-node; failures in Node A's GC don't affect Node B's GC

---

## Evidence

### Key File References

**eBPF Compilation & Loading**:
- `pkg/datapath/loader/compile.go:134-257` - Compilation with per-node CPU probing and variable injection
- `pkg/datapath/loader/base.go:382-546` - Node initialization and BPF program attachment
- `pkg/datapath/loader/loader.go:700-732` - Per-endpoint eBPF program loading

**Endpoint & Policy Management**:
- `pkg/endpoint/endpoint.go:141-195` - Endpoint structure with per-node regeneration
- `pkg/endpoint/bpf.go:379-520` - Endpoint BPF regeneration with local error handling
- `pkg/endpoint/regenerationcontext.go:55-74` - Per-endpoint regeneration context

**Policy Distribution & Compilation**:
- `pkg/policy/repository.go:160-191` - Per-node policy repository
- `pkg/policy/distillery.go:66-102` - On-demand policy resolution per-identity
- `daemon/cmd/daemon.go:100, 128, 139` - Daemon's per-node policy, loader, and endpoint manager instances

**BPF Map Scoping**:
- `pkg/bpf/bpffs_linux.go:44-114` - Per-node BPFfs root and LocalMapPath implementation
- `pkg/maps/ctmap/ctmap.go:62-89` - Connection tracking map naming and scoping
- `pkg/maps/callsmap/callsmap.go:1-20` - Per-endpoint and per-host calls map names

**Kubernetes Deployment**:
- `install/kubernetes/cilium/templates/cilium-agent/daemonset.yaml:15-16` - DaemonSet deployment model ensuring one pod per node

**Compilation Synchronization**:
- `pkg/endpoint/bpf.go:392-398` - Compilation read lock (per-node) during endpoint regeneration
- `pkg/datapath/loader/base.go:391-393` - Compilation lock acquisition during base program initialization

### Architectural Highlights

1. **Per-Node Kernel Probing**: Each node independently detects its kernel capabilities (BPF ISA version) → no shared compilation assumptions
2. **Per-Node Agent Process**: Each DaemonSet pod runs its own Cilium agent daemon with independent Loader, PolicyRepository, and EndpointManager instances
3. **Local Compilation & Attachment**: Each node compiles C → eBPF bytecode and attaches to local network devices; no central coordinator
4. **Node-Local BPFfs**: Each node's kernel provides its own BPF filesystem mount with independent map instances
5. **Endpoint-Scoped Regeneration**: Failures in one endpoint's BPF regeneration are caught and logged locally; other endpoints continue operating

This architecture ensures **fault isolation at the per-node granularity**: a failure to compile or load eBPF programs on one node is contained and does not propagate to the cluster control plane or to other nodes' data planes.
