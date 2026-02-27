# Cilium eBPF Fault Isolation

## Q1: Per-Node eBPF Lifecycle

### How eBPF Programs Are Compiled, Loaded, and Attached Independently

**Responsible Components:**

1. **Agent Initialization** (`pkg/datapath/loader/loader.go`):
   - The `Loader` interface is the primary component responsible for eBPF program lifecycle
   - Implements `Reinitialize()` (line 382 in `pkg/datapath/loader/base.go`) which orchestrates compilation
   - Called once during agent startup and when kernel features change

2. **Compilation Process** (`pkg/datapath/loader/compile.go`):
   - **Entry point**: `compile()` function (line 170) invokes clang/LLVM to compile C source to BPF bytecode
   - **Standard flags applied**: `-O2 --target=bpf -std=gnu89 -Wall -Wextra -Werror`
   - **BPF CPU detection** (`getBPFCPU()` line 135): Probes kernel to determine supported BPF ISA:
     - Kernel 5.10+: v3 instructions
     - Kernel 4.14+: v2 instructions
     - Older: v1 instructions
   - **Specialized compilation functions**:
     - `compileDefault()` (line 331): Default datapath
     - `compileNetwork()` (line 336): IPSec encryption programs
     - `compileOverlay()` (line 364): Overlay network tunneling
     - `compileWireguard()` (line 397): WireGuard support

3. **Node-Specific Configuration in Compilation**:
   - **Template substitution** (`pkg/datapath/loader/template.go` lines 151-253):
     - Each endpoint gets a compiled program with substituted constants:
       - `LXC_IP_1`, `LXC_IP_2`: IPv6 address (split into two 64-bit parts)
       - `LXC_IPV4`: IPv4 address (32-bit integer)
       - `LXC_ID`: Unique per-node endpoint identifier
       - `SECLABEL`: Security identity
       - `interface_ifindex`: Host interface index
     - Map names are rewritten per-endpoint: `cilium_policy_v2_<TEMPLATE_ID>` → `cilium_policy_v2_<ACTUAL_ENDPOINT_ID>`
   - **Kernel version compatibility**: Compilation flags and instructions selected based on `uname` output (kernel version detection in loader initialization)

4. **Loading and Attachment** (`reloadEndpoint()` line 511 in `pkg/datapath/loader/loader.go`):
   - Load compiled ELF object via `bpf.LoadAndAssign(&lxcObjects, spec, options)`
   - Attach programs to interface TC (Traffic Control) filters:
     - Ingress programs: `tc filter add dev <veth> root ingress bpf object-file <prog>`
     - Egress programs: `tc filter add dev <veth> egress bpf object-file <prog>`
   - Insert policy programs into **cilium_call_policy** map using endpoint ID as key
   - Pin maps to `/sys/fs/bpf/tc/globals/` for persistence across container restarts

5. **Per-Endpoint Program Generation**:
   - Generated eBPF binaries: `bpf_lxc.o`, `bpf_host.o`, `bpf_xdp.o`, `bpf_network.o`, `bpf_overlay.o`, `bpf_wireguard.o`
   - Each endpoint type gets separate compiled binaries with embedded constants
   - Compilation is idempotent: same input source code with different constants produces endpoint-specific binaries

**Key Insight**: The compilation step happens **independently on each node**. There is no centralized compilation service. Each Cilium agent downloads the same source code but compiles with its own kernel-specific configuration and endpoint-specific constants, ensuring per-node independence.

---

## Q2: Deployment Architecture

### How Cilium Ensures Per-Node Isolation Through Deployment Model

1. **DaemonSet Deployment Model** (`install/kubernetes/cilium/templates/cilium-agent/daemonset.yaml`):
   - **Type**: Kubernetes DaemonSet (runs exactly one pod per node)
   - **Node affinity**: Uses `spec.nodeName` for node-specific scheduling
   - **Node name propagation**: Passes `K8S_NODE_NAME` environment variable to agent

2. **Per-Node Initialization Flow**:
   - **Init containers** (lines 435-765 in daemonset.yaml) run sequentially to prepare node-local state:
     1. `config` - Builds configuration from ConfigMaps/secrets
     2. `mount-bpf-fs` - Mounts BPF filesystem at `/sys/fs/bpf` (node-local kernel filesytem)
     3. `mount-cgroup` - Sets up cgroup2 filesystem (node-local)
     4. `apply-sysctl-overwrites` - Tunes kernel parameters on that specific node
     5. `wait-for-node-init` - Waits for Cilium CNI node initialization
     6. `clean-cilium-state` - Cleans up stale BPF state from previous agent runs
     7. `install-cni-binaries` - Copies CNI plugin binary to node

3. **Daemon Initialization** (`pkg/daemon/cmd/daemon.go` lines 1-150):
   - Main `Daemon` struct contains critical components for isolation:
     - `loader` (line 126): datapath.Loader for per-node eBPF management
     - `policy` (line 100): PolicyRepository (per-node policy enforcement)
     - `compilationLock` (line 121): Synchronizes eBPF compilation to prevent race conditions
     - `endpointManager` (line 139): Manages container endpoints on that specific node
   - Each agent instance is completely independent - no shared state between nodes

4. **What Happens When One Node's Cilium Agent Fails**:
   - **Compilation failure**: eBPF program fails to compile on Node A
     - Only Node A cannot load new policies
     - Nodes B, C, D continue normal operation (they compiled successfully with their kernel)
     - Existing policies on Node A continue to apply via cached maps pinned to `/sys/fs/bpf`
   - **eBPF program crash**: A policy program segfaults on Node A
     - Only endpoints on Node A are affected
     - Other nodes' endpoints continue normal packet processing
     - Kubernetes may restart the pod on Node A, triggering re-compilation
   - **Control plane communication failure**: Node A's agent cannot reach kube-apiserver
     - Node A uses cached policies from previous sync
     - Nodes B, C, D continue syncing new policies normally

5. **Control Plane vs. Data Plane Split**:
   - **Control Plane (per-node)**: Cilium agent watches Kubernetes API, compiles policies to eBPF
   - **Data Plane (per-node)**: Kernel eBPF programs enforce policies directly on packets
     - No dependency on agent being running after initial load
     - Maps persist in `/sys/fs/bpf` kernel filesystem
     - Packets are processed entirely in kernel, not user-space
   - **Independence**: Data plane failure on Node A doesn't affect Node B's data plane
     - Each node's kernel eBPF programs run independently
     - No IPC or network communication between nodes' data planes

**Key Insight**: The DaemonSet model ensures exactly one agent per node. Each agent maintains completely independent state (compilation lock, policy repository, endpoint manager, BPF filesystem). Failures in one agent do not propagate because there is no shared control plane infrastructure or data plane dependencies between nodes.

---

## Q3: Policy Distribution vs. Enforcement

### How Cluster-Wide Policies Are Distributed and Per-Node Enforcement Works

1. **Policy Distribution Mechanism** (`pkg/policy/policy.go` and `pkg/policy/distillery.go`):
   - **PolicyRepository** (`pkg/policy/policy.go`):
     - Centralized cluster-wide policy store accessed by all endpoints on a node
     - Watches Kubernetes API for CiliumNetworkPolicy, NetworkPolicy, ClusterRole changes
   - **Distribution to nodes**:
     - Each Cilium agent watches Kubernetes API independently
     - Fetches the same CiliumNetworkPolicy CRDs as other nodes
     - No per-node filtering at distribution layer (all nodes get all policies)

2. **Policy Translation to Per-Node eBPF**:
   - **policyCache** (`pkg/policy/distillery.go` line 16):
     - LRU cache of resolved policies per security identity
     - Each node resolves cluster policies locally for its own endpoints
     - Resolution transforms CiliumNetworkPolicy → eBPF map entries
   - **mapState** (`pkg/policy/mapstate.go` line 98):
     - Indexed container for policy keys/entries using BitLPM Trie data structure
     - Converts policy rules into `PolicyKey` and `PolicyEntry` structures:
       ```
       PolicyKey {
           Prefixlen: uint32          // CIDR prefix length for LPM matching
           Identity: uint32           // Source/dest security identity
           TrafficDirection: uint8    // Ingress (0) or Egress (1)
           Nexthdr: uint8            // Protocol (TCP=6, UDP=17, etc)
           DestPortNetwork: uint16    // Port in network byte order
       }

       PolicyEntry {
           Flags: uint8               // Allow/Deny + LPM prefix length
           Packets: uint64            // Statistics
           Bytes: uint64              // Statistics
       }
       ```

3. **Per-Endpoint Policy Compilation** (`pkg/datapath/loader/template.go` lines 151-253):
   - **ELF map substitutions** create per-endpoint policy maps:
     ```
     Cluster policy CRD:
       "allow ingress from label: app=web"

     Node resolution:
       Find all endpoints with label app=web on THIS node
       Get their security identities (e.g., 1000, 1001, 1002)

     Per-endpoint eBPF map:
       cilium_policy_v2_<ENDPOINT_ID> {
           {prefixlen: 32, identity: 1000, direction: 0, ...} → {action: ALLOW}
           {prefixlen: 32, identity: 1001, direction: 0, ...} → {action: ALLOW}
           {prefixlen: 32, identity: 1002, direction: 0, ...} → {action: ALLOW}
       }
     ```

4. **Why Compilation Failure Doesn't Block Distribution**:
   - **Asynchronous compilation**: Policy distribution (step 1) is decoupled from compilation (step 3)
   - **Distributed compilation**: Each node independently compiles its received policies
   - **Compilation errors are local**: If Node A's clang crashes or kernel verifier rejects a program:
     - Node A logs error, may fall back to previous compiled version
     - Node B and C continue compiling the same policy successfully
     - Policy distribution layer unaffected (doesn't wait for compilation success)

5. **Component Locations**:
   - **Policy watch/distribution**: `pkg/daemon/cmd/daemon.go` → policy.PolicyRepository initialization
   - **Policy resolution**: `pkg/policy/distillery.go` → `DistilledPolicy.AllowsIngressRLocked()`
   - **eBPF map generation**: `pkg/policy/mapstate.go` → `mapState.diffPolicy()` generates diff for maps
   - **Per-endpoint policy application**: `pkg/endpoint/policy.go` → endpoint's BPF programs loaded with its specific policy map

**Key Insight**: Cluster policies are fetched identically on all nodes, but compilation and enforcement happens independently. Each node resolves policies based on its own endpoints, compiles them with its own kernel configuration, and stores them in node-local BPF maps. Compilation failures don't propagate because they're purely local operations with no cluster-wide synchronization.

---

## Q4: eBPF Map Scoping and State Isolation

### How Map State Is Isolated Across Nodes and Between Endpoints

1. **Global Maps (Per-Node, Not Cluster-Wide)**:
   - Exist on **every node** but are **node-local** kernel structures
   - Pinned to `/sys/fs/bpf/tc/globals/` on each node's filesystem
   - Examples:
     - `cilium_call_policy`: Maps endpoint_id → policy program file descriptor
     - `cilium_egresscall_policy`: Maps endpoint_id → egress policy program fd
     - `cilium_lb_backend_<protocol>`: Load-balancing state (per node)
     - `cilium_conntrack_<direction>`: TCP connection tracking (per node)
     - `cilium_nat_<direction>`: NAT state (per node)
   - **Isolation**: Each node's `/sys/fs/bpf` is in its own kernel, inaccessible from other nodes

2. **Per-Endpoint Maps (Node-Local, Endpoint-Specific)**:
   - Map names include endpoint ID: `cilium_policy_v2_<ENDPOINT_ID>`
   - Examples:
     - `cilium_policy_v2_42`: Policy decisions for endpoint ID 42
     - `cilium_egresscall_policy_42`: Egress policy for endpoint 42
     - `cilium_calls_42`: Tail call map for endpoint 42
   - **Max entries**: Configurable per map type (default 16384 for policy maps, `pkg/maps/policymap/policymap.go` line ~50)
   - **Lifecycle**: Created when endpoint starts, deleted when endpoint stops

3. **BPF Filesystem Pinning** (`pkg/datapath/loader/loader.go` line 347):
   - Maps are **pinned** (persisted) at `/sys/fs/bpf/tc/globals/<mapname>`
   - Pinning mechanism:
     - Creates a reference to the kernel's in-memory BPF map
     - Allows maps to survive user-space application restart
     - Maps exist as long as the file exists in `/sys/fs/bpf`
   - **Cleanup**: Called during `Unload()` (line 735 in loader.go)
     - Deletes pinned map files when endpoint is destroyed
     - Prevents stale maps from accumulating

4. **PolicyPlumbingMap Structure** (`pkg/maps/policymap/callmap.go`):
   - **Type**: BPF_MAP_TYPE_PROG_ARRAY (tail call map)
   - **Key**: endpoint_id (uint32)
   - **Value**: program file descriptor (uint32)
   - **Function**: `RemoveGlobalMapping(id)` (deletes endpoint mapping)
   - **How it works**:
     ```
     Ingress packet arrives on veth interface
     ↓
     Main BPF program executes
     ↓
     cilium_call_policy[endpoint_id] lookup
     ↓
     Tail call to endpoint-specific policy program
     ↓
     cilium_policy_v2_<endpoint_id> lookup (policy decision)
     ↓
     Allow/Deny action
     ```

5. **Isolation Mechanisms**:

   **Per-Node Isolation**:
   - Each Cilium agent mounts its own `/sys/fs/bpf` filesystem
   - Maps are kernel objects tied to a single node's network namespace
   - Cross-node access: **Not possible** (kernel modules can't access other nodes' BPF filesystems)
   - State synchronization: **Unnecessary** (each node maintains independent state)

   **Per-Endpoint Isolation**:
   - Endpoint ID is unique per node (1-65535 range)
   - Separate compiled program binary for each endpoint
   - Policy map keyed by endpoint ID in global plumbing map (`cilium_call_policy[endpoint_id]`)
   - TC filters attach to per-endpoint veth interfaces, not shared interfaces
   - **Result**: One endpoint's map corruption cannot affect other endpoints' policy lookups

6. **Fault Isolation in Maps**:
   - **Program crash**: If endpoint 42's BPF program crashes:
     - Only packets destined for endpoint 42 are affected
     - Maps `cilium_policy_v2_42`, `cilium_calls_42` become unreachable
     - Kernel replaces the program (TC filter detaches, re-attaches new version)
     - Other endpoints (43, 44, 45) continue using their own maps
   - **Map out-of-space**: If `cilium_policy_v2_42` fills up (exceeds MaxEntries):
     - New policy entries for endpoint 42 fail to insert
     - Endpoint 42's traffic falls back to default (usually DENY)
     - Other endpoints' maps unaffected
   - **Namespace isolation**: Each pod runs in its own network namespace
     - eBPF programs access maps via current namespace context
     - Maps are never shared between namespaces

**Component Locations**:
   - Policy map definitions: `pkg/maps/policymap/policymap.go`
   - Call map (plumbing): `pkg/maps/policymap/callmap.go`
   - Map pinning/loading: `pkg/datapath/loader/loader.go` lines 347, 735
   - Map initialization: `pkg/datapath/loader/objects.go`
   - Endpoint-specific map management: `pkg/endpoint/policy.go`

**Key Insight**: eBPF maps are scoped at two levels: (1) per-node via kernel filesystem isolation, and (2) per-endpoint via unique map names and tail call plumbing. Maps cannot be shared between nodes (kernel filesystem boundary) or between endpoints (unique IDs). Failures in one map (out-of-space, corruption, deletion) cannot cascade to other endpoints because each has its own isolated map instance.

---

## Evidence

### File References

**Agent and Daemon Initialization:**
- `pkg/daemon/main.go` - Agent entrypoint with Hive DI
- `pkg/daemon/cmd/daemon.go` (lines 1-150) - Daemon struct with loader, policy, compilationLock
- `install/kubernetes/cilium/templates/cilium-agent/daemonset.yaml` (lines 126, 435-765) - DaemonSet definition and init containers

**eBPF Compilation and Loading:**
- `pkg/datapath/loader/loader.go` (lines 382, 511, 347, 735) - Loader interface, Reinitialize, reloadEndpoint, pinning, cleanup
- `pkg/datapath/loader/base.go` (line 382) - Reinitialize entry point
- `pkg/datapath/loader/compile.go` (lines 170, 266, 331, 336, 364, 397, 135) - compile(), compileDatapath(), specialized compilation, getBPFCPU()
- `pkg/datapath/loader/template.go` (lines 151-253, 226) - ELF variable/map substitutions
- `pkg/datapath/loader/objects.go` - BPF object file management

**Policy Distribution and Translation:**
- `pkg/policy/policy.go` - PolicyRepository (cluster-wide policy store)
- `pkg/policy/distillery.go` (line 16) - policyCache (per-identity policy resolution)
- `pkg/policy/mapstate.go` (line 98) - mapState (policy to BPF map conversion)
- `pkg/endpoint/policy.go` - Per-endpoint policy application

**eBPF Maps:**
- `pkg/maps/policymap/policymap.go` (line ~50) - PolicyMap structure and max entries
- `pkg/maps/policymap/callmap.go` - PolicyPlumbingMap (tail call plumbing map)
- `pkg/maps/` - All map type definitions with pinning/lifecycle management

### Key Functions and Structures

| Component | Function/Struct | Line | Purpose |
|-----------|-----------------|------|---------|
| Loader | `Reinitialize()` | base.go:382 | Orchestrates per-node eBPF compilation |
| Loader | `reloadEndpoint()` | loader.go:511 | Loads and attaches eBPF program to endpoint |
| Compilation | `compile()` | compile.go:170 | Low-level clang compilation with kernel-specific flags |
| Compilation | `getBPFCPU()` | compile.go:135 | Kernel version detection for BPF ISA selection |
| Template | `ELFVariableSubstitutions()` | template.go:226 | Injects per-endpoint constants (IP, ID, labels) |
| Template | `ELFMapSubstitutions()` | template.go:151 | Rewrites map names per-endpoint |
| Policy | `PolicyRepository` | policy.go | Cluster-wide policy store per node |
| Policy | `policyCache` | distillery.go:16 | Per-identity resolved policy cache |
| Policy | `mapState` | mapstate.go:98 | Policy to BPF map key/value conversion |
| Maps | `PolicyMap` | policymap.go | BPF_MAP_TYPE_HASH_OF_MAPS for policy decisions |
| Maps | `PolicyPlumbingMap` | callmap.go | BPF_MAP_TYPE_PROG_ARRAY for endpoint tail calls |
| Daemon | `Daemon.loader` | daemon.go:126 | Per-node loader instance |
| Daemon | `Daemon.compilationLock` | daemon.go:121 | Synchronizes concurrent compilations |
| DaemonSet | init containers | daemonset.yaml:435-765 | Per-node BPF filesystem mount, sysctl tuning, state cleanup |

### Isolation Boundaries

1. **Kernel Filesystem**: `/sys/fs/bpf/` is node-local kernel filesystem
2. **Network Namespace**: Each endpoint (pod) runs in isolated network namespace
3. **Endpoint ID**: Unique per node (1-65535), embedded in map names
4. **BPF Program Attachment**: TC filters attached only to per-endpoint veth interfaces
5. **DaemonSet Scheduling**: One pod per node via DaemonSet controller
6. **Compilation Lock**: Per-node mutex prevents concurrent compilation races
7. **PolicyRepository**: Each node maintains independent policy watch and resolution
8. **Map Pinning**: Maps persisted in `/sys/fs/bpf/tc/globals/` (kernel filesystem)

