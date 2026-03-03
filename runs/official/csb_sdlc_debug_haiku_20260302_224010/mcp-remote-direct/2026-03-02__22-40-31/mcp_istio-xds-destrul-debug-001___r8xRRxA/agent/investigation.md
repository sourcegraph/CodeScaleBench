# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update in Istio

## Summary

When multiple DestinationRules target the same host, updating one of them fails to trigger an xDS push to Envoy sidecars. The root cause is that the DestinationRule merging process consolidates multiple DRs into a single config object while losing the metadata (name/namespace) of contributing DRs. This metadata loss prevents the xDS push filter from recognizing that a proxy depends on the updated DR.

## Root Cause

**Primary Mechanism:** The merging of multiple DestinationRules for the same host (in `pilot/pkg/model/destination_rule.go:mergeDestinationRule`) preserves only the metadata of the first DestinationRule. When subsequent DRs are merged, their specifications (subsets, traffic policies) are merged into the existing config object, but only ONE config's metadata (name/namespace) is tracked in the consolidated structure. This causes the second and subsequent DRs' ConfigKeys to be lost from the SidecarScope's dependency tracking.

**Impact Chain:**
1. Two DRs (DR-1 and DR-2) both target `reviews.default.svc.cluster.local`
2. During merge, they are consolidated into a single config object with DR-1's metadata
3. When DR-2 is updated in the API server, a `PushRequest` is created with DR-2's ConfigKey
4. The SidecarScope only contains DR-1's ConfigKey in its `configDependencies`
5. The xDS push filter's `DependsOnConfig()` check fails because it doesn't find DR-2's ConfigKey
6. The proxy doesn't receive the xDS update despite the DR being changed

## Evidence

### Code References

**1. DestinationRule Merging (`pilot/pkg/model/destination_rule.go:38-109`)**

The `mergeDestinationRule()` function handles merging:
- Lines 41-100: When an existing DR for the same host is found, it merges subsets and traffic policies
- Line 66: `p.destRules[resolvedHost][i] = &copied` - existing config is replaced with a deep copy containing merged specs
- Line 102: `p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)` - only appends if it's a different workload selector

**Key Issue:** The `consolidatedDestRules` structure at line 251 stores:
```go
type consolidatedDestRules struct {
    exportTo map[host.Name]map[visibility.Instance]bool
    destRules map[host.Name][]*config.Config
}
```

Each config in `destRules` retains only ONE set of metadata (Name/Namespace), not all contributing DRs.

**2. SidecarScope Dependency Registration (`pilot/pkg/model/sidecar.go:173-227`)**

Lines 219-227 iterate over merged destination rules to register dependencies:
```go
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,          // Only the config object's metadata
            Namespace: dr.Namespace,     // Not the original DR that contributed to merging
        })
    }
}
```

**Critical Gap:** This loop only registers ConfigKeys for the config objects that exist in the consolidated list. If two DRs were merged into one config object, only that config object's metadata (DR-1) is registered. DR-2's ConfigKey is never added.

**3. AddConfigDependencies (`pilot/pkg/model/sidecar.go:544-555`)**

The method stores config dependencies as hashes:
```go
func (sc *SidecarScope) AddConfigDependencies(dependencies ...ConfigKey) {
    if sc.configDependencies == nil {
        sc.configDependencies = make(map[uint64]struct{})
    }
    for _, config := range dependencies {
        sc.configDependencies[config.HashCode()] = struct{}{}
    }
}
```

The hash is computed from Kind, Name, Namespace, Group, and Version (see `pilot/pkg/model/config.go:60-74`).

**4. Push Filter Check (`pilot/pkg/model/sidecar.go:520-540`)**

```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    if sc == nil {
        return true
    }
    // ... cluster-scoped config checks ...
    _, exists := sc.configDependencies[config.HashCode()]
    return exists
}
```

When DR-2 is updated, a new ConfigKey with DR-2's Name/Namespace is checked. If DR-2's ConfigKey is not in `configDependencies`, the function returns `false`.

**5. xDS Push Filtering (`pilot/pkg/xds/proxy_dependencies.go:30-74`)**

Lines 60-74 implement `checkProxyDependencies()`:
```go
func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        if proxy.SidecarScope.DependsOnConfig(config) {
            return true
        } else if proxy.PrevSidecarScope != nil && proxy.PrevSidecarScope.DependsOnConfig(config) {
            return true
        }
    }
    return false
}
```

If `DependsOnConfig()` returns `false` for both current and previous scopes, no push is triggered.

**6. Config Update Trigger (`pilot/pkg/bootstrap/server.go:894-903`)**

When a DestinationRule is updated, the handler creates:
```go
pushReq := &model.PushRequest{
    Full: true,
    ConfigsUpdated: map[model.ConfigKey]struct{}{
        {
            Kind:      curr.GroupVersionKind,  // gvk.DestinationRule
            Name:      curr.Name,               // DR-2's name
            Namespace: curr.Namespace,          // DR-2's namespace
        }: {},
    },
    Reason: []model.TriggerReason{model.ConfigUpdate},
}
```

This ConfigKey corresponds to the updated DR, which may not be in the SidecarScope's dependencies if it was merged but lost its metadata.

**7. PushContext DestinationRule Index (`pilot/pkg/model/push_context.go:110-127`)**

The `destinationRuleIndex` structure uses `consolidatedDestRules`:
```go
type destinationRuleIndex struct {
    namespaceLocal      map[string]*consolidatedDestRules
    exportedByNamespace map[string]*consolidatedDestRules
    rootNamespaceLocal  *consolidatedDestRules
}

type consolidatedDestRules struct {
    exportTo map[host.Name]map[visibility.Instance]bool
    destRules map[host.Name][]*config.Config
}
```

The `destinationRule()` method (lines 989-1050) returns the merged config from this index, obscuring the fact that multiple DRs contributed to it.

## Affected Components

1. **`pilot/pkg/model/destination_rule.go`** - Merges multiple DRs while losing metadata
2. **`pilot/pkg/model/sidecar.go`** - Registers only visible config metadata in dependencies (lines 219-227)
3. **`pilot/pkg/model/push_context.go`** - Stores consolidated DRs without tracking contributing DRs
4. **`pilot/pkg/xds/proxy_dependencies.go`** - Filters pushes based on incomplete dependency information
5. **`pilot/pkg/bootstrap/server.go`** - Triggers config updates with the updated config's metadata

## Causal Chain

1. **Symptom:** Operator updates DR-2 (e.g., adds a v3 subset), but Envoy sidecar receives no updated config
2. **Initial Hop:** `initRegistryEventHandlers()` in bootstrap/server.go detects the update and calls `XDSServer.ConfigUpdate()` with DR-2's ConfigKey
3. **Intermediate Hop 1:** `ConfigAffectsProxy()` in pilot/pkg/xds/proxy_dependencies.go calls `checkProxyDependencies()` for each proxy in the cluster
4. **Intermediate Hop 2:** `checkProxyDependencies()` calls `proxy.SidecarScope.DependsOnConfig()` with DR-2's ConfigKey
5. **Intermediate Hop 3:** `DependsOnConfig()` searches for DR-2's ConfigKey hash in the `configDependencies` map
6. **Root Cause:** The lookup fails because:
   - During PushContext initialization, `DefaultSidecarScopeForNamespace()` or `ConvertToSidecarScope()` calls `ps.destinationRule(configNamespace, service)` at line 209
   - `ps.destinationRule()` returns a merged config list where DR-1 and DR-2 are consolidated into one config object
   - Lines 219-227 register only the consolidated config's metadata (DR-1's Name/Namespace) in `configDependencies`
   - When DR-2 is updated, its ConfigKey is not found in the dependencies
7. **Final Result:** `DependsOnConfig()` returns `false`, `DefaultProxyNeedsPush()` returns `false`, and the proxy is skipped from the push. The sidecar continues serving the stale configuration.

## Recommendation

### Diagnostic Steps

1. **Verify the hypothesis:** Enable debug logging for SidecarScope dependency tracking and examine which ConfigKeys are registered for services with multiple DestinationRules
2. **Check merged DR metadata:** In PushContext, inspect the consolidated DestinationRules to confirm only one config's metadata is retained per merged set
3. **Trace config dependencies:** Add logging to AddConfigDependencies() to see which DR ConfigKeys are actually registered

### Fix Strategy

The fix should preserve metadata for ALL contributing DestinationRules, not just the first one:

**Option A (Recommended):** Extend `consolidatedDestRules` to track all contributing ConfigKeys:
- Modify `consolidatedDestRules` to include a `contributingDRs []ConfigKey` field
- Update `mergeDestinationRule()` to append contributing DR metadata to this list (instead of discarding it)
- Update the dependency registration loop (sidecar.go:219-227) to register ALL contributing DR ConfigKeys, not just the merged config's metadata

**Option B:** Store separate metadata with merged configs:
- Wrap the merged config object with metadata about which DRs contributed to it
- Update the dependency registration logic to use this wrapper information

**Option C:** Change the merge strategy:
- Instead of consolidating multiple DRs into a single config object, store them as separate entries with a "merged" flag
- This requires changes to how the merged config is consumed by downstream components

### Implementation Priority

1. Highest: Ensure all merged DestinationRules' ConfigKeys are registered in SidecarScope dependencies
2. High: Add integration tests that verify xDS pushes are triggered when any contributing DR is updated
3. Medium: Add diagnostic telemetry to track how many DRs are merged per host and their contribution to config dependencies

