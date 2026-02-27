# Cilium eBPF Datapath Subsystem - Handoff Documentation

**Document Version:** 1.0
**Cilium Version:** v1.16.5
**Date:** 2026-02-24

---

## Table of Contents
1. [Purpose](#1-purpose)
2. [Dependencies](#2-dependencies)
3. [Relevant Components](#3-relevant-components)
4. [Failure Modes](#4-failure-modes)
5. [Testing](#5-testing)
6. [Debugging](#6-debugging)
7. [Adding a New Hook](#7-adding-a-new-hook)

---

## 1. Purpose

### What Problem Does the eBPF Datapath Solve?

The eBPF datapath is the **core execution engine** that implements Cilium's networking and security policies at the kernel level. It solves several critical problems:

1. **High-Performance Policy Enforcement:** Traditional iptables-based firewalls have linear lookup performance and can't efficiently express complex policy logic. The eBPF datapath executes policy checks in kernel space with O(1) or O(log n) map lookups, avoiding expensive context switches between kernel and userspace.

2. **Dynamic Network Policy:** Cilium uses identity-based (rather than IP-based) policies. The eBPF datapath performs real-time policy lookups against dynamically updated maps as endpoints join/leave the cluster, without requiring userspace packet interception.

3. **Transparent Service Mesh:** eBPF socket-level hooks (`cgroup/connect4`, `cgroup/sendmsg4`, etc. in `bpf_sock.c`) enable transparent load-balancing and service mesh without requiring sidecar proxies, reducing latency and resource overhead.

4. **In-Kernel NAT and Load-Balancing:** Rather than delegating to userspace proxies, the datapath implements SNAT, DNAT, and load-balancing directly in eBPF programs (via `lib/nat.h` and `lib/lb.h`).

5. **Encryption and Tunneling:** The datapath handles IPSec encryption, WireGuard integration, and VXLAN overlays entirely in-kernel via conditional eBPF programs.

6. **Connection Tracking:** Maintains stateful firewall capabilities with TCP connection state tracking in kernel BPF maps, enabling asymmetric policies based on connection direction.

### Why eBPF Instead of Traditional Approaches?

| Approach | Latency | Flexibility | Integration | Memory |
|----------|---------|-------------|-------------|--------|
| **iptables** | 10-100µs per rule | Limited policy logic | Kernel tables only | Large (many rules) |
| **userspace proxies** | 100-1000µs (context switch) | Highly flexible | Application layer | Very high (process overhead) |
| **eBPF datapath** | <1µs (in-kernel) | Extensible via tail calls | Kernel + userspace coordination | Minimal (map-based) |

eBPF provides a **programmable kernel** without:
- Kernel recompilation (dynamic loading)
- Userspace context switches (in-kernel execution)
- Hard-coded features (tail calls allow dynamic program composition)
- Performance penalties (kernel-level operation)

### Key Responsibilities

The eBPF datapath subsystem is responsible for:

1. **Network Policy Enforcement:** Filtering packets based on security identities and L3/L4 rules
2. **Service Load-Balancing:** Distributing traffic across endpoints (ClusterIP, NodePort, ExternalIP)
3. **NAT (Network Address Translation):** SNAT for egress, DNAT for ingress traffic
4. **Connection Tracking:** Stateful firewall with TCP state machine
5. **Endpoint Routing:** Routing packets between containers/VMs and the host/network
6. **Tunneling & Encapsulation:** VXLAN overlays, IPSec, WireGuard integration
7. **L7 Proxy Integration:** Redirecting traffic to userspace Envoy proxy when needed
8. **Metrics & Monitoring:** Collecting per-packet statistics and debug events

### Integration with Kubernetes Networking

```
User Container → Linux Network Stack
    ↓
[TC Ingress Hook] cil_from_container (bpf_lxc.c)
    ↓
[Policy Check] POLICY_CALL_MAP → per-endpoint policy program
    ↓
[Identity Lookup] ipcache map → source security label
    ↓
[Route Lookup] ENDPOINTS_MAP → destination endpoint location
    ↓
[NAT/LB] SNAT_MAPPING, LB*_SERVICES_MAP
    ↓
[Tunnel Encapsulation] (if overlay) → kernel stack
    ↓
Physical NIC → Remote Pod via Kubernetes network fabric
```

The datapath seamlessly bridges:
- **Container endpoints** (network namespaces) ↔ **Host network** (kernel)
- **Pod-to-pod communication** ↔ **Pod-to-service communication**
- **Kubernetes service abstraction** (ClusterIP, NodePort) ↔ **Actual endpoints**

---

## 2. Dependencies

### Internal Dependencies: Upstream (What Calls the Datapath)

**Control Plane → Datapath:**
- `/workspace/pkg/endpoint/bpf.go` (EndpointManager) → Triggers endpoint program generation and loading when policies change
- `/workspace/pkg/datapath/loader/loader.go` (Loader) → Main orchestrator for program compilation and attachment
- `/workspace/pkg/daemon/daemon.go` (Cilium daemon) → Coordinates policy updates and datapath reloads
- `/workspace/pkg/identity/identity.go` → Provides security identity labels used in policy decisions
- `/workspace/pkg/policy/policy.go` → Computes network policies, passed to datapath for enforcement

**Configuration Flows:**
1. Endpoint created → `/workspace/pkg/endpoint/endpoint.go` → calls `endpoint.Regenerate()` → triggers `/workspace/pkg/datapath/loader/loader.go:Reinitialize()`
2. Policy changed → `/workspace/pkg/policy/repository.go` → notifies all affected endpoints → triggers regeneration
3. Service added → `/workspace/pkg/service/service.go` → updates LB maps (`/workspace/pkg/maps/lbmap/`) → datapath picks up changes

### Internal Dependencies: Downstream (What the Datapath Calls)

**Datapath → Support Systems:**
- `/workspace/pkg/maps/` (Map management) → Provides map lifecycle (create, update, delete, cleanup)
  - `policymap/` - Policy enforcement maps
  - `nat/` - NAT translation maps
  - `lbmap/` - Load balancer maps
  - `ctmap/` - Connection tracking maps
  - `ipcache/` - IP-to-identity cache
  - `lxcmap/` - Endpoint information maps

- `/workspace/pkg/bpf/` (eBPF wrapper library)
  - `collection.go` - Loads ELF files, handles verifier errors
  - `map_linux.go` - Per-CPU maps, caching, sync retry logic
  - `bpffs_linux.go` - BPF filesystem pinning/unpinning

- `/workspace/pkg/sysctl/` → Configures kernel parameters (e.g., `net.ipv4.conf.*.rp_filter`, `net.ipv4.ip_forward`)

- `/workspace/pkg/netlink/` → Low-level netlink operations for TC filter attachment, device enumeration

- `/workspace/pkg/monitor/` → Reports debug events and metrics back to Cilium agent for monitoring

### Kernel API Dependencies

**BPF System Calls:**
- `bpf(BPF_PROG_LOAD)` - Load eBPF programs into kernel (via `pkg/bpf/collection.go`)
- `bpf(BPF_MAP_CREATE)` - Create BPF maps (via `pkg/maps/`)
- `bpf(BPF_OBJ_PIN)` / `bpf(BPF_OBJ_GET)` - Pin/unpin objects to BPF filesystem (via `pkg/bpf/bpffs_linux.go`)

**Netlink Protocol:**
- `RTM_NEWQDISC` / `RTM_DELQDISC` - Create/delete qdisc (clsact) for TC
- `RTM_NEWTFILTER` / `RTM_DELTFILTER` - Attach/detach TC filters (via `pkg/datapath/loader/tc.go`)
- `RTM_NEWLINK` / `RTM_GETLINK` - Interface enumeration and XDP attachment (via `pkg/datapath/loader/xdp.go`)

**Cgroup v2 APIs:**
- `BPF_PROG_ATTACH` to `/dev/cgroup/...` - Attach socket programs (via `bpf_sock.c`)

**BPF Program Types:**
- `BPF_PROG_TYPE_SCHED_CLS` - TC programs (main datapath)
- `BPF_PROG_TYPE_XDP` - XDP early filtering
- `BPF_PROG_TYPE_CGROUP_SOCK_ADDR` - Socket address policy hooks
- `BPF_PROG_TYPE_SK_MSG` - Socket message handling

**BPF Map Types:**
- `BPF_MAP_TYPE_HASH` - Endpoint lookup, service lookup
- `BPF_MAP_TYPE_LRU_HASH` - Connection tracking, NAT (auto-eviction)
- `BPF_MAP_TYPE_LPM_TRIE` - Policy (prefix matching), IP cache (CIDR matching)
- `BPF_MAP_TYPE_PROG_ARRAY` - Tail call maps (program composition)
- `BPF_MAP_TYPE_PERCPU_HASH` - Metrics (per-CPU counters)

**BPF Helpers Used:**
- `bpf_map_lookup_elem()` - Read from maps (policy, endpoint, NAT, etc.)
- `bpf_map_update_elem()` - Write to maps (connection tracking, metrics)
- `bpf_tail_call()` - Jump to next eBPF program
- `bpf_redirect()` - Redirect packet to interface
- `bpf_clone_redirect()` - Duplicate packet to interface
- `bpf_perf_event_output()` - Send trace/debug events
- `bpf_get_current_pid_tgid()` - Get process ID (socket programs)
- `bpf_probe_read()` - Read kernel memory safely

### External/Ecosystem Dependencies

- **Cilium CLI** (`cilium-cli`) → Uses datapath for policy validation
- **Kubernetes CNI plugin** → Invokes Cilium binary for pod networking setup
- **NetworkPolicy/CiliumNetworkPolicy** CRDs → Converted to datapath policies
- **etcd/Consul** → Stores policy state, retrieved by control plane
- **Monitoring systems** (Prometheus, etc.) → Consume datapath metrics via `/metrics`

### Go ↔ C Boundary

The datapath exists at a critical **Go-to-C transition point:**

```
Go Control Plane
    ↓
Policy Resolution (Go)
    ↓
[BOUNDARY: pkg/datapath/loader/]
    ↓
C Program Generation & Compilation (C + clang)
    ↓
ELF Object Loading (bpf() syscalls)
    ↓
Kernel eBPF Execution (Kernel-only)
    ↓
[BOUNDARY: bpf maps, netlink updates]
    ↓
Go Runtime Observability (metrics, monitoring)
```

**Data Exchange Mechanisms:**
1. **Configuration Headers:** Go generates `lxc_config.h`, `node_config.h`, etc. with C #define macros (see `pkg/datapath/loader/template.go`)
2. **BPF Maps:** Shared memory regions created by Go, read/written by both Go and eBPF programs
3. **Netlink Events:** Go sends TC filter updates, eBPF programs are attached/detached
4. **Debug Events:** eBPF programs output trace data via perf buffers, Go reads and logs them

---

## 3. Relevant Components

### Core Directory Structure

```
/workspace/
├── bpf/                           # All eBPF C source code and headers
│   ├── bpf_lxc.c                 # Container/pod network policy enforcement
│   ├── bpf_host.c                # Host-side network processing
│   ├── bpf_xdp.c                 # XDP early filtering
│   ├── bpf_sock.c                # Socket-level policy and load-balancing
│   ├── bpf_overlay.c             # VXLAN/overlay network support
│   ├── bpf_wireguard.c           # WireGuard integration
│   ├── bpf_network.c             # Network namespace handling
│   ├── lib/                      # Shared eBPF library headers
│   │   ├── common.h              # Core packet structures, macros
│   │   ├── policy.h              # Policy lookup implementation
│   │   ├── nat.h                 # SNAT/DNAT implementation
│   │   ├── lb.h                  # Load-balancing logic
│   │   ├── conntrack.h           # Connection tracking
│   │   ├── nodeport.h            # NodePort/ClusterIP service handling
│   │   ├── egress_gateway.h      # Egress gateway routing
│   │   ├── host_firewall.h       # Host-level firewalling
│   │   ├── tailcall.h            # Tail call infrastructure
│   │   ├── maps.h                # Map definitions and helpers
│   │   ├── ipv4.h, ipv6.h        # L3 processing
│   │   ├── l4.h                  # L4 processing (TCP, UDP, etc.)
│   │   ├── drop.h                # Drop reason codes
│   │   ├── trace.h               # Packet tracing/monitoring
│   │   ├── encap.h               # Tunneling encapsulation
│   │   └── encrypt.h             # IPSec encryption
│   ├── include/bpf/              # Context and BPF API headers
│   │   ├── ctx/skb.h             # SKB context (TC programs)
│   │   ├── ctx/xdp.h             # XDP context
│   │   ├── section.h             # __section macro definitions
│   │   └── tailcall.h            # Tail call assembly macros
│   ├── custom/                   # User-defined custom programs
│   └── tests/                    # BPF unit test programs (72 test files)
│
├── pkg/datapath/                 # Go datapath management layer
│   ├── loader/                   # eBPF program compilation and loading
│   │   ├── loader.go             # Main loader orchestration (650+ lines)
│   │   ├── compile.go            # Clang compilation invocation
│   │   ├── base.go               # Loader initialization and configuration
│   │   ├── tc.go                 # Legacy TC hook attachment
│   │   ├── tcx.go                # Modern TCX hook attachment (kernel 5.11+)
│   │   ├── netkit.go             # Netkit device handling
│   │   ├── xdp.go                # XDP program attachment and management
│   │   ├── cache.go              # Template object caching (hash-based)
│   │   ├── netlink.go            # Low-level netlink operations
│   │   ├── template.go           # Header file generation
│   │   ├── loader_test.go        # Loader unit tests
│   │   ├── *_test.go             # Other component tests
│   │   └── prefilter/            # Pre-filter configuration
│   ├── maps/                     # eBPF map lifecycle management
│   │   ├── policymap/            # Policy enforcement maps
│   │   ├── nat/                  # NAT translation maps
│   │   ├── lbmap/                # Load balancer maps
│   │   ├── ctmap/                # Connection tracking maps
│   │   ├── ipcache/              # IP-to-identity cache
│   │   ├── lxcmap/               # Endpoint information maps
│   │   └── callsmap/             # Tail call program arrays
│   ├── linux/                    # Linux-specific operations
│   │   ├── probes/               # Kernel feature detection
│   │   └── config.go             # Runtime configuration
│   └── types/                    # Interface definitions
│
├── pkg/bpf/                      # eBPF wrapper library for Go
│   ├── collection.go             # ELF loading, verifier error handling (~500 lines)
│   ├── map_linux.go              # Map operations, caching, sync (~1000 lines)
│   ├── bpffs_linux.go            # BPF filesystem operations
│   ├── link.go                   # Link management (pin, unpin, update)
│   ├── endpoint.go               # Per-endpoint BPF state
│   └── *_test.go                 # Unit tests
│
├── pkg/endpoint/                 # Endpoint management (triggers regeneration)
│   ├── bpf.go                    # eBPF integration
│   ├── policy.go                 # Policy-to-eBPF conversion
│   ├── regeneration/             # Program regeneration orchestration
│   └── endpoint.go               # Core endpoint struct (~2000 lines)
│
├── pkg/maps/                     # Map definitions and operations
│   ├── policymap/                # Policy map interface
│   ├── nat/                      # NAT map interface
│   ├── lbmap/                    # LB map interface
│   ├── ctmap/                    # Conntrack map interface
│   ├── ipcache/                  # IP cache interface
│   └── */                        # Other map types
│
├── pkg/policy/                   # Policy compilation
│   ├── policy.go                 # Network policy engine
│   ├── repository.go             # Policy storage and retrieval
│   └── l4.go                     # L4 policy specifics
│
├── pkg/identity/                 # Security identity management
│   ├── identity.go               # Identity allocation
│   └── cache.go                  # Identity caching
│
├── pkg/monitor/                  # Monitoring and debug infrastructure
│   ├── datapath_debug.go         # Debug event codes
│   └── monitor.go                # Event collection
│
├── pkg/service/                  # Kubernetes service management
│   └── service.go                # Service-to-datapath integration
│
├── pkg/sysctl/                   # Kernel parameter configuration
│   └── sysctl.go                 # sysctl writes
│
├── pkg/netlink/                  # Netlink utilities
│   └── netlink.go                # Device operations
│
└── tests/                        # Integration tests
    ├── integration/
    │   └── datapath/             # Datapath-specific integration tests
    └── unit/                     # Unit test infrastructure
```

### Critical Files for Understanding eBPF Datapath

#### **1. eBPF Program Entry Points**

- **`bpf_lxc.c`** (2,500+ lines)
  - `cil_from_container()` - Ingress from pod (line 1443)
  - `cil_to_container()` - Egress to pod (line 2281)
  - Policy lookup and enforcement
  - IPv4/IPv6 routing, NAT, LB

- **`bpf_host.c`** (1,700+ lines)
  - `cil_from_netdev()` - Ingress from physical network (line 1286)
  - `cil_to_netdev()` - Egress to physical network (line 1357)
  - `cil_from_host()` - From host namespace (line 1343)
  - `cil_to_host()` - To host namespace (line 1628)
  - Host firewall, ARP handling

- **`bpf_xdp.c`** (300+ lines)
  - `cil_xdp_entry()` - XDP fast-path filtering (line 361)
  - CIDR-based pre-filtering before kernel stack

- **`bpf_sock.c`** (30,000+ lines)
  - `cil_sock4_connect()` - Socket address rewriting (line 410)
  - `cil_sock4_pre_bind()` - Bind-time restrictions (line 510)
  - `cil_sock4_post_bind()` - Post-bind tracking (line 466)
  - `cil_sock4_sendmsg()` - Send-time policy (line 570)
  - And IPv6 equivalents

#### **2. eBPF Library Headers (Policy/Lookup Logic)**

- **`lib/common.h`** (1,000+ lines)
  - Core data structures (`endpoint_key`, `policy_key`, `endpoint_info`)
  - Tail call slot definitions (50 slots: `CILIUM_CALL_*`)
  - Helper functions for packet processing

- **`lib/policy.h`** (250+ lines)
  - Policy lookup function: `policy_can_access()` (line ~100-150)
  - Identity validation
  - Per-endpoint policy enforcement

- **`lib/nat.h`** (1,500+ lines)
  - SNAT/DNAT lookup and application
  - Connection-aware NAT

- **`lib/lb.h`** (1,500+ lines)
  - Service lookup
  - Per-service backend selection
  - Load-balancing algorithms

- **`lib/conntrack.h`** (1,100+ lines)
  - TCP state tracking
  - Connection establishment/teardown

- **`lib/nodeport.h`** (2,400+ lines)
  - Kubernetes service implementation
  - NodePort, ClusterIP, ExternalIP handling

#### **3. Go Loader and Compilation**

- **`pkg/datapath/loader/loader.go`** (650+ lines)
  - `newLoader()` - Initialize loader
  - `Reinitialize()` - Main entry point for datapath recompilation (line ~200)
  - `ReinitializeXDP()` - XDP-specific setup (line ~500)
  - `reinitializeOverlay()` - Overlay network setup
  - `reinitializeIPSec()` - IPSec tunnel configuration
  - `ReloadDatapath()` - Program attachment
  - `reloadHostDatapath()` - Host program reload (line ~325)

- **`pkg/datapath/loader/compile.go`** (300+ lines)
  - `compile()` - Clang invocation with BPF target (line ~50-150)
  - Handles compilation errors, verifier log output
  - Debug preprocessed C and assembly generation

- **`pkg/datapath/loader/template.go`** (200+ lines)
  - `WriteNodeConfig()` - Generate node_config.h
  - `WriteNetdevConfig()` - Generate netdev_config.h
  - `WriteFilterConfig()` - Generate filter_config.h

- **`pkg/datapath/loader/cache.go`** (200+ lines)
  - Template object caching mechanism
  - Hash-based lookup for pre-compiled programs

#### **4. Go BPF Wrapper Library**

- **`pkg/bpf/collection.go`** (500+ lines)
  - `LoadCollectionSpec()` - Load ELF, handle verifier errors (line ~100-350)
  - Verifier retry logic with exponential buffer growth (line ~256-349)
  - Tail call validation, unreachable program removal
  - Map compatibility detection

- **`pkg/bpf/map_linux.go`** (1,000+ lines)
  - `Map` struct - Core map wrapper
  - Per-CPU map support
  - Caching with sync retry
  - Pressure metrics

- **`pkg/bpf/link.go`** (100 lines)
  - Link lifecycle (update, unpin)
  - Pinned link fallback mechanisms

#### **5. Hook Attachment**

- **`pkg/datapath/loader/tc.go`** (300+ lines)
  - `attachSKBProgram()` - Attach TC programs (line ~150-200)
  - Legacy clsact qdisc creation
  - TC filter insertion via netlink

- **`pkg/datapath/loader/tcx.go`** (200+ lines)
  - `attachTCXProgram()` - Modern TCX attachment (kernel 5.11+)
  - Link update with fallback
  - Defunct link detection

- **`pkg/datapath/loader/xdp.go`** (300+ lines)
  - `attachXDPProgram()` - XDP attachment (line ~200-275)
  - bpf_link (kernel 5.7+) vs netlink (legacy) modes
  - XDP program discovery and cleanup

#### **6. Map Management**

- **`pkg/maps/policymap/`**
  - Policy enforcement map interface
  - Per-endpoint policy program array

- **`pkg/maps/nat/`**
  - NAT map management
  - IPv4/IPv6 SNAT/DNAT lookup tables

- **`pkg/maps/ctmap/`**
  - Connection tracking map definitions
  - Per-endpoint, per-protocol (IPv4/IPv6) variants

- **`pkg/maps/lbmap/`**
  - Service load-balancer maps
  - Backend selection state

#### **7. Kernel Feature Detection**

- **`pkg/datapath/linux/probes/probes.go`** (500+ lines)
  - `ProbeSystemConfig()` - Detect kernel capabilities
  - `bpftool -j feature probe` integration
  - Required/optional feature checking

#### **8. Data Structures and Context**

- **`bpf/include/bpf/ctx/skb.h`**
  - TC program context structure wrapping
  - Packet buffer access methods

- **`bpf/include/bpf/ctx/xdp.h`**
  - XDP context structure wrapping
  - Fast-path packet access

### Key Data Structures

**eBPF-Side (C):**

```c
// Endpoint identification
struct endpoint_key {
    __u32 ip4;              // IPv4 address
    __u32 family;           // Address family
    __u32 key;              // Endpoint ID
};

struct endpoint_info {
    __u32 ifindex;          // Interface index
    __u16 lxc_id;           // Endpoint ID
    __u32 sec_label;        // Security identity
};

// Policy lookup
struct policy_key {
    struct bpf_lpm_trie_key lpm_key;  // For prefix matching
    __u32 sec_label;        // Source security identity
    __u16 dport;            // Destination port
    __u8 proto;             // Protocol
    __u8 egress;            // Direction
};

struct policy_entry {
    __u64 packets;          // Metrics
    __u64 bytes;
    __u32 proxy_port;       // For L7 LB
    __u8 deny;              // Drop if set
    __u8 auth_type;         // Auth requirement
};
```

**Go-Side (Go):**

```go
// From pkg/datapath/loader/loader.go
type loader struct {
    cfg Config
    nodeConfig atomic.Pointer[...]      // Node-wide configuration
    templateCache *objectCache          // Pre-compiled program cache
    ipsecMu lock.Mutex
    hostDpInitialized chan struct{}     // Sync point
    // ... more fields for sysctl, prefilter, locks
}

// From pkg/bpf/map_linux.go
type Map struct {
    m *ebpf.Map                         // Underlying eBPF map
    key, value MapKey, MapValue         // Type wrappers
    cache map[string]*cacheEntry        // Lookup cache
    enableSync bool
    withValueCache bool
}
```

### Maps and Their Purposes

| Map Name | Type | Purpose | Key Size | Value Size | Managed By |
|----------|------|---------|----------|------------|------------|
| `ENDPOINTS_MAP` | HASH | Endpoint lookup by IP | 8 bytes | 16 bytes | `pkg/maps/lxcmap/` |
| `POLICY_CALL_MAP` | PROG_ARRAY | Per-endpoint policy programs | 4 bytes | 4 bytes | `pkg/maps/policymap/` |
| `cilium_policy_*` | LPM_TRIE | Per-endpoint policies | variable | 16 bytes | `pkg/maps/policymap/` |
| `cilium_ct4_*` | LRU_HASH | IPv4 connection tracking | 24 bytes | 40 bytes | `pkg/maps/ctmap/` |
| `cilium_ct6_*` | LRU_HASH | IPv6 connection tracking | 48 bytes | 40 bytes | `pkg/maps/ctmap/` |
| `SNAT_MAPPING_IPv4/6` | LRU_HASH | NAT translations | 24/48 bytes | 24 bytes | `pkg/maps/nat/` |
| `LB4_SERVICES_MAP_V2` | HASH | IPv4 services | 8 bytes | 16 bytes | `pkg/maps/lbmap/` |
| `LB6_SERVICES_MAP_V2` | HASH | IPv6 services | 24 bytes | 48 bytes | `pkg/maps/lbmap/` |
| `ipcache` | LPM_TRIE | IP → security identity | variable | 16 bytes | `pkg/maps/ipcache/` |
| `METRICS_MAP` | PERCPU_HASH | Packet counters | 8 bytes | variable | `pkg/maps/metrics/` |

### Program Compilation and Attachment Flow

```
User/Pod Created → Control Plane
    ↓
endpoint.Regenerate() [pkg/endpoint/endpoint.go]
    ↓
datapath.Reinitialize() [pkg/datapath/loader/loader.go:200]
    ↓
WriteNodeConfig() [template.go]
WriteNetdevConfig() [template.go]
    ↓
compile() [compile.go] → clang -target bpf bpf_lxc.c -o bpf_lxc.o
    ↓
LoadCollectionSpec() [pkg/bpf/collection.go] → Load ELF
    ↓
ResolvePrograms() [bpf/collection.go] → Extract section names, tail call info
    ↓
CreateMaps() [bpf/map_linux.go] → Create/pin maps
    ↓
attachSKBProgram() [tc.go] → Attach to device via TC/TCX
    ↓
attachXDPProgram() [xdp.go] → Attach to device via XDP (optional)
    ↓
Program Loaded and Running ✓
```

---

## 4. Failure Modes

### eBPF Program Loading Failures

#### **4.1 eBPF Verifier Failures**

**Symptoms:** Program fails to load, error message shows verifier rejection

**Root Causes:**
1. **Unbounded loops:** eBPF programs must be provably terminating (kernel 5.3+ allows bounded loops)
2. **Out-of-bounds memory access:** Verifier can't prove all memory accesses are within bounds
3. **Unreachable code:** Dead code paths confuse the verifier
4. **Stack overflow:** Local variables exceed 512-byte limit
5. **Helper function misuse:** Wrong argument types, or calling unsupported helpers on older kernels

**Handling:**
- Located in `pkg/bpf/collection.go:256-349`
- Verifier error log starts at 4 MiB buffer (line ~260)
- If truncated (`VerifierError.Truncated == true`), quadruples buffer and retries
- Retries up to 5 times before giving up with truncated output
- Error output sent to stderr for debugging (line ~349)

**Recovery:**
- Compilation fails, program not loaded
- Falls back to previous version of program (if previously loaded)
- Cilium continues with old policies until fix is applied
- New code must be verified offline and committed

**Prevention:**
- Use `__always_inline` for helper functions (reduces stack depth)
- Keep loops bounded (`#pragma unroll`)
- Use BPF `if` guards to prove memory safety
- Test with kernel BPF verifier locally (`llvm-objdump`, `bpftool prog dump`)

#### **4.2 Map Incompatibility Errors**

**Symptoms:** Program loads but fails to use maps, or hangs on map operations

**Root Causes:**
1. **Map definition change:** Changed map size/type without cleanup (line ~160 in `collection.go`)
2. **Pinned map with different layout:** Old map persists with incompatible schema
3. **Map in use:** Kernel prevents deletion/recreation while in use

**Handling:**
- Detected in `LoadCollectionSpec()` → `mapIncompatible := ...` (line ~160)
- Incompatible maps are unpinned via `UnpinLink()` and recreated
- New maps created with correct schema
- Automatic recovery with `CILIUM_PIN_REPLACE` flag (line ~180)

**Recovery:**
- Maps are automatically recreated with new schema
- Existing data is lost (acceptable for most maps - ephemeral state)
- Policy maps rebuilt from control plane state
- NAT/CT maps cleared (new connections will re-establish state)

**Prevention:**
- Never change map sizes without coordination
- Use versioning in pinned map names
- Test map schema changes in staging first
- Document all map layout changes in commit messages

#### **4.3 Program Type Mismatches**

**Symptoms:** Program fails to attach: "Invalid argument" or "Unsupported"

**Root Causes:**
1. **Wrong program type:** Trying to attach XDP program as TC filter
2. **Missing kernel feature:** Kernel doesn't support TCX, falling back to legacy TC
3. **Incompatible instruction set:** ISA doesn't support CPU (e.g., 32-bit on 64-bit kernel)

**Handling:**
- TC/TCX fallback logic (line ~150-200 in `tc.go`)
- Tries TCX first (kernel 5.11+)
- Falls back to legacy TC if TCX unavailable
- XDP: tries bpf_link (kernel 5.7+), falls back to netlink (lines ~230-275 in `xdp.go`)

**Recovery:**
- Automatic fallback to older mechanisms
- Program still functions, possibly with different performance
- User notified via logs of fallback mechanism used
- No manual intervention required

---

### Map-Related Failures

#### **4.4 Map Size Exhaustion**

**Symptoms:** Map updates fail, "Map full" errors in logs

**Root Causes:**
1. **Connection tracking explosion:** Millions of connections in CT maps
2. **Endpoint explosion:** More endpoints than map capacity
3. **Service explosion:** Too many load-balanced services
4. **SNAT port exhaustion:** More unique source ports needed than available

**Handling:**
- LRU maps (CT, NAT) automatically evict least-recently-used entries
- Policy maps per-endpoint (distributed across many maps, not global)
- Metrics show map pressure via `bpf_map_update_element()` return codes
- Errors logged with context (which endpoint, which map)

**Recovery:**
- **LRU maps:** Automatic eviction of old entries (typically succeeds)
- **Per-endpoint policy maps:** Can resize dynamically via endpoint regeneration
- **Manual:** Increase kernel memory limits, increase map sizes, scale horizontally (more nodes)

**Prevention:**
- Monitor map pressure via Cilium metrics
- Set appropriate map sizes at startup (`BPF_CT4_GLOBAL_TCP_MAX`, etc.)
- Use ClusterIP load-balancing to reduce endpoint-to-endpoint connections
- Implement connection limits via security policies

#### **4.5 Map Update Race Conditions**

**Symptoms:** Inconsistent policy enforcement, stale NAT translations, connection leaks

**Root Causes:**
1. **Policy update during packet processing:** Packet sees partial policy
2. **Map replacement without synchronization:** Old programs still running with new map IDs
3. **Concurrent map writers:** Multiple Go routines writing to same map entry

**Handling:**
- Tail call maps updated AFTER kernel load (line ~120 in `netlink.go`)
- Link update atomicity: `bpf_link.Update()` is atomic (TCX, kernel 5.8+)
- Per-CPU maps isolate writer conflicts
- Policy programs are per-endpoint (no cross-endpoint contention)

**Recovery:**
- Packets with partial policy state drop with visible error (metrics)
- Policy revalidated on retry
- Long-lived connections may see transient policy changes but remain open

**Prevention:**
- Always attach all tail calls before activating programs
- Test concurrent policy updates in benchmarks
- Monitor for unexpected drops during policy rollout

---

### Kernel Compatibility Failures

#### **4.6 Kernel Verifier Regression**

**Symptoms:** Code that compiled on one kernel fails on another

**Root Causes:**
1. **Stricter verifier:** Newer kernel rejects previously-valid code
2. **Removed helpers:** Kernel version doesn't have required BPF helper
3. **Breaking BPF ABI:** Kernel changed map/program structure layout

**Handling:**
- Probed at startup via `ProbeSystemConfig()` (line ~50 in `probes.go`)
- `bpftool -j feature probe` run to detect capability gaps
- Compilation flags adjust based on kernel features (e.g., `ENABLE_JUMBO_FRAMES` if kernel supports it)
- Configuration warns if required features missing

**Recovery:**
- Cilium refuses to start if required features absent
- Upgrade kernel to supported version (documented in Cilium prerequisites)
- Disable features via configuration to match older kernel
- No runtime recovery - requires kernel upgrade or configuration change

**Prevention:**
- Test on target kernel versions before deployment
- Document minimum kernel version for each feature
- Use conditional compilation for optional features
- Run feature probes in CI/CD

#### **4.7 Instruction Set Incompatibility**

**Symptoms:** "Instruction not supported by kernel" during program load

**Root Causes:**
1. **64-bit BPF on 32-bit kernel:** Kernel doesn't support 64-bit instructions
2. **32-bit ALU on old kernel:** Kernel requires compatibility mode
3. **ISA extensions:** BPF code uses unreleased instruction sets

**Handling:**
- Compilation target hardcoded to `-target bpf` (clang chooses correct ISA)
- Code reviewed to avoid newer ISA features
- ISA version constraints in Cilium CI

**Recovery:**
- Program load fails, requires kernel upgrade or code reversion
- No runtime recovery available

**Prevention:**
- Test on minimum kernel version regularly
- Use `llvm-objdump -d` to inspect generated assembly
- Avoid pointer arithmetic that requires 64-bit operations on 32-bit targets

---

### Configuration and Runtime Failures

#### **4.8 Configuration Header Corruption**

**Symptoms:** Program compiles but exhibits wrong behavior (wrong endpoint ID, wrong policies)

**Root Causes:**
1. **Template variable not replaced:** Placeholder like `SECLABEL` not substituted
2. **Config generation race:** Multiple processes writing config simultaneously
3. **File system sync failure:** Config written but not flushed before compilation

**Handling:**
- Config generation in `template.go` uses atomic writes (write-to-temp, rename)
- Compilation lock prevents concurrent compilation (line ~50 in `cache.go`)
- Verification: Compiled object checked for expected symbols

**Recovery:**
- Verifier typically rejects programs with missing macros (undefined symbols)
- Manual: Check generated config files in `/var/run/cilium/` or `/sys/fs/bpf/cilium/`
- Logs show exact config used for compilation
- Manual config cleanup if corrupted

**Prevention:**
- Template generation tests in unit tests
- Config files read-only after generation (no external modification)
- Atomic file operations throughout

#### **4.9 Device Not Found**

**Symptoms:** Program compiles but doesn't attach: "device not found"

**Root Causes:**
1. **Device removed after endpoint creation:** Interface deleted before program attachment
2. **Device name changed:** Endpoint created on `eth0`, later renamed to `eth1`
3. **Device in wrong namespace:** Device in container namespace, not host namespace

**Handling:**
- Device enumeration just before attachment (line ~150 in `loader.go`)
- Graceful skip if device not found (line ~200 in `tc.go`)
- Retry mechanism for transient device unavailability
- Logs indicate which devices received programs

**Recovery:**
- Program attachment skipped for unavailable device
- Next endpoint regeneration will retry
- Pod continues running with policy enforcement on available devices
- If all devices unavailable, endpoint marked unhealthy

**Prevention:**
- Ensure network setup completes before datapath reload
- Test device lifecycle handling in integration tests
- Monitor for repeated device-not-found errors (indicates infrastructure issue)

#### **4.10 Insufficient Kernel Memory**

**Symptoms:** Map creation fails: "Cannot allocate memory"

**Root Causes:**
1. **Too many maps created:** LRU, per-endpoint maps multiply quickly
2. **Maps too large:** Per-endpoint policy map sized for millions of entries
3. **System memory pressure:** Kernel memory already exhausted

**Handling:**
- Map creation wrapped in error handler (line ~220 in `map_linux.go`)
- LRU maps use kernel memory efficiently (auto-eviction)
- Map sizes configurable via `CILIUM_MAP_*` environment variables
- Metrics track memory usage per map

**Recovery:**
- Map creation failure returns error, endpoint stays with old maps
- Next garbage collection attempt may free memory
- Manual: Reduce map sizes via configuration, restart Cilium agent
- Horizontal scaling: Move workloads to other nodes

**Prevention:**
- Pre-size maps based on expected scale
- Monitor kernel memory usage via `/proc/meminfo`
- Set memory limits for BPF subsystem
- Test scaling with expected endpoint/service counts

---

### Debugging Failure Modes

#### **4.11 Missed Tail Calls**

**Symptoms:** Policy not enforced, drops with "missed tail call" error

**Root Causes:**
1. **Program not installed in tail call map:** `POLICY_CALL_MAP[endpoint_id]` empty
2. **Tail call map full:** Can't add more programs
3. **Wrong endpoint ID:** Program tries to call non-existent entry
4. **Race condition:** Program loaded but policy program not yet inserted

**Handling:**
- Tail call validation during load (line ~170 in `collection.go`)
- Programs inserted in POLICY_CALL_MAP after all tail calls resolved
- Ordering: all programs loaded before any activated (line ~120 in `netlink.go`)
- Metrics: `cilium_bpf_program_runtime_micro_seconds{reason="missed_tail_call"}`

**Recovery:**
- Packet dropped with identifiable reason code
- Policy regeneration retry will repopulate tail call maps
- Cilium logs show failed endpoint, user can investigate why

**Prevention:**
- Unit tests validate tail call insertion
- Integration tests verify policy enforcement
- Monitor missed tail call metrics in production

---

## 5. Testing

### Test Infrastructure and Patterns

Cilium uses multiple testing levels for the eBPF datapath:

#### **5.1 Unit Tests (Go)**

**Location:** `/workspace/pkg/datapath/loader/*.test.go`

**Key Test Files:**

- **`loader_test.go`** (299 lines)
  - `TestCompileOrLoadDefaultEndpoint` - Tests standard endpoint compilation
  - `TestCompileOrLoadHostEndpoint` - Tests host endpoint compilation
  - `TestReload` - Tests program reload cycles
  - `TestCompileFailure*` - Tests error handling with context cancellation
  - `TestBPFMasqAddrs` - Tests masquerade address resolution
  - `BenchmarkCompileOnly` - Benchmarks pure compilation time
  - `BenchmarkReplaceDatapath` - Benchmarks full reload cycle

- **`cache_test.go`** - Tests template compilation cache
- **`compile_test.go`** - Tests clang compilation invocation
- **`xdp_test.go`** - Tests XDP program attachment
- **`*_test.go`** - Other component-specific tests

**Test Pattern:**

```go
func TestCompileOrLoadDefaultEndpoint(t *testing.T) {
    // 1. Create test endpoint
    ep := testutils.TestEndpoint()

    // 2. Create dummy network device
    netdev := createDummyLink()
    defer netdev.Delete()

    // 3. Initialize loader
    l := newLoader(cfg)
    defer l.Close()

    // 4. Trigger compilation and loading
    err := l.Reinitialize(ctx, cfg, tunCfg, iptMgr, proxy)

    // 5. Verify program attached
    assert.NoError(t, err)
    verifyProgramAttached(netdev)
}
```

**Test Utilities:**
- `testutils.TestEndpoint()` - Creates a mock endpoint
- `testutils.TestHostEndpoint()` - Creates a host endpoint mock
- `netlink.LinkAdd()` - Creates dummy test interface
- `bpffs` mocking with temporary directories

#### **5.2 BPF Program Tests (C)**

**Location:** `/workspace/bpf/tests/` (72 test files)

**Test Files:**
- `bpf_common_test.c` - Common structure tests
- `bpf_lxc_test.c` - Container program tests
- `bpf_host_test.c` - Host program tests
- `bpf_nat_test.c` - NAT logic tests
- `bpf_lb_test.c` - Load-balancing tests
- And 67 other test programs

**Test Pattern:**

BPF tests use a custom test harness that:
1. Defines test fixtures (mock packet buffers, map entries)
2. Calls eBPF functions with test data
3. Verifies output (returned verdict, modified fields)

Example structure:
```c
// /workspace/bpf/tests/bpf_lxc_test.c
__section("test_")
int test_policy_allow() {
    // Setup test map entries
    __u32 src_label = 1000;
    __u32 dst_label = 2000;

    // Create mock packet
    struct __ctx_buff ctx = {...};

    // Call policy lookup
    int ret = policy_can_access(...);

    // Verify result
    assert(ret == POLICY_ALLOW);
}
```

**Running Tests:**

- BPF tests compiled as standalone objects
- Can be run with BPF test harness tools
- Validation of policy logic independent of kernel

#### **5.3 Integration Tests**

**Location:** `/workspace/tests/integration/datapath/` (estimated)

**Test Patterns:**

1. **Policy Enforcement Tests**
   - Create network policies
   - Create pods with labels
   - Verify traffic allowed/denied per policy
   - Test with actual container creation

2. **Service Load-Balancing Tests**
   - Create Kubernetes service
   - Create backend endpoints
   - Verify traffic distributed across backends
   - Test service IP routing

3. **NAT Tests**
   - Verify SNAT applied to pod-to-external traffic
   - Verify DNAT applied to external-to-service traffic
   - Test NAT state cleanup on connection close

4. **Connection Tracking Tests**
   - Establish connections
   - Verify CT state machine
   - Test established connection allow
   - Test invalid state rejection

5. **Endpoint Regeneration Tests**
   - Trigger policy change
   - Verify no packet drops during update
   - Verify new policy takes effect
   - Test concurrent policy updates

#### **5.4 End-to-End Tests (K8s)**

**Pattern:**

```bash
# Create cluster
kind create cluster --image kindest/node:vX.XX

# Install Cilium with datapath enabled
cilium install --values=test-values.yaml

# Deploy test workloads
kubectl apply -f test-deployments.yaml

# Run connectivity tests
cilium connectivity test

# Verify policies enforced
kubectl exec pod -- curl service (should succeed/fail per policy)
```

### Testing Policy Enforcement Without Full Cluster

**Unit Test Approach:**

1. **Mock Endpoint Creation:**
   ```go
   ep := &endpoint.Endpoint{
       ID: 1234,
       SecLabel: 5000,
       IPv4: "10.0.0.1",
       IPv6: "f00d::1",
   }
   ```

2. **Mock Policy Installation:**
   ```go
   // Insert policy entries into policy map
   policyMap := ep.GetPolicyMap()
   policyMap.Insert(policyKey{src: 1000, proto: TCP}, policyEntry{allow: true})
   ```

3. **Mock Packet Processing:**
   ```c
   // Create test packet buffer
   struct __ctx_buff ctx = {
       .data = mock_packet,
       .data_end = mock_packet + sizeof(mock_packet),
   };

   // Call entry point
   int ret = cil_from_container(&ctx);
   ```

4. **Verify Result:**
   ```go
   assert(ret == TC_ACT_OK)  // Allow
   assert(ret == TC_ACT_SHOT) // Drop
   assert(packet_modified)     // NAT applied
   ```

### Datapath Validation Before Loading

**Located in:** `pkg/datapath/loader/loader.go` and `pkg/bpf/collection.go`

**Pre-Load Validation Steps:**

1. **Compilation:** Clang compilation with `-Werror` (warnings as errors)
2. **Verifier:** Kernel verifier checks program safety and correctness
3. **Symbol Resolution:** Verify all expected entry points and helpers present
4. **Tail Call Validation:** Ensure all referenced tail calls have programs (line ~170 in `collection.go`)
5. **Map Compatibility:** Check pinned maps match expected schema
6. **Program Type Check:** Verify program type matches attachment point

**Diagnostics Output:**

```bash
# If compilation fails
CLANG_ERROR: verifier log: ...truncated...

# If verifier rejects
BPF_VERIFIER_ERROR: Invalid instruction at offset ...

# If tail call missing
MISSED_TAIL_CALL: Endpoint 1234, slot CILIUM_CALL_IPV4_FROM_LXC not populated

# If maps incompatible
MAP_INCOMPATIBLE: Expected size 4096, got 8192
```

---

## 6. Debugging

### Troubleshooting eBPF Program Loading Failures

#### **6.1 Viewing Compilation Errors**

**If compilation fails:**

1. **Check compilation logs:**
   ```bash
   # Logs in Cilium agent output
   cilium-agent -debug    # Enables compilation debug logging

   # Or in systemd journal
   journalctl -u cilium-agent -n 100
   ```

2. **Manually reproduce compilation:**
   ```bash
   # Find clang command used
   clang -c -target bpf -O2 -DENABLE_IPV4 -DENABLE_IPV6 \
      -DPOLICY_MAP=cilium_policy_1234 \
      -I/workspace/bpf/include -I/workspace/bpf/lib \
      bpf_lxc.c -o bpf_lxc.o
   ```

3. **Check compiler output:**
   ```bash
   # Compilation error details in stderr
   cat /var/log/cilium/compilation.log
   ```

#### **6.2 Viewing Verifier Errors**

**If program loads but verifier rejects:**

1. **Extract verifier log:**
   ```bash
   # Logs are captured and output to stderr when available
   # Large logs (>4 MiB) are truncated, Cilium retries with larger buffer

   # Check Cilium agent logs
   cilium-agent -debug 2>&1 | grep "verifier log"
   ```

2. **Manually inspect with bpftool:**
   ```bash
   # After successful load
   bpftool prog dump xlated id <PROG_ID>    # Verify instructions
   bpftool prog dump jited id <PROG_ID>     # See JIT compiled code
   bpftool prog show                        # List all loaded programs
   ```

3. **Check kernel version compatibility:**
   ```bash
   # Verifier strictness increased in newer kernels
   uname -r

   # Some features require specific kernel versions
   cat /sys/kernel/config/CONFIG_BPF_SYSCALL  # Must be enabled
   ```

#### **6.3 Understanding Compilation Failures**

**Common errors:**

1. **"Unbounded loops"**
   - Issue: `for` loop without fixed iteration count
   - Fix: Add `#pragma unroll` or bounded loop limit
   - Location: Check loop in bpf/lib/ headers

2. **"Stack too big"**
   - Issue: Local variables exceed 512 bytes
   - Fix: Move variables to maps or use `__always_inline` more aggressively
   - Location: Usually in policy lookup functions

3. **"Invalid memory access"**
   - Issue: Pointer arithmetic that verifier can't prove safe
   - Fix: Add explicit bounds checks before access
   - Location: Packet header accesses, map reads

---

### Inspecting eBPF Maps at Runtime

#### **6.4 Using bpftool for Map Inspection**

```bash
# List all BPF maps
sudo bpftool map list

# Dump specific map
sudo bpftool map dump name cilium_policy_1234

# Read single entry
sudo bpftool map lookup name cilium_ct4_global id <KEY_BYTES_HEX>

# Update entry (for testing)
sudo bpftool map update name test_map key <KEY> value <VALUE>

# Monitor map access stats
sudo bpftool map stat
```

**Common maps to inspect:**

```bash
# Check endpoint mappings
bpftool map dump name cilium_lxc

# Check active connections
bpftool map dump name cilium_ct4_global | head -20

# Check NAT mappings
bpftool map dump name cilium_snat_v4_global

# Check service load-balancing
bpftool map dump name cilium_lb4_services_v2

# Check IP-to-identity mappings
bpftool map dump name cilium_ipcache
```

#### **6.5 Understanding Map Entry Formats**

**Endpoint Map Entry:**
```
Key:   <IPv4><Family><Endpoint_ID>
Value: <IFIndex><LXC_ID><SecLabel><Flags>
```

Example:
```bash
# Endpoint with ID 1234, sec label 5000, on interface 123
bpftool map lookup name cilium_lxc key 0a 00 00 04 00 00 00 00 d2 04 00 00
# Returns: Value = 7b 00 00 00 d2 04 00 00 88 13 00 00 00 00 00 00
#          (ifindex=123, lxc_id=1234, sec_label=5000)
```

**Policy Entry:**
```
Key:   <LPM_Prefix><SecLabel><DPort><Proto><Direction>
Value: <PacketCnt><ByteCnt><ProxyPort><Deny><AuthType>
```

**Connection Tracking Entry:**
```
Key:   <SrcIP><DstIP><SrcPort><DstPort><Proto><Direction>
Value: <State><BytesIn><BytesOut><Timestamp><Flags>
```

---

### Debugging Tools and Commands

#### **6.6 Cilium Monitor**

**Monitor eBPF events in real-time:**

```bash
# Watch all events
cilium monitor

# Watch specific event type (debug events)
cilium monitor --type Debug

# Show drops with reasons
cilium monitor --type Dropped

# Filter by endpoint
cilium monitor --from-id 1234 --to-id 5678

# Show captured packets (hex dump)
cilium monitor --verbose --from-id 1234
```

**Debug event types:**

```
DbgCaptureDelivery      - Packet delivery to endpoint
DbgCtLookup             - Connection tracking lookup
DbgCtMatch              - Connection state matched
DbgCtCreated            - New connection established
DbgCtLookupReverse      - Reverse path lookup
DbgCtUpdate             - Connection state update
DbgLbLookup             - Service load-balancer lookup
DbgLbRevnat             - Reverse NAT lookup
DbgPolicy               - Policy enforcement
DbgPolicyMatch          - Specific policy matched
DbgPolicyDenied         - Policy denied traffic
DbgSnat                 - SNAT translation
DbgARP                  - ARP processing
DbgCapture              - Packet captured for inspection
```

#### **6.7 Analyzing Drop Reasons**

**If traffic is being dropped:**

1. **Check drop metrics:**
   ```bash
   cilium metrics list

   # Look for cilium_drop_total metric
   # Labels show: reason (policy denied, checksum error, etc)

   # Get top drop reasons
   cilium metrics list | grep drop | sort | uniq -c
   ```

2. **Identify drop location:**
   ```bash
   # From drops, get drop_reason code
   # Map code to location in bpf/lib/drop.h

   # Common codes:
   # DROP_POLICY              (1)   - Policy denied
   # DROP_UNKNOWN_L3          (2)   - Unknown L3 protocol
   # DROP_UNKNOWN_L4          (3)   - Unknown L4 protocol
   # DROP_AUTH_REQUIRED       (68)  - Authentication required
   # ... (others in bpf/lib/drop.h)
   ```

3. **Correlate with policy:**
   ```bash
   # Check if policy allows traffic
   kubectl get ciliumnetworkpolicy -A

   # Get policy details
   kubectl describe cnp <policy-name> -n <namespace>

   # Check source/destination labels
   kubectl get pods --show-labels
   ```

---

### Profiling and Performance Debugging

#### **6.8 BPF Program Performance**

**Metrics available:**

```bash
# Per-program statistics
bpftool prog stat

# Returns run time, run count
# Use to identify hot programs

# Flamegraphs (if kernel supports)
perf record -e bpf:bpf_prog_load -aR sleep 10
perf script | stackcollapse-perf.pl | flamegraph.pl > graph.svg
```

**Location in code:** `pkg/monitor/metrics.go` - collect runtime statistics

#### **6.9 Identifying Performance Bottlenecks**

**Slow Policy Lookups:**
- Check policy map size: `bpftool map dump name cilium_policy_* | wc -l`
- Reduce policies: Consolidate overlapping rules
- Use fast-path policies: Optimize most-used policies

**Connection Tracking Overhead:**
- Check CT map size: `bpftool map dump name cilium_ct4_* | wc -l`
- Monitor memory: High pressure indicates map eviction
- Reduce long-lived connections if needed

**Tail Call Chain Length:**
- Inspect program sections: `llvm-objdump -d bpf_lxc.o | grep "tail_call"`
- Count tail calls in hot paths
- Minimize for latency-sensitive traffic

---

### Logs and Metrics for Diagnostics

#### **6.10 Key Cilium Log Messages**

```
"Datapath compilation successful"              - Program compiled and loaded
"Failed to load datapath"                       - Compilation or loading error
"Missed tail call"                              - Program not in tail call map
"Policy map full"                               - Per-endpoint policy map exhausted
"Endpoint regeneration failed"                  - Error during endpoint update
"Verifier log truncated"                        - Verifier output exceeded buffer
"Device not found"                              - Interface doesn't exist
"BPF map incompatible"                          - Existing pinned map has wrong schema
```

**View logs:**
```bash
# Cilium agent logs
journalctl -u cilium-agent -f

# Or in Kubernetes
kubectl logs -n cilium-system cilium-XXXXX -f

# Debug level logs
cilium-agent --debug-verbose
```

#### **6.11 Prometheus Metrics**

**Key datapath metrics:**

```
cilium_bpf_map_pressure{map_name="cilium_ct4_global"}
  - Map utilization (0-100), alerts at 80%+

cilium_drop_total{reason="policy"}
  - Packets dropped by policy

cilium_forward_bytes_total
  - Data forwarded through datapath

cilium_endpoint_count{state="created"}
  - Active endpoints

cilium_lb4_service_count
  - Active load-balanced services

cilium_bpf_program_runtime_micro_seconds{program="tc/ingress"}
  - Program execution time per packet

cilium_bpf_map_updates_total{map="cilium_policy"}
  - Map update operations
```

**Access metrics:**

```bash
# In Kubernetes
kubectl port-forward -n cilium-system cilium-agent-POD 9090:9090

# Access metrics
curl http://localhost:9090/metrics | grep cilium_drop
```

---

### Kernel Probing and Compatibility Checking

#### **6.12 Feature Probing**

**Cilium probes kernel capabilities at startup:**

```bash
# Located in pkg/datapath/linux/probes/probes.go

# Check what features Cilium detected
cilium status --verbose

# Shows kernel version, BPF support, feature availability
```

**Manual probe:**

```bash
# Run bpftool to detect features (Cilium does this)
sudo bpftool -j feature probe

# Returns JSON with supported features:
# - kernel_version
# - map_types (which types supported)
# - program_types
# - helper_functions
# - kernel_config
```

**Checking required features:**

```bash
# Must have for basic operation
cat /boot/config-$(uname -r) | grep CONFIG_BPF
# OUTPUT: CONFIG_BPF=y

cat /boot/config-$(uname -r) | grep CONFIG_BPF_SYSCALL
# OUTPUT: CONFIG_BPF_SYSCALL=y

# Check interface for TC
cat /boot/config-$(uname -r) | grep CONFIG_NET_SCH_INGRESS
# OUTPUT: CONFIG_NET_SCH_INGRESS=y
```

---

## 7. Adding a New Hook

### Step-by-Step Process for Adding a New eBPF Hook

#### **7.1 Define the Hook Slot**

**File:** `/workspace/bpf/lib/common.h` (lines 80-140)

**Current slots:** 50 total, with gaps at 3, 35, 40-41

**Action:**
1. Choose an unused slot number (or define new slot at end: `CILIUM_CALL_MYFEATURE = 50`)
2. Add definition:

```c
#define CILIUM_CALL_MYFEATURE_CUSTOM    48  // Or pick any unused slot
```

**Example:** To add IPv4-specific custom packet processing:
```c
#define CILIUM_CALL_IPV4_CUSTOM_HOOK    48
#define CILIUM_CALL_IPV6_CUSTOM_HOOK    50  // Or 51 if CILIUM_CALL_SIZE increased
```

#### **7.2 Create the Tail-Called Program**

**File:** New file `/workspace/bpf/lib/myhook.h` (or add to existing header)

**Structure:**

```c
// /workspace/bpf/lib/myhook.h

#ifndef CILIUM_CALL_MYFEATURE_CUSTOM
#define CILIUM_CALL_MYFEATURE_CUSTOM 48
#endif

/**
 * process_custom_logic - Custom packet processing
 * @ctx: Packet context (SKB or XDP)
 * @return: Packet verdict (TC_ACT_OK, TC_ACT_SHOT, etc.)
 *
 * Performs custom logic on packets matching certain criteria.
 */
static __always_inline __maybe_unused int
process_custom_logic(struct __ctx_buff *ctx)
{
    // Extract packet info
    struct iphdr *iph = ctx_data(ctx) + sizeof(struct ethhdr);

    // Perform custom logic
    // Examples: rate limiting, signature matching, custom routing

    // Return verdict
    return TC_ACT_OK;  // Allow packet
    // or TC_ACT_SHOT  // Drop packet
    // or TC_ACT_REDIRECT  // Redirect to interface
}

// Tail-called version (must be separate for tail call registration)
__section_tail(CILIUM_MAP_CALLS, CILIUM_CALL_MYFEATURE_CUSTOM)
int tail_custom_hook(struct __ctx_buff *ctx)
{
    return process_custom_logic(ctx);
}
```

#### **7.3 Invoke from Main Program**

**File:** `/workspace/bpf/bpf_lxc.c` (or `bpf_host.c` for host-side processing)

**Integration point:**

1. **Include the header:**
```c
#include "lib/myhook.h"
```

2. **Add invocation in appropriate function:**

```c
// In cil_from_container() around line 1600-1700
__section_entry
int cil_from_container(struct __ctx_buff *ctx)
{
    // ... existing code for endpoint lookup, policy check ...

    // Invoke custom hook (after basic validation)
    if (is_defined(ENABLE_CUSTOM_HOOK)) {
        ret = invoke_tailcall_if(
            is_defined(ENABLE_CUSTOM_HOOK),    // Condition
            CILIUM_CALL_MYFEATURE_CUSTOM,      // Tail call slot
            process_custom_logic,               // Fallback function (if tail call fails)
            &ext_err                            // Extended error code
        );

        if (IS_ERR(ret)) {
            // Handle error
            return send_drop_notify_ext(ctx, src_label, dst_label, LXC_ID,
                                       ret, ext_err, CTX_ACT_DROP,
                                       METRIC_INGRESS);
        }

        // Continue with returned packet (may be modified)
    }

    // ... rest of packet processing ...
}
```

**Conditional invocation example:**
```c
// Only invoke for TCP traffic
ret = invoke_tailcall_if(
    __and(is_defined(ENABLE_CUSTOM_HOOK),
          protocol == IPPROTO_TCP),
    CILIUM_CALL_MYFEATURE_CUSTOM,
    tail_custom_hook,
    &ext_err
);
```

#### **7.4 Add Compilation Configuration**

**File:** `/workspace/pkg/datapath/loader/loader.go` (lines 200-250)

**Add feature flag:**

```go
// In compiler configuration struct
type CompileOpts struct {
    // ... existing fields ...
    EnableCustomHook bool
}

// In Reinitialize() function
func (l *loader) Reinitialize(ctx context.Context, cfg *config.DaemonConfig, ...) error {
    // ... existing code ...

    // Add compilation flag if feature enabled
    if cfg.EnableCustomHook {
        opts.Define("ENABLE_CUSTOM_HOOK")
    }

    // ... continue compilation ...
}
```

**Or in Go datapath config struct:**

```go
// In pkg/datapath/types/types.go
type CompilerOptions struct {
    // ... existing fields ...
    CustomHookEnabled bool
}
```

#### **7.5 Update Map Definitions (If Needed)**

**If hook requires new maps:**

**File:** `/workspace/bpf/lib/maps.h` (or new file)

```c
// Define custom hook configuration map (if needed)
struct bpf_elf_map __section_maps CUSTOM_HOOK_CONFIG = {
    .type           = BPF_MAP_TYPE_HASH,
    .id             = CILIUM_MAP_CUSTOM_HOOK_CONFIG,
    .size_key       = sizeof(__u32),
    .size_value     = sizeof(struct custom_hook_entry),
    .pinning        = CILIUM_PIN_REPLACE,
    .max_elem       = 10000,
};

struct custom_hook_entry {
    __u32 config;
    __u64 match_count;
};
```

**From Go side:**

**File:** `/workspace/pkg/maps/customhook/customhook.go` (new file)

```go
package customhook

import "github.com/cilium/cilium/pkg/bpf"

const (
    MapName    = "cilium_custom_hook"
    MaxEntries = 10000
)

type CustomHookEntry struct {
    Config     uint32
    MatchCount uint64
}

func NewMap() *bpf.Map {
    return bpf.NewMap(
        MapName,
        bpf.BPF_MAP_TYPE_HASH,
        &CustomHookKey{},
        &CustomHookEntry{},
        MaxEntries,
        bpf.CILIUM_PIN_REPLACE,
    )
}
```

#### **7.6 Update Control Plane Integration**

**File:** `/workspace/pkg/endpoint/policy.go` (if hook relates to policy)

**Add policy-to-hook conversion:**

```go
func (e *Endpoint) ApplyCustomHookPolicy(policy *api.CustomHookPolicy) error {
    // Convert policy to eBPF map entries
    for _, rule := range policy.Rules {
        entry := &CustomHookEntry{
            Config: encodeConfig(rule),
        }

        // Insert into hook config map
        if err := e.customHookMap.Insert(rule.ID, entry); err != nil {
            return err
        }
    }

    return nil
}
```

#### **7.7 Test the Hook**

**Create unit test:**

**File:** `/workspace/bpf/tests/bpf_customhook_test.c` (new file)

```c
#include "lib/myhook.h"
#include "lib/common.h"

__section("test_")
int test_custom_hook_allow() {
    struct __ctx_buff ctx = {
        .data = mock_packet_tcp,
        .data_end = mock_packet_tcp + sizeof(mock_packet_tcp),
    };

    int ret = process_custom_logic(&ctx);

    // Verify allowed
    assert(ret == TC_ACT_OK);
    return 0;
}

__section("test_")
int test_custom_hook_drop() {
    struct __ctx_buff ctx = {
        .data = mock_packet_malicious,
        .data_end = mock_packet_malicious + sizeof(mock_packet_malicious),
    };

    int ret = process_custom_logic(&ctx);

    // Verify dropped
    assert(ret == TC_ACT_SHOT);
    return 0;
}
```

**Create Go integration test:**

**File:** `/workspace/pkg/datapath/loader/customhook_test.go` (new file)

```go
func TestCustomHookAttachment(t *testing.T) {
    // Create loader with hook enabled
    cfg := &config.DaemonConfig{
        EnableCustomHook: true,
    }

    l := newLoader(cfg)

    // Compile with hook
    ep := testutils.TestEndpoint()
    err := l.ReloadDatapath(context.Background(), ep)

    // Verify compilation succeeded
    assert.NoError(t, err)

    // Verify hook maps created
    hookMap := bpf.LookupMap("cilium_custom_hook")
    assert.NotNil(t, hookMap)
}
```

#### **7.8 Document the Hook**

**Create documentation:**

**File:** `/logs/agent/custom_hook_guide.md`

```markdown
# Custom Hook Implementation Guide

## Overview
The custom hook processes packets [description of when hook triggers]

## Configuration
- Enable via: `--custom-hook-enabled=true`
- Maps created: `cilium_custom_hook` (configuration)

## Behavior
- Invoked for: [packet types/conditions]
- Returns: TC_ACT_OK (allow), TC_ACT_SHOT (drop), TC_ACT_REDIRECT (redirect)

## Metrics
- `cilium_custom_hook_matches_total` - Packets processed by hook
- `cilium_custom_hook_drops_total` - Packets dropped by hook

## Troubleshooting
[Common issues and solutions]
```

#### **7.9 Different Hook Types and Attachment Points**

**You can create hooks at different points in the datapath:**

**Option A: Container Ingress (from network → container)**
```c
// In cil_to_container() - egress traffic from other containers to this one
__section_tail(CILIUM_MAP_CALLS, CILIUM_CALL_CUSTOM_INGRESS)
int tail_ingress_custom(struct __ctx_buff *ctx) { ... }
```

**Option B: Container Egress (from container → network)**
```c
// In cil_from_container() - ingress traffic from this container to network
__section_tail(CILIUM_MAP_CALLS, CILIUM_CALL_CUSTOM_EGRESS)
int tail_egress_custom(struct __ctx_buff *ctx) { ... }
```

**Option C: Host Firewall**
```c
// In bpf_host.c for host-level packet processing
__section_tail(CILIUM_MAP_CALLS, CILIUM_CALL_CUSTOM_HOST_FW)
int tail_host_fw_custom(struct __ctx_buff *ctx) { ... }
```

**Option D: XDP (Early filtering, before kernel stack)**
```c
// Add to bpf_xdp.c for high-speed pre-filtering
__section_entry
int cil_xdp_custom_filter(struct __ctx_buff *ctx)
{
    // Very limited operations, max performance
    // Can only: PASS, DROP, REDIRECT
}
```

**Option E: Socket Level (transparent proxy integration)**
```c
// In bpf_sock.c for traffic at application layer
__section("sk_msg/verdict")
int cil_sk_msg_custom(struct sk_msg_md *msg)
{
    // Intercept at socket level before/after application
    // Can redirect to proxy, drop, or allow through
}
```

#### **7.10 Integration Checklist**

Before marking the hook complete:

- [ ] eBPF source code added and compiles without errors
- [ ] BPF verifier passes (no "invalid instruction" errors)
- [ ] Tail call slot defined in `common.h`
- [ ] Hook invoked from entry point with conditional flag
- [ ] Go compilation adds `-D` flag when feature enabled
- [ ] Maps created and managed by Go package (if needed)
- [ ] Control plane can update hook configuration
- [ ] Unit tests for eBPF logic pass
- [ ] Integration tests for Go-eBPF interaction pass
- [ ] Metrics added (packet count, drop count, latency)
- [ ] Debug events added for troubleshooting
- [ ] Documentation complete with examples
- [ ] Tested with XDP (if applicable) and TC attachment
- [ ] Verified with actual Kubernetes workloads

---

## Appendix: Key Files Reference

### Essential Files to Read First

1. **`pkg/datapath/loader/loader.go`** - Main orchestration
2. **`bpf/bpf_lxc.c`** - Primary policy enforcement program
3. **`pkg/bpf/collection.go`** - ELF loading and verifier
4. **`bpf/lib/common.h`** - Core data structures and macros

### Related Go Packages

- `pkg/endpoint/` - Endpoint lifecycle
- `pkg/policy/` - Policy computation
- `pkg/identity/` - Security identity management
- `pkg/maps/` - BPF map interfaces
- `pkg/service/` - Kubernetes service management

### Related eBPF Headers

- `lib/policy.h` - Policy lookup logic
- `lib/nat.h` - NAT/SNAT/DNAT
- `lib/lb.h` - Load balancing
- `lib/conntrack.h` - Connection tracking
- `lib/nodeport.h` - NodePort service implementation

### Command Reference

```bash
# View all eBPF programs loaded
sudo bpftool prog list

# Dump specific program
sudo bpftool prog dump xlated id <PROG_ID>

# View all BPF maps
sudo bpftool map list

# Dump map entries
sudo bpftool map dump name <MAP_NAME>

# Monitor datapath events
cilium monitor

# Check Cilium status
cilium status --verbose

# View policy maps on specific endpoint
cilium bpf endpoint list
```

---

**Document Version:** 1.0
**Last Updated:** 2026-02-24
**Author:** Onboarding AI Assistant

This document provides comprehensive guidance for understanding and maintaining the Cilium eBPF datapath subsystem. For questions or updates, refer to the Cilium GitHub repository at https://github.com/cilium/cilium.
