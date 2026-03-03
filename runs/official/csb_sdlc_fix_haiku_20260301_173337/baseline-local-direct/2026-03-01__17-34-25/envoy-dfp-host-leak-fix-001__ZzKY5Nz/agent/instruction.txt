# Fix Memory Leak in Dynamic Forward Proxy Cluster

**Repository:** envoyproxy/envoy
**Difficulty:** HARD
**Category:** cross_module_bug_fix

## Description

Envoy's Dynamic Forward Proxy (DFP) cluster has a memory leak that occurs when a host's DNS resolution changes to a new IP address. When a DFP host initially resolves to IP address A, a `LogicalHost` is created and added to both the `host_map_` and the cross-priority host map (tracked by `MainPrioritySetImpl`). When the same host later re-resolves to IP address B, the current code updates the `LogicalHost`'s address in-place via `setNewAddresses()` without removing the old address from the cross-priority host map.

This means IP A remains in the cross-priority host map permanently. When the host's TTL expires and it is removed, only IP B is cleaned up from the map — IP A leaks. Over time, with repeated DNS re-resolution, the cross-priority host map grows without bound.

The fix refactors `addOrUpdateHost()` to remove the old host and create a new `LogicalHost` with the new address, properly emitting both `hosts_added` and `hosts_removed` events to the priority set. The method signature is simplified to remove the accumulated `hosts_added` vector pattern, and `updatePriorityState()` is called directly within `addOrUpdateHost()`. Debug logging is also added to `upstream_impl.cc` for cross-priority host map operations.

## Task

Changes:
- 4 files modified (upstream_impl.cc, cluster.cc, cluster.h, cluster_test.cc)
- 29 additions, 39 deletions

Tasks:
1. Add debug logging to `source/common/upstream/upstream_impl.cc` for cross-priority host map mutations
2. Refactor `addOrUpdateHost()` in `source/extensions/clusters/dynamic_forward_proxy/cluster.cc` to replace in-place address updates with host removal and re-creation
3. Simplify the `addOrUpdateHost()` signature in `cluster.h` (remove the `hosts_added` out-parameter)
4. Update test expectations in `cluster_test.cc` for the new per-host update notification pattern

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 4 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 15 minutes
**Estimated Context:** 10000 tokens
