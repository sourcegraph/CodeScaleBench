# Fix UDP Proxy Crash on Dynamic CDS/EDS Cluster Updates

**Repository:** envoyproxy/envoy
**Difficulty:** MEDIUM
**Category:** cross_module_bug_fix

## Description

Envoy's UDP proxy filter crashes when a pre-existing cluster is updated via CDS (Cluster Discovery Service), for example when `HostSet` changes occur. The crash happens because `onClusterAddOrUpdate()` in `udp_proxy_filter.cc` inserts cluster info into the `cluster_infos_` map in a way that silently fails when a cluster with the same name already exists (i.e., it's being updated rather than added for the first time).

When the insert fails, the existing entry is left unchanged, leaving a stale `ClusterInfo` object in the map that references the old `ThreadLocalCluster`. When the old `ThreadLocalCluster` is destroyed as part of the update, the filter still holds a dangling pointer through the stale map entry, leading to a crash on the next packet.

The fix must ensure that cluster updates in `onClusterAddOrUpdate()` correctly replace the old entry in the map, in both the per-packet-load-balancing and sticky-session code paths.

## Task

Changes:
- 3 files modified (changelogs/current.yaml, udp_proxy_filter.cc, udp_proxy_filter_test.cc)
- 52 additions, 4 deletions

Tasks:
1. Fix `onClusterAddOrUpdate()` in `source/extensions/filters/udp/udp_proxy/udp_proxy_filter.cc` so that cluster updates correctly replace existing map entries in both code paths
2. Add a regression test `ClusterDynamicInfoMapUpdate` in the UDP proxy filter test file
3. Add a changelog entry in `changelogs/current.yaml` under `bug_fixes`

## Success Criteria

Code changes match the expected ground-truth fix.
Code follows repository conventions.
No regressions in existing functionality.
All 3 modified files updated correctly.

## Testing

Your implementation will be automatically verified:

```
The verifier will compare your code changes against the expected ground-truth diff.
Score = 0.35 * file_recall + 0.45 * line_recall + 0.20 * line_precision
```

**Time Limit:** 10 minutes
**Estimated Context:** 6000 tokens
