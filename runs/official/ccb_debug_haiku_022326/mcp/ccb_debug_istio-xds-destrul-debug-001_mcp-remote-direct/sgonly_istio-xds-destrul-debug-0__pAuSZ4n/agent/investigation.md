# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update

## Summary

When multiple DestinationRules are configured for the same host, updating one of them silently fails to trigger an xDS push to Envoy sidecars. The root cause is that the DestinationRule merging process in Istio's PushContext consolidates multiple DRs into a single config object while retaining only one DR's metadata (name/namespace), causing the second DR's updates to be invisible to the config dependency tracking system.

## Root Cause

The bug is a metadata loss during DestinationRule merging combined with incomplete config dependency tracking:

1. **DestinationRule Merging (pilot/pkg/model/destination_rule.go)**: When two or more DRs target the same host and have matching workload selectors (or no selectors), the `mergeDestinationRule()` function (line 38) merges them into a single consolidated config object. The merged object is created by deep-copying the first DR's config (line 65) and adding subsets/traffic policies from subsequent DRs to it.

2. **Metadata Retention**: The merged config object retains the `Meta` (Name and Namespace) of the **first** DR only. The second and subsequent DRs' metadata is discarded—only their Spec fields (subsets, traffic policies) are merged into the consolidated object.

3. **Single Config Registration**: In SidecarScope (pilot/pkg/model/sidecar.go, lines 219-227), when iterating through destination rules to register config dependencies, only the merged config's Name and Namespace are extracted and added to `configDependencies`. This means only the **first DR's ConfigKey** is registered.

4. **Push Filter Failure**: When the second DR is updated in Kubernetes, a PushRequest is created with a ConfigKey containing the second DR's name/namespace. However, when `DependsOnConfig()` (pilot/pkg/model/sidecar.go, line 523) checks the proxy's dependencies, it looks up the ConfigKey's hash in `configDependencies` and finds no match—because only the first DR was registered. The function returns `false`, causing `ConfigAffectsProxy()` to skip the proxy, and **no xDS push is sent**.

## Evidence

### mergeDestinationRule() Function
- **File**: `pilot/pkg/model/destination_rule.go`
- **Lines**: 38-109
- **Key observations**:
  - Line 41: Checks if a merged list exists for the hostname
  - Line 65: `copied := mdr.DeepCopy()` — Deep copies only the first DR
  - Line 66: `p.destRules[resolvedHost][i] = &copied` — Replaces the first entry with the merged copy
  - Lines 77-87: Merges subsets from the incoming DR into the merged config
  - Lines 91-93: Merges traffic policy if missing
  - Line 101: `if addRuleToProcessedDestRules` is false — the second DR is never added to the list
  - **Result**: Only the first DR's metadata survives; the second DR's metadata is lost

### consolidatedDestRules Structure
- **File**: `pilot/pkg/model/push_context.go`
- **Lines**: 251-256
- **Key fields**:
  - `destRules map[host.Name][]*config.Config` — Map of merged config objects
  - When multiple DRs for the same host are merged, the list contains only one config object with the first DR's metadata

### Config Dependency Registration
- **File**: `pilot/pkg/model/sidecar.go`
- **Lines**: 219-227
- **Code**:
  ```go
  for _, drList := range out.destinationRules {
      for _, dr := range drList {
          out.AddConfigDependencies(ConfigKey{
              Kind:      gvk.DestinationRule,
              Name:      dr.Name,           // Only first DR's name!
              Namespace: dr.Namespace,       // Only first DR's namespace!
          })
      }
  }
  ```
- **Problem**: `dr.Name` and `dr.Namespace` come from the merged config's Meta field, which only contains the first DR's metadata

### SidecarScope.DependsOnConfig() Function
- **File**: `pilot/pkg/model/sidecar.go`
- **Lines**: 523-540
- **Key line**: 538: `_, exists := sc.configDependencies[config.HashCode()]`
- **Problem**: The lookup only finds the first DR's ConfigKey hash; the second DR's ConfigKey hash is never registered

### ConfigKey.HashCode() Function
- **File**: `pilot/pkg/model/config.go`
- **Lines**: 60-74
- **Calculates hash from**: Name, Namespace, Kind.Kind, Kind.Group, Kind.Version
- **Impact**: Different DR name/namespace = different hash = no match in dependencies map

### xDS Push Filter
- **File**: `pilot/pkg/xds/proxy_dependencies.go`
- **Lines**: 32-74
- **Function ConfigAffectsProxy()**:
  - Line 52: Calls `checkProxyDependencies(proxy, config)` for each updated config
  - **For SidecarProxy** (line 64): Calls `proxy.SidecarScope.DependsOnConfig(config)`
  - Returns true only if the config is in the proxy's dependencies
- **Impact**: If the second DR's ConfigKey is not in dependencies, `DependsOnConfig()` returns false, and the proxy is not pushed the update

## Affected Components

1. **pilot/pkg/model/destination_rule.go** — DestinationRule merging logic
2. **pilot/pkg/model/push_context.go** — PushContext and destinationRuleIndex structure
3. **pilot/pkg/model/sidecar.go** — SidecarScope config dependency tracking and DependsOnConfig()
4. **pilot/pkg/xds/proxy_dependencies.go** — Config change filtering for xDS pushes
5. **pilot/pkg/config/config.go** — ConfigKey and its hash function

## Causal Chain

1. **Symptom**: Updating the second DestinationRule does not propagate to Envoy sidecars
2. → Operator updates DestinationRule "reviews-subsets" in Kubernetes
3. → Kubernetes API server notifies Istio Pilot of the config change
4. → Pilot creates a PushRequest with ConfigsUpdated containing ConfigKey(DestinationRule, "reviews-subsets", "default")
5. → **Gap**: `pilot/pkg/model/sidecar.go:219-227` only registered ConfigKey(DestinationRule, "reviews-traffic-policy", "default") in configDependencies (the first DR's metadata)
6. → `pilot/pkg/xds/proxy_dependencies.go:52` calls `checkProxyDependencies(proxy, ConfigKey("reviews-subsets", ...))`
7. → `pilot/pkg/model/sidecar.go:523` (DependsOnConfig) looks up the hash of ConfigKey("reviews-subsets", ...) in configDependencies
8. → **Lookup fails** — the hash doesn't exist (only the first DR's hash is stored)
9. → `DependsOnConfig()` returns false
10. → Proxy is not included in the xDS push
11. → **Root cause**: Metadata loss during `mergeDestinationRule()` in `pilot/pkg/model/destination_rule.go:38-109`
    - The merged config only retains the first DR's metadata
    - The second DR's metadata is never stored anywhere
    - Therefore, the second DR's ConfigKey is never registered in dependencies
    - When the second DR is updated, its ConfigKey is not found in the dependencies map

## Recommendation

### Fix Strategy

The root cause requires a two-part fix:

1. **Track All Contributing DRs in Merged Config**: Store metadata about all DRs that contributed to the merged config, not just the first one. Options:
   - Add an `OriginalConfigs` or `ContributingDRs` field to the consolidated config to track all source DRs
   - Modify the consolidation data structure to maintain a list of all contributing DR names/namespaces

2. **Register All Contributing DRs in Dependencies**: When building the SidecarScope, iterate through all contributing DRs and register each one's ConfigKey:
   ```go
   // Instead of just:
   out.AddConfigDependencies(ConfigKey{Name: dr.Name, Namespace: dr.Namespace, ...})

   // Register all contributing DRs:
   for _, originalDR := range dr.ContributingDRs {
       out.AddConfigDependencies(ConfigKey{
           Name: originalDR.Name,
           Namespace: originalDR.Namespace,
           ...
       })
   }
   ```

### Diagnostic Steps for Users

1. **Identify merged DRs**: Check the Istio debug endpoint `/debug/config_dump` on the sidecar to see which DestinationRule is active
2. **Verify expectations**: Use `kubectl get destinationrule` to see all DRs for a host
3. **Check sidecar logs**: Look for "DependsOnConfig returned false" or similar dependency-related messages
4. **Verify push events**: Use Pilot logs to confirm whether ConfigUpdate events are being received for all DRs
5. **Monitor config dependencies**: Add logging to `SidecarScope.AddConfigDependencies()` to see which ConfigKeys are actually registered

### Preventive Measures

- Add unit tests in `pilot/pkg/model/sidecar_test.go` that verify all contributing DRs' ConfigKeys are registered when multiple DRs are merged
- Add integration tests that update each merged DR independently and verify xDS pushes occur
- Consider refactoring the DestinationRule consolidation to maintain explicit links to all contributing source configs

## Implementation Notes

The fix should be backwards compatible since it's adding additional dependencies, not removing them. Proxies will receive more frequent pushes in the case of multiple merged DRs, which is the correct behavior.
