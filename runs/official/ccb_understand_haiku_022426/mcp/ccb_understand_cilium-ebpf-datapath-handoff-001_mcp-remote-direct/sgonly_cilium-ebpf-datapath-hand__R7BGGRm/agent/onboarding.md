# Cilium eBPF Datapath Subsystem - Handoff Documentation

## Overview

This document provides a comprehensive overview of Cilium's eBPF datapath subsystem, the core networking and security implementation. This handoff is designed to help team members understand, maintain, and extend this critical component.

---

## 1. Purpose

### What Problem Does the eBPF Datapath Solve?

The eBPF (extended Berkeley Packet Filter) datapath is the foundation of Cilium's networking and security enforcement. Instead of relying on traditional iptables rules or userspace packet processing, Cilium uses eBPF programs running in the Linux kernel to:

1. **High-performance packet processing** - eBPF programs execute in kernel space with minimal overhead
2. **Fine-grained network policy enforcement** - Policies are enforced at kernel level before packets reach applications
3. **Dynamic behavior without kernel changes** - New networking features can be added by loading new eBPF programs without modifying the kernel
4. **Visibility and observability** - eBPF programs can generate events for network monitoring

### Why eBPF Instead of iptables or Userspace Networking?

- **Performance**: eBPF programs execute directly in the kernel JIT-compiled to CPU instructions, avoiding context switches
- **Flexibility**: eBPF allows dynamic packet processing logic that can be updated without recompiling the kernel
- **Safety**: The in-kernel verifier ensures eBPF programs are safe and cannot crash the kernel
- **Real-time capabilities**: Enables features like TCP retransmission optimization and connection tracking that iptables cannot provide
- **Container-awareness**: eBPF can access kernel data structures to make decisions based on container/pod identity

### Key Responsibilities of the Datapath Subsystem

1. **Endpoint (pod/container) ingress/egress filtering** - Control traffic in/out of containers
2. **Service load balancing** - Distribute service traffic across backends
3. **Network policy enforcement** - Implement security policies between pods
4. **Network address translation (NAT)** - Implement masquerading and SNAT/DNAT
5. **Encryption** - Tunnel encryption for inter-node traffic
6. **Connection tracking** - Maintain stateful connections
7. **Overlay networking** - Support VXLAN and other overlay mechanisms
8. **Host networking** - Manage traffic on the host level
9. **Host firewall** - Enforce network policies on node traffic

### Integration with Kubernetes Networking

The datapath integrates with Kubernetes by:

1. **Pod interface attachment** - Cilium loads eBPF programs onto pod veth interfaces
2. **Service discovery** - Watches Kubernetes Service objects and populates load balancing maps
3. **NetworkPolicy enforcement** - Converts Kubernetes NetworkPolicy resources into eBPF bytecode
4. **Identity-based security** - Uses pod labels to create security identities instead of IP-based rules
5. **CNI integration** - Acts as the CNI plugin to set up pod networking

---

## 2. Dependencies

### Upstream Dependencies (What Calls Into the Datapath)

- **Daemon**: `daemon/cmd/daemon.go` - Main Cilium agent that initializes the datapath via `Loader.Reinitialize()`
- **Endpoint manager**: `pkg/endpoint/` - Creates/updates endpoints which trigger datapath program loading
- **Policy engine**: `pkg/policy/` - Generates policy rules that are converted to eBPF bytecode
- **Service manager**: `pkg/service/` - Manages load balancing configuration
- **Controller framework**: Uses controller patterns to react to cluster changes

### Downstream Dependencies (What the Datapath Calls)

- **Linux kernel APIs**:
  - BPF syscall (`bpf()`) for program loading and map operations
  - Netlink for attaching programs to network interfaces
  - tc (Traffic Control) subsystem for ingress/egress attachment
  - XDP (eXpress Data Path) for high-speed packet processing
  - cgroup for socket-level program attachment

- **eBPF map access**: Shared memory maps for communication between kernel and userspace
  - Policy maps (`cilium_policy_*`)
  - Connection tracking maps (`cilium_ct*`)
  - Service load balancing maps (`cilium_lb*`)
  - Event maps for monitoring

### Subsystem Interactions

```
┌─────────────────────────────────────────────────────────┐
│                  Cilium Agent (Daemon)                  │
├──────────────────┬──────────────────┬──────────────────┤
│   Endpoint Mgr   │  Policy Engine   │  Service Manager │
└────────┬─────────┴────────┬─────────┴────────┬──────────┘
         │                  │                  │
    ┌────▼──────────────────▼──────────────────▼────┐
    │    Datapath Loader (pkg/datapath/loader)     │
    │  Compilation │ Loading │ Attachment │ Maps   │
    └────┬─────────────────────────────────────────┘
         │
    ┌────▼─────────────────────────────────┐
    │   Linux Kernel eBPF Runtime          │
    │  ┌──────────┬──────────┬────────┐   │
    │  │ tc ingress/egress  │ XDP   │   │
    │  │ cgroup socket      │ Maps  │   │
    │  └──────────┴──────────┴────────┘   │
    └──────────────────────────────────────┘
```

### Go-to-C Boundary

**Interfaces**: `pkg/datapath/types/`
- `Loader` interface: Main entry point for loading/reloading programs
- `Endpoint` interface: Represents a workload (pod/container)
- `ConfigWriter` interface: Handles writing configuration headers

**Data Flow**:
1. Go code determines what eBPF programs are needed
2. Compilation: C eBPF source → Object files (`.o`) via clang
3. Loading: ELF object files → Kernel via `ebpf-go` library
4. Map population: Go code populates eBPF maps with policy/configuration data
5. Attachment: Programs attached to kernel hook points via netlink

---

## 3. Relevant Components

### Main Source Structure

```
bpf/                                  # eBPF source programs
├── bpf_lxc.c                        # Container endpoint programs
├── bpf_host.c                       # Host endpoint programs
├── bpf_network.c                    # Network node programs
├── bpf_overlay.c                    # Overlay network programs
├── bpf_xdp.c                        # XDP prefilter programs
├── bpf_sock.c                       # Socket-level programs
├── bpf_wireguard.c                  # WireGuard encryption programs
├── include/                         # Header files and configuration
└── lib/                             # Shared BPF library code

pkg/datapath/                        # Datapath Go code
├── loader/                          # Main loader implementation
│   ├── loader.go                   # Core loader struct and ReloadDatapath()
│   ├── compile.go                  # eBPF compilation (C→object files)
│   ├── base.go                     # Reinitialize() entry point
│   ├── netlink.go                  # Program loading and map operations
│   ├── tc.go                       # TC attachment (legacy)
│   ├── tcx.go                      # TCX attachment (newer)
│   ├── netkit.go                   # Netkit attachment
│   ├── xdp.go                      # XDP attachment
│   ├── cache.go                    # Template caching
│   ├── template.go                 # Program template handling
│   └── hash.go                     # Configuration hashing
├── maps/                           # Map management
├── linux/                          # Linux-specific utilities
│   └── probes/                    # Feature detection
├── types/                          # Interface definitions
└── iptables/                       # iptables rule management
```

### Critical Files and Their Purposes

#### Core Loader Files

**`pkg/datapath/loader/loader.go`** (lines 1-700+)
- `type loader struct` - Main loader state machine
- `func (l *loader) ReloadDatapath()` - Entry point for reloading endpoint programs
- `func (l *loader) reloadDatapath()` - Internal method that actually loads programs
- `func (l *loader) reloadHostDatapath()` - Handles host endpoint program loading
- `func (l *loader) Unload()` - Cleanup when endpoint is deleted

**`pkg/datapath/loader/base.go`** (lines 356+)
- `func (l *loader) Reinitialize()` - Main initialization called at daemon startup
- `func (l *loader) writeNodeConfigHeader()` - Generate node_config.h
- `func (l *loader) writeNetdevHeader()` - Generate netdev_config.h

**`pkg/datapath/loader/compile.go`** (lines 1-300+)
- `func compileDatapath()` - Orchestrates compilation of eBPF C → object files
- `func getBPFCPU()` - Detects CPU ISA version (v1, v2, v3) for BPF complexity
- Compilation flags and program definitions

**`pkg/datapath/loader/netlink.go`** (lines 1-150+)
- `func loadDatapath()` - Loads ELF object into kernel
- `func resolveAndInsertCalls()` - Populates program array maps (tail calls)
- `func renameMaps()` - Substitutes map names for endpoint-specific maps

**`pkg/datapath/loader/tc.go`, `tcx.go`, `netkit.go`, `xdp.go`**
- Program attachment mechanisms for different hook points
- `attachSKBProgram()` - Unified attachment that tries tcx, netkit, or falls back to tc

#### Template and Caching

**`pkg/datapath/loader/template.go`**
- Handles pre-compiled program templates
- Reduces compilation time by caching compiled objects

**`pkg/datapath/loader/cache.go`**
- `type objectCache` - Caches compiled datapaths
- `func (o *objectCache) UpdateDatapathHash()` - Invalidates cache when config changes

#### Feature Detection

**`pkg/datapath/linux/probes/probes.go`**
- Detects kernel capabilities for eBPF features
- `func HaveProgramHelper()` - Tests if kernel supports specific BPF helper functions
- `func HaveV3ISA()` - Detects if kernel supports BPF ISA v3

#### Map Management

**`pkg/maps/callsmap/callsmap.go`**
- Manages tail call maps (program arrays)
- Maps named `cilium_calls_*` for endpoint-specific tail calls
- Maps named `cilium_calls_netdev_*` for per-netdev calls

**`pkg/maps/policymap/policymap.go`**
- Policy enforcement maps
- `cilium_policy_*` for ingress policy decisions
- `cilium_call_policy` for policy program arrays

### eBPF Program Entry Points

#### Container Endpoint Programs (bpf_lxc.c)

```c
// Symbols defined in loader: symbolFromEndpoint, symbolToEndpoint
static __section__("classifier/ingress") int cil_from_container(...)  // Ingress
static __section__("classifier/egress") int cil_to_container(...)     // Egress
```

- Handles ingress filtering for container traffic
- Implements policy enforcement
- Performs load balancing and NAT
- Manages connection tracking

#### Host Endpoint Programs (bpf_host.c)

```c
static __section__("from-netdev") int cil_from_netdev(...)    // Ingress
static __section__("to-netdev") int cil_to_netdev(...)        // Egress
static __section__("from-host") int cil_from_host(...)        // Host egress
```

- Handles traffic on physical/host interfaces
- Implements host firewall
- Manages NodePort services
- Handles inter-node communication

#### Network Node Programs (bpf_network.c)

- Attached to virtual network interfaces
- Handles tunnel encapsulation/decapsulation
- Processes overlay network packets

#### XDP Programs (bpf_xdp.c)

- Early packet filtering at driver level
- Pre-filter configuration
- Highest performance but limited capability

### Symbol Mapping (loader.go lines 47-65)

```go
// Container endpoints
const symbolFromEndpoint = "cil_from_container"  // Ingress program
const symbolToEndpoint = "cil_to_container"      // Egress program

// Host endpoints
const symbolFromHostNetdevEp = "cil_from_netdev" // Host ingress
const symbolToHostNetdevEp = "cil_to_netdev"     // Host egress
const symbolFromHostEp = "cil_from_host"         // Host traffic
const symbolToHostEp = "cil_to_host"             // To host

// XDP
const symbolFromHostNetdevXDP = "cil_xdp_entry"

// Overlay
const symbolFromOverlay = "cil_from_overlay"
const symbolToOverlay = "cil_to_overlay"
```

### Compilation and Loading Flow

```
1. Configuration Generation (Reinitialize)
   └─► WriteNodeConfig() → node_config.h
   └─► WriteNetdevConfig() → netdev_config.h
   └─► WritePreFilterConfig() → filter_config.h

2. Compilation (ReloadDatapath → compileDatapath)
   └─► C source + headers → clang with target=bpf
   └─► Object files (.o) → bpf_lxc.o, bpf_host.o, etc.

3. Loading (reloadDatapath → loadDatapath)
   └─► ELF object → ebpf-go → kernel verifier
   └─► Verifier checks: memory safety, termination, bounds

4. Attachment (attachSKBProgram)
   └─► tcx (Linux 6.6+) or legacy tc
   └─► Attach to ingress/egress on interfaces

5. Map Initialization (resolveAndInsertCalls)
   └─► Populate program array maps (tail calls)
   └─► Populate policy maps
```

---

## 4. Failure Modes

### eBPF Program Loading Failures

#### Verifier Failures

**Symptom**: Error message with "verifier log" in logs
**Root Causes**:
- Invalid memory access patterns
- Unbounded loops or complexity
- Use of unsupported BPF helpers on kernel
- Stack overflows (eBPF stack is limited to 512 bytes)

**Handling**: `pkg/datapath/loader/netlink.go:87-92`
```go
if errors.As(err, &ve) {
    // Print verifier error for debugging
    fmt.Fprintf(os.Stderr, "Verifier error: %s\nVerifier log: %+v\n", err, ve)
}
```

**Recovery**: Must recompile with simpler logic or requires kernel upgrade

#### Map Incompatibility

**Symptom**: `ErrMapIncompatible` when loading
**Cause**: Pinned map from previous run has different structure (type, key/value size, etc.)
**Handling**: `pkg/datapath/loader/netlink.go:253-256` - Maps are removed if incompatible before reload

#### Map Full / Allocation Failures

**Symptom**: `BPF_MAP_CREATE` fails
**Causes**:
- Insufficient kernel memory
- `/sys/fs/bpf/` filesystem limits
- Memory pressure from other applications

**Diagnosis Tools**:
```bash
bpftool map list              # See all maps and their usage
bpftool map show id <id>      # Details of specific map
cat /proc/meminfo             # Kernel memory pressure
```

### Kernel Compatibility Issues

#### Unsupported Feature Detection

**System**: `pkg/datapath/linux/probes/probes.go`

**Detection Pattern**:
```go
// Test if kernel supports a feature by trying to load it
func HaveProgramHelper(progType ebpf.ProgramType, helper asm.BuiltinFunc) error {
    // Attempt to create minimal program using the helper
    // If it fails with ErrNotSupported, feature is missing
}
```

**Examples**:
- `probes.HaveFibLookup()` - Required for NodePort
- `probes.HaveKtimeGetBootNs()` - Required for packet recording
- `probes.HaveRedirectNeigh()` - Required for host routing

**Configuration Validation**: `daemon/cmd/kube_proxy_replacement.go:245-384`
- Validates kernel supports required helpers before enabling features
- Returns errors if configuration impossible on this kernel

### Configuration Errors

#### Invalid Program Symbols

**Cause**: eBPF source doesn't define expected symbol
**Detection**: eBPF collection loading fails with "program not found"
**Prevention**: Symbol constants verified in compile and load stages

#### Missing or Malformed Headers

**Cause**: Configuration headers (node_config.h, netdev_config.h) generation fails
**Symptom**: Compilation errors mentioning undefined macros
**Prevention**: `WriteNodeConfigHeader()` validates all required options

#### Template Cache Invalidation

**Mechanism**: Hash computed on configuration changes (`loader.go:621-627`)
```go
spec, hash, err := l.templateCache.fetchOrCompile(ctx, cfg, ep, &dirs, stats)
```
- If datapath configuration changes, old templates invalidated
- Forces recompilation
- Cache prevents redundant compilations

### Network Interface Issues

#### Device Not Found

**Symptom**: "retrieving device" error in logs
**Cause**: Interface doesn't exist when loader tries to attach programs
**Handling**: `loader.go:382-385` - Logs warning and continues

#### Attachment Failures

**TC Qdisc Errors**: `attachTCProgram()` failures
**Cause**:
- qdisc already exists
- Permission denied
- Kernel TC subsystem issues

**Fallback Chain** (attachSKBProgram):
1. Try TCX (modern, Linux 6.6+)
2. Try netkit (specialized for netkit devices)
3. Fall back to legacy TC
4. If all fail, error returned

### Recovery Mechanisms

#### Automatic Cleanup

**On Failure**: `reloadDatapath()` returns error but partial state may remain
- Pinned BPF links in `/sys/fs/bpf/` may remain
- Maps may be orphaned

**Manual Recovery**:
```bash
# Remove all Cilium BPF objects
rm -rf /sys/fs/bpf/tc/
rm -rf /sys/fs/bpf/cilium/

# Restart Cilium - will reinitialize everything
systemctl restart cilium
```

#### State Preservation

- Pinned maps preserved across restarts for connection tracking continuity
- Obsolete programs removed by `removeObsoleteNetdevPrograms()`

#### Configuration Rollback

- Previous node configuration preserved in templates
- If new compilation fails, old programs can still run (if pinned)

---

## 5. Testing

### Test Structure

Tests located in `pkg/datapath/loader/` with `_test.go` suffix:
- `loader_test.go` - Main loader functionality
- `compile_test.go` - Compilation logic
- `cache_test.go` - Template caching
- `hash_test.go` - Configuration hashing
- `tc_test.go`, `xdp_test.go`, `tcx_test.go` - Attachment mechanisms

### Test Infrastructure

**Privileged Tests**: Require root/capabilities
```go
func initEndpoint(tb testing.TB, ep *testutils.TestEndpoint) {
    testutils.PrivilegedTest(tb)  // Skip if not privileged
    require.Nil(tb, rlimit.RemoveMemlock())
}
```

**Setup**:
- Create temporary directories for state
- Create dummy network interfaces
- Cleanup pinned BPF objects after test

### Test Patterns

#### Basic Datapath Loading

**Test**: `TestCompileOrLoadDefaultEndpoint`
```go
func testReloadDatapath(t *testing.T, ep *testutils.TestEndpoint) {
    ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
    defer cancel()
    stats := &metrics.SpanStat{}

    l := newTestLoader(t)
    _, err := l.ReloadDatapath(ctx, ep, stats)
    require.NoError(t, err)
}
```

**What it tests**:
- Complete compilation pipeline
- ELF object loading into kernel
- Program attachment to dummy interfaces

#### Feature Testing

Tests use feature probes to skip tests on unsupported kernels:
```go
if probes.HaveProgramHelper(ebpf.XDP, asm.FnXdpGetBuffLen) != nil {
    t.Skip("XDP programs not supported on this kernel")
}
```

#### Map-based Tests

Test that eBPF maps are properly created and populated:
- Policy maps created with correct structures
- Tail call maps populated with program references
- Map constants substituted correctly

### BPF Program Validation

**Verifier Testing**: `pkg/datapath/linux/probes/` - Pre-loads programs to verify kernel support
- Minimal test programs for each feature
- Catches kernel incompatibilities early

**Static Analysis**:
- Clang compilation warnings treated as errors (`-Werror`)
- Type checking through BPF ELF structure validation

### Integration Tests

**End-to-End**: `test/` directory contains integration tests
- Creates actual pods/containers
- Verifies policy enforcement
- Tests load balancing and NAT

**Cilium CLI Tests**: `pkg/endpoint/bpf_test.go`
- Tests endpoint creation/deletion
- Verifies map cleanup

### Testing Without Full Cluster

**Unit Tests**:
- Loader tests use dummy interfaces
- Don't require Kubernetes or full Cilium setup
- Fast, repeatable, isolated

**Mock Setup**:
```go
// Create dummy interfaces for testing
link := netlink.Dummy{
    LinkAttrs: netlink.LinkAttrs{Name: ifName},
}
netlink.LinkAdd(&link)
defer netlink.LinkDel(&link)
```

---

## 6. Debugging

### Troubleshooting eBPF Program Loading Failures

#### Step 1: Check Kernel Version and Features

```bash
# Minimum: Linux 4.16 for basic eBPF
uname -a

# Check specific features
cat /proc/config.gz | zcat | grep CONFIG_BPF

# Use Cilium tools
cilium-dbg map list              # List loaded maps
cilium-dbg bpf endpoint list    # List loaded programs
```

#### Step 2: Enable Debug Logging

```yaml
# Kubernetes ConfigMap
logging:
  level: debug
  format: json
```

**Key log fields to search**:
- `subsys=datapath-loader` - All loader operations
- `level=warning` or `level=error` - Problems
- `msg=` - Search for specific failures

#### Step 3: Inspect eBPF Maps at Runtime

```bash
# List all maps
bpftool map list

# Show specific map contents
bpftool map dump name cilium_policy_1234

# Show map stats
bpftool map show id <id>

# Real-time monitoring
watch -n1 'bpftool map show'
```

#### Step 4: Inspect Loaded Programs

```bash
# List all eBPF programs
bpftool prog list

# Show program details
bpftool prog show id <id>

# Disassemble program (complex programs may not show fully)
bpftool prog dump id <id> xlated

# Show verifier log (if available)
bpftool prog dump id <id> xlated verbose
```

### Debugging Map Attachment and Updates

**Find where programs are attached**:
```bash
# Show all TC qdisc and filters
tc qdisc show
tc filter show dev <interface>

# XDP programs
ip link show

# netkit programs (if supported)
```

**Verify Tail Call Maps**:
```bash
# Check if program arrays have entries
bpftool map dump name cilium_calls_1234
bpftool map dump name cilium_call_policy

# If maps are empty, programs won't be called
```

### Tools for Debugging eBPF

#### bpftool (kernel-supplied)

```bash
bpftool --help                           # List all commands
bpftool prog list --json                # JSON output for parsing
bpftool map dump name <name> --json     # Map contents as JSON
bpftool prog dump id <id> opcodes       # Raw bytecode
```

#### cilium-dbg (Cilium-supplied)

```bash
# Within container or with --local
cilium-dbg bpf endpoint list
cilium-dbg bpf endpoint get <id>
cilium-dbg map get <name>
```

#### Cilium Monitor

```bash
# Real-time event monitoring
cilium monitor

# Filter by event type
cilium monitor -t policy-verdict -t trace

# Show packet traces from eBPF trace points
cilium monitor -t trace
```

#### perf tools

```bash
# Trace BPF program execution
perf record -e kprobe:*bpf* sleep 10
perf report

# Trace specific syscalls
perf trace --filter='syscall==bpf' sleep 10
```

### Verifying Policy Enforcement

#### Step 1: Understand the Flow

1. Packet arrives at container interface
2. `cil_from_container` ingress program executes
3. Program looks up policy in `cilium_policy_*` map
4. Decision: DROP, ALLOW, or REDIRECT

#### Step 2: Trace Packet Through Datapath

```bash
# Enable packet tracing in Cilium Monitor
cilium monitor -t trace

# Test connectivity
kubectl exec <pod1> -- ping <pod2-ip>

# Should see trace events showing packet path
```

#### Step 3: Inspect Policy Maps

```bash
# Get endpoint ID
kubectl get pod <pod> -o jsonpath='{.metadata.uid}' | head -c 8

# Dump policy map
bpftool map dump name cilium_policy_<endpoint-id>

# Expected entries: destination IP/port → verdict (allow/deny)
```

#### Step 4: Check Policy Compilation

```bash
# Verify policy is loaded
kubectl get networkpolicy

# Check Cilium sees it
cilium policy list

# Should match rules in policy map
```

### Common Issues and Solutions

#### Issue: "Verifier Rejected My Program"

**Symptoms**: Load fails with verifier error about "unreachable code" or "stack overflow"

**Debug**:
1. Check memory limit: Stack is 512 bytes
2. Look for unbounded loops
3. Check for excessive stack allocation
4. May need to refactor BPF code to be simpler

#### Issue: Programs Load But Policy Doesn't Enforce

**Debug Steps**:
```bash
# 1. Verify programs are attached
bpftool prog list | grep "cil_from"

# 2. Check if policy map has entries
bpftool map dump name cilium_policy_<id> | head

# 3. Monitor if program is executing
cilium monitor -t trace

# 4. If not executing, check interface setup
ip link show | grep <interface>
tc filter show dev <interface>
```

#### Issue: Memory Leak or Kernel Panic

**Common Cause**: eBPF map not cleaned up on endpoint deletion

**Prevention**: `deleteMaps()` in `pkg/endpoint/bpf.go:1019` should remove all pinned maps

**Check**:
```bash
# Look for orphaned maps
ls -la /sys/fs/bpf/tc/globals/ | grep -v cilium
```

### Performance Debugging

#### CPU Usage from eBPF Programs

```bash
# Use perf to profile BPF program execution
perf stat -e bpf-output sleep 10

# Flamegraph of kernel functions (including BPF)
perf record -F 99 -g sleep 30
perf script | stackcollapse-perf.pl > out.folded
flamegraph.pl out.folded > graph.svg
```

#### Memory Pressure from Maps

```bash
# Monitor BPF map memory usage
grep BPF /proc/meminfo

# If high, check which maps are largest
bpftool map list --json | jq '.[] | select(.bytes_key > 1000)' | jq '.name'
```

#### Latency Analysis

**Tail call depth**: Excessive tail calls can increase latency
```bash
# Count tail calls in program
bpftool prog dump id <id> opcodes | grep "tail_call" | wc -l
```

### Logs and Metrics

**Key Metrics** (from `pkg/datapath/loader/metrics/`):
- `cilium_bpf_load_prog_duration_seconds` - Time to load programs
- `cilium_bpf_maps_*` - Map statistics
- `cilium_policy_map_pressure_*` - Policy map fullness

**Log Locations**:
- `/var/log/cilium/cilium.log` - Main Cilium logs
- `journalctl -u cilium` - Systemd journal
- Docker: `docker logs <cilium-container>`
- Kubernetes: `kubectl logs -n kube-system -l k8s-app=cilium`

---

## 7. Adding a New Hook

### Overview: Adding a New eBPF Hook Point

A hook point is a kernel location where an eBPF program can be attached to process packets. Examples:
- TC ingress/egress (current)
- XDP (current)
- cgroup socket (for sockets)
- Custom kernel probes

### Step-by-Step Process

#### Step 1: Define the Hook and Program Type

**Determine**:
- What kernel subsystem (tc, XDP, cgroup, etc.)?
- What program type: `ebpf.SchedCLS`, `ebpf.XDP`, `ebpf.CGroupSKB`, etc.?
- Where does the packet come from/go to?

**Add to constants** in `pkg/datapath/loader/loader.go`:
```go
const (
    symbolMyNewHook = "cil_my_new_hook"
)
```

#### Step 2: Create eBPF Source Program

**File**: `bpf/bpf_my_hook.c`

```c
#include <bpf/ctx/skb.h>
#include <bpf/api.h>
#include <node_config.h>

#define IS_BPF_MY_HOOK 1
#define EVENT_SOURCE MY_HOOK_ID

#include "lib/common.h"
#include "lib/maps.h"
#include "lib/policy.h"

__section("classifier/ingress")
int cil_my_new_hook(struct __ctx_buff *ctx) {
    // Your packet processing logic
    return CTX_ACT_OK;  // or CTX_ACT_DROP
}

// Other required sections
char _license[] __section("license") = "GPL";
```

**Key Considerations**:
- Program type determines available helpers (see BPF API docs)
- Context type differs: `skb` for tc, `xdp_md` for XDP, `__ctx_buff` for generic
- Must include appropriate header files for your use case
- Use `__always_inline` for small helper functions
- Stack limited to 512 bytes total

#### Step 3: Add Compilation Support

**File**: `pkg/datapath/loader/compile.go`

Add program definition:
```go
const (
    myNewHookPrefix = "bpf_my_hook"
    myNewHookProg   = myNewHookPrefix + ".c"
    myNewHookObj    = myNewHookPrefix + ".o"
)

var myNewHookProgInfo = &progInfo{
    Source:     myNewHookProg,
    Output:     myNewHookObj,
    OutputType: outputObject,
}
```

Add to compilation list (in `compileDatapath()` function):
```go
progs := []progInfo{
    // existing programs...
    myNewHookProgInfo,
}
```

#### Step 4: Add Loading and Attachment Logic

**Determine Attachment Point**:

Create a new file like `pkg/datapath/loader/myhook.go` if complex, or add to existing attachment file.

**Example Pattern** (from tc.go and xdp.go):

```go
package loader

import (
    "github.com/cilium/ebpf"
    "github.com/vishvananda/netlink"
)

// attachMyHookProgram attaches the new hook program to device
func attachMyHookProgram(device netlink.Link, prog *ebpf.Program, progName, bpffsDir string) error {
    if prog == nil {
        return fmt.Errorf("program %s is nil", progName)
    }

    // Hook-specific attachment logic
    // For TC: use attachTCProgram()
    // For XDP: use attachXDPProgram()
    // For cgroup: use link.AttachCGroup()

    return nil
}

// detachMyHookProgram removes the hook program
func detachMyHookProgram(device netlink.Link, progName, bpffsDir string) error {
    // Hook-specific detachment logic
    return nil
}
```

#### Step 5: Integrate with ReloadDatapath()

**In `loader.go`, update `reloadDatapath()` or `reloadHostDatapath()`**:

```go
func (l *loader) reloadDatapath(ep datapath.Endpoint, spec *ebpf.CollectionSpec) error {
    // ... existing code ...

    // Load and attach your new hook
    if err := attachMyHookProgram(device, coll.Programs[symbolMyNewHook],
        symbolMyNewHook, bpffsDir); err != nil {
        return fmt.Errorf("attaching my hook: %w", err)
    }

    if err := commit(); err != nil {
        return fmt.Errorf("committing bpf pins: %w", err)
    }

    // ... rest of function ...
}
```

#### Step 6: Add Map Management (If Needed)

If your hook needs to access data from Go (policies, configuration), populate maps:

**In `pkg/datapath/loader/loader.go`**:
```go
// After loading programs but before attaching
if pm, ok := spec.Maps[yourMapName]; ok {
    // Populate map entries
    // Example: Add policy rules
}
```

#### Step 7: Add Feature Detection

**In `pkg/datapath/linux/probes/probes.go`**:

```go
// HaveMyHookSupport returns nil if the kernel supports your hook
func HaveMyHookSupport() error {
    // Create minimal test program with your program type
    spec := &ebpf.ProgramSpec{
        Type: ebpf.YourProgramType,
        // minimal instructions
    }
    p, err := ebpf.NewProgram(spec)
    if err != nil {
        return fmt.Errorf("my hook not supported: %w", ebpf.ErrNotSupported)
    }
    defer p.Close()
    return nil
}
```

**In daemon startup** (e.g., `daemon/cmd/daemon.go`):
```go
if myHookEnabled {
    if err := probes.HaveMyHookSupport(); err != nil {
        return fmt.Errorf("kernel does not support my hook: %w", err)
    }
}
```

#### Step 8: Add Cleanup

**In `Unload()` method**:
```go
func (l *loader) Unload(ep datapath.Endpoint) {
    // ... existing cleanup ...

    // Cleanup your hook
    link, err := safenetlink.LinkByName(ep.InterfaceName())
    if err == nil {
        if err := detachMyHookProgram(link, symbolMyNewHook, linkDir); err != nil {
            log.WithError(err).Warnf("Removing my hook from interface %s", ep.InterfaceName())
        }
    }
}
```

#### Step 9: Add Tests

**File**: `pkg/datapath/loader/myhook_test.go`

```go
package loader

import (
    "testing"
    "github.com/stretchr/testify/require"
)

func TestMyHookAttachment(t *testing.T) {
    // Setup
    testutils.PrivilegedTest(t)

    // Create dummy interface
    // Compile program
    // Attach program
    // Verify attachment
    // Cleanup

    require.NoError(t, err)
}
```

### Example: Adding a Custom Packet Filter Hook

**Real-world example**: Adding a custom packet filtering hook on ingress

```c
// bpf/bpf_custom_filter.c
#define IS_BPF_CUSTOM_FILTER 1
#include "lib/common.h"
#include "lib/maps.h"

// Map for custom filter rules
struct {
    __uint(type, BPF_MAP_TYPE_HASH);
    __uint(max_entries, 10000);
    __type(key, __u32);
    __type(value, __u32);
} custom_filter_rules __section_maps_btf;

__section("classifier/ingress")
int cil_custom_filter(struct __ctx_buff *ctx) {
    // Get packet destination IP
    __u32 dstip = /* extract from packet */;

    // Check if in filter rules
    __u32 *rule = bpf_map_lookup_elem(&custom_filter_rules, &dstip);
    if (!rule) {
        return CTX_ACT_OK;  // Allow if not in rules
    }

    // Apply rule
    if (*rule == FILTER_DROP) {
        return DROP_POLICY_DENIED;
    }

    return CTX_ACT_OK;
}

char _license[] __section("license") = "GPL";
```

### Program Array Registration

If your hook needs to tail-call into other programs:

```c
// In your program header
#define CALLS_MAP_ID 100
// Register tail call in CALLS_MAP
tail_call(ctx, &CALLS_MAP, CALLS_MAP_ID);
```

**Populate in Go**:
```go
// resolveAndInsertCalls fills the program array
calls := []ebpf.MapKV{
    {Key: uint32(100), Value: "cil_my_hook"},
}
resolveAndInsertCalls(coll, "cilium_calls", calls)
```

### Performance Considerations

- **Helper functions**: Check kernel version supports required helpers (see `probes.go`)
- **Memory**: Total eBPF stack is 512 bytes - keep it tight
- **Complexity**: BPF verifier has limits; simpler is better
- **Tail calls**: Each tail call adds latency (~100ns)
- **Map lookups**: Hash maps are O(n) worst case; limit or use BPF_MAP_TYPE_ARRAY for known ranges

### Integration with Policy Engine

If your hook needs policy decisions:

1. **Query policy map**: `cilium_policy_*` during packet processing
2. **Policy format**: Maps policy ID (from packet metadata) to action
3. **Return codes**: CTX_ACT_OK (allow), DROP_* (deny)
4. **Custom actions**: Create new DROP_* constants for your hook

### Debugging Your New Hook

```bash
# 1. Check compilation
ls -la <output-dir>/bpf_my_hook.o

# 2. Check loading
bpftool prog list | grep my_hook

# 3. Check attachment
bpftool prog show id <id>

# 4. Trace execution
cilium monitor -t trace

# 5. Check map operations
bpftool map dump name <your-map-name>

# 6. Verify verifier logs if load fails
# Check logs for "Verifier error"
```

---

## Architecture Diagrams

### Program Loading Pipeline

```
┌──────────────────────────────────┐
│  Daemon.Initialize()             │
│  Loader.Reinitialize()           │
└────────────┬─────────────────────┘
             │
       ┌─────▼──────────┐
       │ Write Headers  │
       │ node_config.h  │
       │ netdev_config.h│
       └─────┬──────────┘
             │
    ┌────────▼────────┐
    │ Compile BPF     │
    │ C → Object File │
    │ clang --target=bpf
    └────────┬────────┘
             │
    ┌────────▼─────────────┐
    │ Load into Kernel     │
    │ ebpf-go CollectionAPI
    │ Verifier validates   │
    └────────┬─────────────┘
             │
    ┌────────▼──────────────────┐
    │ Populate Maps            │
    │ Policy, CT, LB, etc.     │
    └────────┬──────────────────┘
             │
    ┌────────▼─────────────────┐
    │ Attach to Interfaces    │
    │ TC/TCX/XDP/Netkit      │
    └────────┬────────────────┘
             │
    ┌────────▼────────┐
    │ Pin to BPFfs   │
    │ /sys/fs/bpf/   │
    └────────────────┘
```

### Kernel eBPF Program Execution

```
Network Packet
      │
      ▼
┌─────────────────────────────────┐
│ Ingress TC Hook (cil_from_*)   │
├─────────────────────────────────┤
│ 1. Get packet metadata (IP, L4) │
│ 2. Lookup security identity    │
│ 3. Check policy rules          │
│ 4. Handle NAT/LB if needed     │
│ 5. Update connection tracking  │
│ 6. Return decision (OK/DROP)   │
└─────────────────────────────────┘
      │
      ├─► Drop (permission denied)
      │
      └─► Forward to application
                 │
                 ▼ (on egress)
┌─────────────────────────────────┐
│ Egress TC Hook (cil_to_*)      │
├─────────────────────────────────┤
│ 1. Check egress policy         │
│ 2. Apply encryption if needed  │
│ 3. Encapsulate for overlay     │
│ 4. Update connection state     │
│ 5. Return to kernel stack      │
└─────────────────────────────────┘
```

---

## Quick Reference

### Key Commands for Daily Operations

```bash
# View all eBPF maps
bpftool map list

# Monitor eBPF events
cilium monitor

# Check program load status
bpftool prog list | grep cilium

# View specific endpoint policy
bpftool map dump name cilium_policy_<id>

# Test connectivity with tracing
kubectl exec <pod> -- ping <other-pod> && cilium monitor -t trace

# Debug compilation issues
journalctl -u cilium | grep verifier

# Clean up stale BPF objects
rm -rf /sys/fs/bpf/tc/
systemctl restart cilium
```

### Key File Locations

```
/sys/fs/bpf/                       # BPF filesystem (pinned objects)
/sys/fs/bpf/tc/                    # TC programs and maps
/sys/fs/bpf/tc/globals/            # Global maps (policies, LB, etc.)
/var/lib/cilium/                   # Cilium state directory
/var/lib/cilium/templates/         # Compiled program templates
```

### Important Environment Variables

```bash
# Cilium daemon configuration
CILIUM_BPF_DIR              # Path to bpf/ source directory
CILIUM_LB_MAP_MAX_ENTRIES   # Service backend capacity
CILIUM_CT_MAP_SIZE_*        # Connection tracking map size
```

---

## Key References and Further Reading

### Internal Documentation
- `bpf/` - All eBPF source programs
- `Documentation/reference-guides/bpf/` - BPF architecture guide
- `Documentation/contributing/development/codeoverview.rst` - Code structure

### Related Subsystems
- `pkg/endpoint/` - Endpoint lifecycle management
- `pkg/policy/` - Policy compilation
- `pkg/service/` - Load balancing
- `pkg/identity/` - Security identity management

### External Resources
- BPF Kernel Documentation: https://docs.kernel.org/bpf/
- cilium/ebpf Library: https://github.com/cilium/ebpf
- Linux Kernel Sources: https://kernel.org (especially kernel/bpf/)

---

## Transition Notes for New Team Members

### First Week Tasks
1. Familiarize with basic eBPF concepts (kernel docs)
2. Read through this document and linked code
3. Set up local development environment (see contributing guide)
4. Run existing tests: `go test ./pkg/datapath/loader/...`
5. Trace through a real endpoint creation with debug logs enabled

### Second Week Tasks
1. Add a simple feature to an eBPF program (e.g., new map lookup)
2. Debug a compilation or loading failure in test environment
3. Write a new test for loader functionality
4. Review recent changes to understand current state

### Third Week Tasks
1. Implement a small new feature (policy rule type, metric, etc.)
2. Debug performance issue in test environment
3. Contribute documentation improvements

### Getting Help
- Code review: Check MAINTAINERS.md and codeowners
- eBPF Questions: #ebpf Slack channel
- Architecture: Ask during architecture discussion time
- Kernel Issues: Check cilium/cilium issues, may need kernel upgrade

---

**Document Version**: 1.0
**Last Updated**: 2024
**Cilium Version**: 1.16.5
