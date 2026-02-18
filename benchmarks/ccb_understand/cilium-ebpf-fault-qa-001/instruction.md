# Debug Q&A: Cilium eBPF Fault Isolation

**Repository:** cilium/cilium
**Task Type:** Debug Q&A (investigation only — no code changes)

## Background

Cilium is a Kubernetes CNI (Container Network Interface) plugin that uses eBPF (Extended Berkeley Packet Filter) programs to enforce network policies and route traffic. In a multi-node Kubernetes cluster, each node runs its own Cilium agent which compiles, loads, and attaches eBPF programs to enforce policies.

## Behavior Observation

**What happens:** When an eBPF program fails to compile or load on one Kubernetes node (e.g., due to a kernel verifier rejection, compilation error, or incompatible kernel features), the other nodes in the cluster continue to enforce their network policies normally. The failing node may log errors or degrade to a fallback mode, but the failure doesn't propagate cluster-wide.

**Why is this notable?** Many distributed systems that rely on shared state or centralized configuration can fail cluster-wide when one node encounters a problem. Cilium's architecture ensures that eBPF datapath failures are isolated to the affected node.

## Questions

Answer ALL of the following questions to explain this behavior:

### Q1: Per-Node eBPF Lifecycle

How are eBPF programs compiled, loaded, and attached on each node independently?
- What component is responsible for compiling eBPF programs on each node?
- How does node-specific configuration (kernel version, enabled features, etc.) affect compilation?
- At what point in the lifecycle does the eBPF program become node-local vs. cluster-wide?

### Q2: Deployment Architecture

How does Cilium's deployment model ensure per-node isolation?
- How is the Cilium agent deployed across the cluster (DaemonSet, static pods, etc.)?
- What happens when one node's Cilium agent fails to initialize its eBPF programs?
- How does the control plane vs. data plane split contribute to isolation?

### Q3: Policy Distribution vs. Enforcement

Cilium network policies are cluster-wide resources (CRDs), but enforcement is per-node. How does this work?
- How are CiliumNetworkPolicy resources distributed to each node?
- What component on each node translates policies into eBPF bytecode?
- Why doesn't a compilation failure on one node block policy distribution to other nodes?

### Q4: eBPF Map Scoping and State Isolation

eBPF programs use maps (hash tables, arrays) to store state. How is map state isolated across nodes?
- Are eBPF maps node-local or cluster-wide?
- What mechanisms (BPF filesystem pinning, namespaces) ensure map isolation?
- If a node fails to create or update a map, how does that affect other nodes' packet processing?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Cilium eBPF Fault Isolation

## Q1: Per-Node eBPF Lifecycle
<answer with specific file paths, class names, and function references>

## Q2: Deployment Architecture
<answer with specific file paths, class names, and function references>

## Q3: Policy Distribution vs. Enforcement
<answer with specific file paths, class names, and function references>

## Q4: eBPF Map Scoping and State Isolation
<answer with specific file paths, class names, and function references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, classes, and functions — avoid vague or speculative answers
- Focus on the `pkg/datapath/loader/`, `pkg/policy/`, `pkg/maps/`, and `pkg/endpoint/` directories
