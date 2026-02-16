# Investigation: Pods Scheduled on Unreachable Nodes During Network Partition

**Repository:** kubernetes/kubernetes
**Task Type:** Multi-Component Interaction (investigation only — no code fixes)

## Scenario

A Kubernetes cluster operator reports that during network partitions, new pods are being scheduled onto nodes that have already lost connectivity. The pods remain in `Pending` or `ContainerCreating` state indefinitely on these unreachable nodes, rather than being quickly rescheduled elsewhere.

The timeline of events is:

1. A node `worker-03` stops sending heartbeats (simulating network partition)
2. After approximately 40 seconds, the node is detected as unresponsive and its `Ready` condition is set to `Unknown`
3. A `NoSchedule` taint (`node.kubernetes.io/unreachable:NoSchedule`) is added promptly
4. However, there is a **~5-second delay** before the `NoExecute` taint (`node.kubernetes.io/unreachable:NoExecute`) is applied
5. During this window, pods with `NoSchedule` tolerations (which many system pods and DaemonSet pods have) can still be scheduled onto the unreachable node
6. Once the `NoExecute` taint finally arrives, eviction begins — but newly scheduled pods during the window are already stuck on an unreachable node

The operator's logs show the delay:

```
I0115 10:23:40.001] Node worker-03 ReadyCondition updated. Updating timestamp
I0115 10:23:40.002] Node worker-03 is unresponsive. Setting NodeReady to Unknown
I0115 10:23:40.003] Adding NoSchedule taint to node worker-03
# ... ~5 second gap (one monitoring cycle) ...
I0115 10:23:45.001] Node worker-03 is unresponsive. Adding it to the Taint queue
I0115 10:23:45.002] Adding NoExecute taint to node worker-03
```

The gap between `NoSchedule` and `NoExecute` taints indicates something is preventing the `NoExecute` taint from being applied in the same cycle that the node is first detected as unreachable.

## Your Task

Investigate the root cause of the delayed `NoExecute` taint application. Your investigation must cover:

1. **Identify ALL interacting components** — at least 3 distinct Kubernetes subsystems contribute to this problem. Determine which controllers, plugins, and subsystems interact and what each one's role is in the failure
2. **The specific timing condition** — why the `NoExecute` taint is delayed by exactly one monitoring cycle after the node is detected as unreachable
3. **The root cause** — identify the specific function call, parameter, or variable that causes the taint application to be delayed by one cycle
4. **The data flow** — trace how node health information flows from detection through to taint decisions, identifying where stale vs fresh data is used
5. **The scheduling impact** — how the delayed taint creates a window for undesirable scheduling decisions
6. **The full interaction chain** — which files and functions form the complete path from heartbeat loss to delayed eviction

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding>

## Root Cause
<Specific file, function, and mechanism>

## Evidence
<Code references with file paths and line numbers>

## Affected Components
<List of packages/modules impacted — must identify all interacting components>

## Causal Chain
<Ordered list: heartbeat loss → detection → taint delay → scheduling window → eviction>

## Recommendation
<Fix strategy and diagnostic steps>
```

## Constraints

- Do NOT write any code fixes
- Do NOT modify any source files
- Your job is investigation and analysis only
- The bug involves interaction between multiple Kubernetes control plane components — no single component is at fault in isolation
- Start from the symptom (delayed NoExecute taint) and trace backward through the code to find the root cause
