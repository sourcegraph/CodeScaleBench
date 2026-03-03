# Cilium eBPF Fault Isolation

This investigation explains how Cilium's architecture ensures that eBPF program failures on one Kubernetes node do not propagate cluster-wide, and how per-node isolation is maintained at the compilation, loading, and map scoping layers.

---

## Q1: Per-Node eBPF Lifecycle

### How are eBPF programs compiled, loaded, and attached on each node independently?

**Compilation occurs locally per-node** via the **`pkg/datapath/loader/`** subsystem:

- **Main entry point**: `pkg/datapath/loader/loader.go:ReloadDatapath()` (lines 700-732)
  - This is called for each endpoint on the node
  - Calls `l.templateCache.fetchOrCompile()` to compile or retrieve cached eBPF programs
  - Contains per-endpoint specific rewrites and constant substitutions

- **Actual compilation**: `pkg/datapath/loader/compile.go` (lines 1-150+)
  - `compileDatapath()` function invokes the **clang** compiler locally on each node
  - Produces eBPF bytecode specific to the node's kernel capabilities
  - Program sources are in the `bpf/` directory of Cilium source

- **Kernel feature detection** (affects compilation): `pkg/datapath/loader/compile.go:getBPFCPU()` (lines 134-157)
  - Probes the kernel at runtime to determine eBPF ISA version: v1, v2, or v3
  - Uses `pkg/datapath/linux/probes` to detect available BPF helpers (e.g., `bpf_redirect_neigh`)
  - Kernel v5.10+ can support v3 ISA; kernels 4.14+ support v2
  - This means each node may compile **different bytecode versions** based on its kernel

### What component is responsible for compiling eBPF programs on each node?

- **Cilium Agent** (runs as DaemonSet, one per node)
  - Deployed via Helm values in `install/kubernetes/cilium/values.yaml`
  - Each pod has full access to the node's kernel and filesystem
  - The `loader` subsystem is injected via Hive dependency injection (`pkg/datapath/cells.go`)

- **Compilation parameters are node-specific**:
  - `pkg/datapath/loader/loader.go:hostRewrites()` (lines 174-224) computes per-node values:
    - Device MAC addresses (lines 186-193) - pulled from network interfaces
    - Interface indices (line 205) - specific to the node's netlink
    - Masquerade IP addresses (lines 208-218) - per-node configuration
  - These are substituted as ELF constants via `bpf.LoadAndAssign()` in `pkg/datapath/loader/loader.go:attachCiliumHost()` (line 345)

### How does node-specific configuration (kernel version, enabled features, etc.) affect compilation?

- **Datapath hash invalidation**: `pkg/datapath/loader/cache.go:UpdateDatapathHash()` (lines 56-94)
  - Computes SHA256 hash of the node's configuration via `hashDatapath()`
  - Hash includes kernel version, feature flags, IPSec settings, etc. from `LocalNodeConfiguration`
  - If hash changes (e.g., after kernel upgrade or feature enabled), cache is invalidated and recompilation forced
  - Hash is computed in `pkg/datapath/loader/hash.go:hashDatapath()` (lines 16-24)

- **Template caching per node**: `pkg/datapath/loader/cache.go:objectCache` (lines 26-94)
  - Each node maintains its own cache of compiled templates in `option.Config.StateDir`
  - Cache key is endpoint configuration hash + node configuration hash
  - This ensures wrong templates aren't shared across nodes with different kernels

### At what point in the lifecycle does the eBPF program become node-local vs. cluster-wide?

- **Source files are cluster-wide**: The eBPF C sources (`bpf_lxc.c`, `bpf_host.c`, etc.) are identical across all nodes

- **Compilation is node-local**: When `pkg/datapath/loader/compile.go:compileDatapath()` is called:
  - Each node independently compiles the source with node-specific clang flags
  - Output: `.o` (object) files are node-local in `option.Config.StateDir/templates/`

- **Loading and attachment is node-local**: `pkg/datapath/loader/loader.go:reloadEndpoint()` (lines 511-584)
  - Each node loads the compiled bytecode into the kernel via eBPF syscalls
  - **If loading fails** (e.g., verifier rejection), the function returns an error
  - The error is scoped to that node's endpoint; other nodes continue

- **Map pinning is node-local**: `pkg/bpf/bpffs_linux.go:LocalMapPath()` (lines 111-114)
  - Maps are pinned to `/sys/fs/bpf/cilium/` on the **local node**
  - Each node has its own bpffs mount (typically `/sys/fs/bpf`)

---

## Q2: Deployment Architecture

### How does Cilium's deployment model ensure per-node isolation?

**Cilium is deployed as a Kubernetes DaemonSet** (`install/kubernetes/cilium/values.yaml`):
- One pod (`cilium-agent`) runs on every node
- Each agent process independently manages that node's eBPF datapath
- No shared state between nodes (except via etcd/kvstore for policy distribution)

**Process isolation per node**:
- Each agent:
  1. Watches for endpoint (pod) creation on its node
  2. Compiles eBPF programs locally for that endpoint
  3. Loads programs into the kernel
  4. Maintains per-endpoint BPF maps on the bpffs

**Failure isolation**:
- If agent on Node A fails to compile or load eBPF:
  - Only Node A's pods cannot enforce network policies
  - Agent logs error locally via `pkg/datapath/loader/metrics` instrumentation
  - Agent may enter degraded state but doesn't block other nodes
  - Node B, Node C, etc. continue with their own eBPF enforcement independently

### What happens when one node's Cilium agent fails to initialize its eBPF programs?

When `pkg/datapath/loader/loader.go:ReloadDatapath()` returns an error:
- The error is propagated to `pkg/endpoint/bpf.go` (endpoint.go regeneration logic)
- Endpoint remains in a degraded state (may not have policy enforcement)
- Kubernetes pod may be marked as unhealthy if liveness probes fail
- **The failure does not propagate to other nodes** because:
  - Each node has its own independent copy of the loader
  - No cross-node RPC or shared state in the datapath layer
  - Other nodes' loaders continue their work independently

### How does the control plane vs. data plane split contribute to isolation?

**Control Plane (per-cluster)**:
- Cilium Operator runs cluster-wide (usually 1-2 pods)
- Distributes policies as Kubernetes CRDs (CiliumNetworkPolicy)
- Manages global state (identities, IP cache) in etcd/kvstore
- **Failure here affects policy distribution, but not already-loaded eBPF**

**Data Plane (per-node)**:
- Each Cilium Agent compiles and loads eBPF **independently** from control plane
- Once eBPF is loaded, it runs in kernel without agent intervention (except for map updates)
- Agent can fail without stopping packet processing by already-loaded eBPF
- eBPF programs run in kernel without dependency on agent process availability (for the datapath itself)

---

## Q3: Policy Distribution vs. Enforcement

### How are CiliumNetworkPolicy resources distributed to each node?

- **Cluster-wide resources**: CiliumNetworkPolicy CRDs are stored in etcd
- **Per-node watchers**: Each `cilium-agent` watches the Kubernetes API for policy changes
  - Implemented via `pkg/k8s/watchers` and informer factories
  - Each agent maintains a local copy of the policies that could affect its endpoints

- **Policy distribution is async**:
  - When policy is created, API server returns immediately
  - Each agent independently fetches and processes the policy
  - No synchronization point between nodes

### What component on each node translates policies into eBPF bytecode?

**Policy translation (cluster per-identity)**: `pkg/policy/distillery.go` (lines 1-150+)
- The `policyCache` maintains resolved policies for each security identity
- `updateSelectorPolicy()` (lines 73-102) resolves a policy for a given identity
- Output is a `selectorPolicy` object describing which identities can communicate

**Per-endpoint eBPF generation**: `pkg/endpoint/bpf.go` (lines 1-150+)
- Each endpoint has a policy map: `policyMapPath()` returns `LocalMapPath(policymap.MapName, e.ID)` (line 88)
- When policy changes, the agent calls `loader.ReloadDatapath()` to recompile
- The compilation step in `pkg/datapath/loader/compile.go` generates endpoint-specific eBPF from policy

**Per-node compilation with node-specific constants**:
- `pkg/datapath/loader/loader.go:ELFVariableSubstitutions()` injects endpoint and node-specific data
- `pkg/datapath/loader/loader.go:ELFMapSubstitutions()` remaps map names to node-local versions
- All constants (identities, security labels) are baked into the compiled ELF

### Why doesn't a compilation failure on one node block policy distribution to other nodes?

- **Policies are data, not code**: CiliumNetworkPolicy is stored as cluster-wide configuration
- **Compilation is node-local**: Policy → eBPF bytecode compilation happens independently on each node
- **Failure is scoped**: If Node A's compilation fails:
  - Policy is still in etcd
  - Node B, C, D successfully compile the **same policy** for their endpoints
  - Node A may fall back to deny-all or degraded mode, but doesn't affect others

- **No cluster-wide compilation step**: There is no central compilation service
  - Each node compiles its own bytecode
  - No distributed build system that could fail cluster-wide

---

## Q4: eBPF Map Scoping and State Isolation

### Are eBPF maps node-local or cluster-wide?

**Maps are primarily node-local**:

**Per-endpoint maps** (node-local):
- Policy map: `cilium_policy_v2_<endpointID>`
  - Located at `pkg/bpf/bpffs_linux.go:LocalMapPath(policymap.MapName, endpointID)`
  - Example: `/sys/fs/bpf/cilium/cilium_policy_v2_00001` on Node A
  - Different path on Node B even for an endpoint with same ID (different mount)

- Connection tracking (CT) maps: `cilium_ct{4,6}_<endpointID>`
  - Per-endpoint, per-protocol CT tables
  - Stored at local map paths via `pkg/maps/ctmap/ctmap.go`
  - Line 62: `MapNamePrefix = "cilium_ct"`

- Tail call maps: `cilium_calls_<endpointID>`
  - For BPF-to-BPF jumps (tail calls)
  - Scoped to endpoint on the node

**Shared global maps** (per-node replicas):
- Policy call map: `cilium_call_policy`
  - Used for tail calls into endpoint-specific policy programs
  - Referenced in `pkg/datapath/loader/loader.go:attachCiliumHost()` (line 358)
  - Each node has its own replica in its own bpffs

- IP cache: `cilium_ipcache`
  - Caches IP → identity mappings
  - Each node has its own copy
  - Updated by agent for that node's kernel

### What mechanisms (BPF filesystem pinning, namespaces) ensure map isolation?

**BPF filesystem pinning** (`pkg/bpf/bpffs_linux.go`):

- **Mount per host**: Each node has `/sys/fs/bpf` or `/run/cilium/bpffs` mounted
  - Mounted via `mountFS()` (lines 120-150) called during agent startup
  - Each node's kernel has its own bpffs instance

- **Path-based isolation**: `LocalMapPath()` (lines 111-114)
  ```go
  func LocalMapPath(name string, id uint16) string {
      return MapPath(LocalMapName(name, id))
  }
  // LocalMapName: fmt.Sprintf("%s%05d", name, id)
  // Example: cilium_policy_v2_00001
  ```

- **Directory hierarchy**:
  - `/sys/fs/bpf/cilium/` - Cilium object directory (line 59: `CiliumPath()`)
  - `/sys/fs/bpf/tc/globals/` - Legacy TC globals (line 53: `TCGlobalsPath()`)
  - Per-device subdirs: `/sys/fs/bpf/cilium/lxc/veth1234/links/` for endpoint veth attachments

**Network namespaces**:
- Cilium doesn't rely on network namespaces for map isolation
- Maps are pinned in the **root namespace's bpffs**
- Multiple namespaces on the same node access the same maps, but:
  - Each endpoint's eBPF programs only read/write their own endpoint ID's maps
  - Maps are protected by BPF verifier (kernel ensures memory safety)

**Per-kernel isolation** (implicit):
- Each Linux kernel maintains its own bpffs
- Docker/Kubernetes container isolation means Node A's kernel ≠ Node B's kernel
- Maps are kernel objects, not accessible across nodes

### If a node fails to create or update a map, how does that affect other nodes' packet processing?

**Failure to create**:
- `pkg/datapath/loader/loader.go:reloadEndpoint()` (line 515) calls `bpf.LoadAndAssign()`
- If map creation fails, the entire load fails and returns error
- Error is logged locally; endpoint on that node enters degraded state
- **Other nodes**: Unaffected. They have their own independent map creation

**Failure to update**:
- Maps are updated via BPF syscalls in the agent
- Example: `pkg/maps/policymap/policymap.go` map operations (line 98: PolicyMap type)
- If update fails on Node A:
  - Node A's traffic policy doesn't reflect the update
  - Node B, C continue with their own map updates
  - Cross-node traffic between A and B may have inconsistent policy temporarily

**Recovery mechanisms**:
- `pkg/datapath/loader/cache.go:UpdateDatapathHash()` will trigger recompilation if config changes
- Endpoint regeneration can be triggered by controllers in `pkg/endpoint/bpf.go`
- Manual pod restart forces endpoint recreation and map recreation

---

## Evidence

### Per-Node Compilation
- `pkg/datapath/loader/loader.go:ReloadDatapath()` - Entry point per node, lines 700-732
- `pkg/datapath/loader/compile.go:getBPFCPU()` - Kernel feature detection, lines 134-157
- `pkg/datapath/loader/hash.go:hashDatapath()` - Node config hashing, lines 16-24
- `pkg/datapath/loader/cache.go:UpdateDatapathHash()` - Cache invalidation, lines 56-94

### Per-Node Loading & Attachment
- `pkg/datapath/loader/loader.go:reloadHostEndpoint()` - Host endpoint loading, lines 317-334
- `pkg/datapath/loader/loader.go:attachCiliumHost()` - Attach to cilium_host, lines 336-378
- `pkg/datapath/loader/loader.go:reloadEndpoint()` - Endpoint loading, lines 507-584
- `pkg/datapath/loader/loader.go:hostRewrites()` - Per-node constant generation, lines 174-224

### Per-Node eBPF Map Pinning
- `pkg/bpf/bpffs_linux.go:LocalMapPath()` - Per-endpoint map path, lines 111-114
- `pkg/bpf/bpffs_linux.go:LocalMapName()` - Per-endpoint map name, lines 106-109
- `pkg/bpf/bpffs_linux.go:CiliumPath()` - Per-node cilium directory, lines 56-60
- `pkg/bpf/bpffs_linux.go:TCGlobalsPath()` - Per-node globals directory, lines 49-54

### Policy Distribution (Cluster-wide)
- `pkg/policy/distillery.go` - Policy cache and resolution, lines 1-150+
- `pkg/endpoint/bpf.go:policyMapPath()` - Per-endpoint policy map, line 87-89

### Endpoint Lifecycle
- `pkg/endpoint/endpoint.go` - Endpoint struct and initialization, lines 1-100+
- `pkg/endpoint/bpf.go` - eBPF-specific endpoint operations, lines 1-150+

### Deployment Architecture
- `install/kubernetes/cilium/values.yaml` - Helm values showing DaemonSet deployment
- `pkg/datapath/cells.go` - Hive cell configuration for loader injection

### Configuration Management
- `pkg/option/config.go` - Global configuration, includes StateDir for per-node templates
- `pkg/defaults/defaults.go` - Constants like BPFFSRoot (/sys/fs/bpf), TCGlobalsPath (tc/globals)

