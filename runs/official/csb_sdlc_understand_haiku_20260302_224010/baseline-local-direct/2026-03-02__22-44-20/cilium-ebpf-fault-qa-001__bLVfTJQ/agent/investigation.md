# Cilium eBPF Fault Isolation

## Q1: Per-Node eBPF Lifecycle

### Compilation Phase

Each Cilium node independently compiles eBPF programs through the **per-node loader** component:

- **Component**: `pkg/datapath/loader/loader.go` (lines 74-89) defines the `loader` struct which manages per-node eBPF compilation and loading
- **Per-node compilation**: `pkg/datapath/loader/compile.go` (lines 170-257) - the `compile()` function invokes `clang` on **each node individually** to compile eBPF source code to bytecode
- **Node-specific configuration**: Compilation is driven by node-local headers:
  - `pkg/datapath/loader/base.go` (lines 46-74) - writes node-specific configuration headers (`netdev_config.h`, `node_config.h`) that reflect the current node's kernel version, enabled features, and device configuration
  - The loader reads these headers before each compilation: lines 176-181 in `compile.go` add node-specific include paths

### Loading Phase

Once compiled, each node **independently loads** its own eBPF programs:

- **Per-endpoint loading**: `pkg/datapath/loader/loader.go` (lines 700-732) - `ReloadDatapath()` method compiles and loads eBPF programs **specific to a single endpoint and node**
- **Template caching**: The loader maintains a **per-node template cache** (line 77) to avoid recompilation when multiple endpoints share the same configuration
- **Kernel verifier execution**: Each node runs the kernel's eBPF verifier locally on its compiled bytecode (line 16 in `loader.go` imports `"github.com/cilium/ebpf"` which handles kernel loading)
- **Error isolation**: If the kernel verifier rejects a program on node A, the loader returns an error locally (line 709 in `loader.go`) - **this error only affects node A**

### Node-Local Configuration Effects

- **Kernel version**: `pkg/datapath/loader/compile.go` (lines 134-157) - `getBPFCPU()` probes the local kernel to determine eBPF ISA version (v1, v2, or v3), which affects compilation flags
- **Feature availability**: Lines 143-148 in `compile.go` check for kernel features like `HaveV3ISA()` and `HaveProgramHelper()` - these checks are **local to each node**
- **Device-specific rewrites**: `pkg/datapath/loader/loader.go` (lines 176-223) - `hostRewrites()` function adapts eBPF variable substitutions based on the **local host's MAC address, interface index, and masquerade IP**

### Lifecycle Timing

**Node-local vs. cluster-wide**:
- **Compilation and loading**: Node-local (no coordination with other nodes)
- **Policy distribution**: Cluster-wide (policies come from Kubernetes API server)
- **eBPF program bytecode**: Node-local (each node compiles its own)
- **Attachment to kernel**: Node-local (via TC, XDP, or TCX hooks on the local node)

## Q2: Deployment Architecture

### DaemonSet Deployment Model

Cilium deploys as a **DaemonSet** (one pod per node):

- **Manifest**: `install/kubernetes/cilium/templates/cilium-agent/daemonset.yaml` (lines 15-37) - defines `kind: DaemonSet` which ensures one Cilium agent pod runs on **every node**
- **Per-node agent**: Each node runs its own instance of the Cilium daemon (`daemon/main.go` lines 1-16, which invokes `cmd.Agent`)
- **Independent initialization**: Each daemon instance independently initializes:
  - The local datapath loader (`pkg/datapath/loader/loader.go` lines 106-116)
  - Per-node BPF maps
  - The compilation lock used to serialize template compilation

### Control Plane vs. Data Plane Separation

- **Control plane** (cluster-wide): Policy Repository manages cluster-wide policies (`pkg/policy/repository.go` lines 36-91)
- **Data plane** (node-local): Each node's loader and endpoint manager apply policies to that node's eBPF programs
- **Isolation point**: When a policy is distributed to a node, the **local endpoint regeneration** on that node compiles and loads it independently

### Failure Isolation

When one node's Cilium agent fails to load eBPF programs:

1. **Endpoint regeneration failure**: `pkg/endpoint/bpf.go` (lines 565-572) - if `ReloadDatapath()` returns an error, it's handled **per-endpoint** on that node
2. **Error handling**: Lines 567-571 log the error and return it locally - **no cluster-wide propagation**
3. **Node degradation**: The failing node may:
   - Log errors but continue running
   - Degrade to a fallback mode (e.g., using iptables instead of eBPF)
   - Not propagate the failure to other nodes via the API server
4. **Other nodes unaffected**: Other nodes continue to call `ReloadDatapath()` independently, unaware of failures on other nodes

### Compilation Lock

- **Per-node lock**: `pkg/datapath/loader/loader.go` (line 86) - `compilationLock` serializes **template compilation on a single node**
- **Not cluster-wide**: Only protects concurrent goroutines on the same node from compiling templates simultaneously
- **Failure scope**: If compilation fails due to kernel verifier rejection, only the nodes with incompatible kernels are affected

## Q3: Policy Distribution vs. Enforcement

### Policy Distribution (Cluster-Wide)

Cluster-wide resources like `CiliumNetworkPolicy` are distributed to all nodes:

- **Source**: Kubernetes API server stores cluster-wide policies
- **Distribution**: Each Cilium agent watches Kubernetes for policy changes via Watchers (see `pkg/k8s/watchers/` imports in `daemon/cmd/daemon_main.go` line 72)
- **No point of failure**: If policy distribution fails on one node, it doesn't affect other nodes (each has its own watch connection)

### Policy Resolution (Per-Node)

When a policy arrives at a node, that node **independently translates** it into eBPF:

- **Policy repository**: Each node runs its own `Repository` instance (`pkg/policy/repository.go`) that stores local copy of policies
- **Per-endpoint resolution**: `pkg/endpoint/bpf.go` (lines 620-630) - `regenerateBPF()` calls `regeneratePolicy()` which resolves policies **for that node's endpoints**
- **Distillery/policy cache**: `pkg/policy/distillery.go` (lines 15-50) - the `policyCache` is **per-node**, storing resolved policies for local identities
- **eBPF bytecode generation**: The resolved policy is written to endpoint-specific header files and compiled into eBPF bytecode **locally** (lines 731-732 in `pkg/endpoint/bpf.go`)

### Why One Node's Failure Doesn't Block Others

1. **Policy resolution is idempotent**: Each node resolves policies independently based on its local copy
2. **Compilation errors are local**: If policy bytecode fails to compile on node A (e.g., due to kernel verifier rejection), this error is caught locally in `realizeBPFState()` (lines 566-572 in `pkg/endpoint/bpf.go`)
3. **Error handling is local**: The error is returned to the endpoint's regeneration context and logged locally - **not propagated to other nodes**
4. **API server doesn't know**: Kubernetes API server has no mechanism to detect compilation failures, so it continues to distribute the same policy to all nodes

## Q4: eBPF Map Scoping and State Isolation

### Map Scoping: Node-Local Not Cluster-Wide

All eBPF maps used by Cilium are **node-local**:

- **BPFfs pinning**: `pkg/bpf/bpffs_linux.go` (lines 44-60) - maps are pinned to the **local node's BPFfs filesystem** at `/sys/fs/bpf/cilium/` (or `/run/cilium/bpffs/` in containers)
- **Per-node BPFfs mount**: Lines 121-150 show that each node mounts its own independent BPFfs instance - **maps don't cross node boundaries**

### Per-Endpoint Maps

Maps are scoped to individual endpoints within a node:

- **Policy map naming**: `pkg/maps/policymap/policymap.go` (line 34) - `MapName = "cilium_policy_v2_"` with endpoint ID suffix via `LocalMapPath()` (line 112 in `pkg/bpf/bpffs_linux.go`)
- **Example**: Endpoint 123 has map `cilium_policy_v200123` pinned at `/sys/fs/bpf/cilium/cilium_policy_v200123`
- **Global maps**: Some maps like connection tracking (`ctmap`) are shared across endpoints on the same node, but never across nodes

### State Isolation Mechanisms

1. **Linux kernel namespaces**: Each node's eBPF programs run in the **kernel namespace of that node** - BPF maps in one node's kernel can't be accessed by another node's kernel
2. **BPFfs filesystem isolation**: `pkg/bpf/bpffs_linux.go` (line 146) - each node has its own `bpffs` mount point, preventing cross-node map access
3. **Local map pinning**: Maps are pinned only on the node that creates them; other nodes pin to their own locations

### Failure Isolation via Maps

If a node fails to create or update a map:

- **Endpoint-local impact**: `pkg/endpoint/bpf.go` (lines 472-477) - `lxcmap.WriteEndpoint()` updates the endpoint map locally; if it fails, only that endpoint on that node is affected
- **No cross-node dependencies**: Other nodes' endpoints don't depend on this node's maps - each node has its own copies
- **Packet processing unaffected**: If node A fails to update its policy map, node B continues to process packets using its own policy map

### Example: Connection Tracking Map

- **Per-node CT map**: `pkg/maps/ctmap/` - each node has its own connection tracking map
- **Isolation**: When node A's Cilium agent crashes, its CT map is cleaned up on restart (via `ctCleaned` logic in `pkg/endpoint/bpf.go` lines 650-664); this doesn't affect node B's CT map
- **State loss**: Only connections on node A are affected; node B's connections persist independently

## Evidence

### Key Files and Line References

**Q1: Per-Node eBPF Lifecycle**
- `pkg/datapath/loader/loader.go:74-89` - loader struct definition
- `pkg/datapath/loader/loader.go:700-732` - ReloadDatapath() per-node loading method
- `pkg/datapath/loader/compile.go:170-257` - compile() function for per-node compilation
- `pkg/datapath/loader/base.go:46-74` - per-node header file generation
- `pkg/datapath/loader/compile.go:134-157` - getBPFCPU() per-node kernel probing

**Q2: Deployment Architecture**
- `install/kubernetes/cilium/templates/cilium-agent/daemonset.yaml:15-37` - DaemonSet manifest
- `daemon/main.go:1-16` - per-node agent initialization
- `pkg/datapath/loader/loader.go:86` - per-node compilation lock
- `pkg/endpoint/bpf.go:565-572` - per-endpoint error handling in realizeBPFState()

**Q3: Policy Distribution vs. Enforcement**
- `pkg/policy/repository.go:36-91` - PolicyContext and Repository interfaces
- `pkg/endpoint/bpf.go:620-630` - regeneratePolicy() per-node resolution
- `pkg/policy/distillery.go:15-50` - per-node policy cache
- `pkg/k8s/watchers/` - per-node policy watchers

**Q4: eBPF Map Scoping and State Isolation**
- `pkg/bpf/bpffs_linux.go:44-60` - CiliumPath() and BPFfs mounting
- `pkg/bpf/bpffs_linux.go:112-114` - LocalMapPath() per-node map naming
- `pkg/maps/policymap/policymap.go:34` - per-endpoint policy map naming
- `pkg/endpoint/bpf.go:472-477` - per-endpoint map write operations
- `pkg/endpoint/bpf.go:650-664` - per-node connection tracking cleanup
