# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update

## Summary

When multiple DestinationRules for the same host are merged during PushContext initialization, only the first DR's metadata (name/namespace) survives in the `consolidatedDestRules` structure. When a contributing DR is subsequently updated, the xDS push filter fails to recognize the dependency because the updated DR's ConfigKey is not registered in the SidecarScope's `configDependencies` map, causing the push to be silently skipped.

---

## Root Cause

The root cause spans a three-component chain:

1. **Metadata Loss During Merging** (`pilot/pkg/model/destination_rule.go`, `mergeDestinationRule()` function)
2. **Incomplete Dependency Registration** (`pilot/pkg/model/sidecar.go`, `AddConfigDependencies()` calls)
3. **Dependency-Based Push Filtering** (`pilot/pkg/xds/proxy_dependencies.go`, `checkProxyDependencies()` function)

When two DestinationRules targeting the same host are merged, only one merged config object persists with the first DR's name/namespace. The second DR's identity is lost. Later, when dependency tracking occurs, only the first DR's ConfigKey is registered. When the second DR is updated, the update event carries the second DR's ConfigKey, which is not found in the dependency map, causing the push to be filtered out.

---

## Evidence

### 1. Merging Logic Loses Metadata

**File:** `/workspace/pilot/pkg/model/destination_rule.go`
**Function:** `mergeDestinationRule()` (lines 38-109)

**Problematic sequence (lines 41-104):**
```go
if mdrList, exists := p.destRules[resolvedHost]; exists {
    addRuleToProcessedDestRules := true
    for i, mdr := range mdrList {
        existingRule := mdr.Spec.(*networking.DestinationRule)
        // ... check if should merge ...

        if bothWithoutSelector || (rule.GetWorkloadSelector() != nil && selectorsMatch) {
            addRuleToProcessedDestRules = false
        }

        // Deep copy destination rule, to prevent mutate it later when merge with a new one.
        copied := mdr.DeepCopy()
        p.destRules[resolvedHost][i] = &copied  // Line 66: Updates existing at index i
        mergedRule := copied.Spec.(*networking.DestinationRule)

        // Merge subsets and traffic policy into the FIRST DR's config...
        for _, subset := range rule.Subsets {
            if _, ok := existingSubset[subset.Name]; !ok {
                mergedRule.Subsets = append(mergedRule.Subsets, subset)
            }
        }

        if mergedRule.TrafficPolicy == nil && rule.TrafficPolicy != nil {
            mergedRule.TrafficPolicy = rule.TrafficPolicy
        }
    }
    if addRuleToProcessedDestRules {
        // Line 102: Only appended if NO merge was performed
        p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
    }
}
```

**Impact:** When two DRs without workload selectors exist for the same host:
- The loop finds a matching DR (the first one)
- `addRuleToProcessedDestRules` is set to false (line 60)
- The FIRST DR is mutated with merged content from the SECOND DR (lines 77-93)
- The SECOND DR is **not appended** to the list (line 102 skipped because `addRuleToProcessedDestRules` is false)
- Result: `p.destRules[resolvedHost]` contains only **one config object** with the **first DR's metadata** but merged content from both DRs

### 2. Consolidated Structure Stores Merged Configs Only

**File:** `/workspace/pilot/pkg/model/push_context.go`
**Data Structure:** `consolidatedDestRules` (lines 251-256)

```go
type consolidatedDestRules struct {
    // Map of dest rule host to the list of namespaces to which this destination rule has been exported to
    exportTo map[host.Name]map[visibility.Instance]bool
    // Map of dest rule host and the merged destination rules for that host
    destRules map[host.Name][]*config.Config  // Line 255: List of configs, but only ONE per merged group
}
```

When `SetDestinationRules()` processes configs via `mergeDestinationRule()`, the resulting `destRules` map contains merged configs, losing the identity of contributing DRs.

### 3. Dependency Registration Only Covers Merged Configs

**File:** `/workspace/pilot/pkg/model/sidecar.go`
**Function:** `DefaultSidecarScopeForNamespace()` (lines 173-251)

**Critical section (lines 209-211, 219-227):**
```go
// Line 209: Fetches merged configs from PushContext
if dr := ps.destinationRule(configNamespace, s); dr != nil {
    out.destinationRules[s.Hostname] = dr  // Line 210: dr is a list of MERGED configs
}

// Lines 219-227: Iterate over merged configs ONLY
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,           // Line 223: MERGED config's name
            Namespace: dr.Namespace,      // Line 224: MERGED config's namespace
        })
    }
}
```

**Similar code in `ConvertToSidecarScope()`** (lines 408-418):
```go
if drList := ps.destinationRule(configNamespace, s); drList != nil {
    out.destinationRules[s.Hostname] = drList
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,      // Only the FIRST (merged) DR's name
            Namespace: dr.Namespace, // Only the FIRST (merged) DR's namespace
        })
    }
}
```

**Impact:** When a service depends on merged DRs, only the first DR's ConfigKey is registered. The second DR's ConfigKey is never added to `configDependencies`.

### 4. destinationRule() Method Returns Merged Configs

**File:** `/workspace/pilot/pkg/model/push_context.go`
**Function:** `destinationRule()` (lines 990-1066)

**Key lines (1010, 1020, 1043, 1050):**
```go
// Returns from consolidatedDestRules.destRules[hostname]
return ps.destinationRuleIndex.namespaceLocal[proxyNameSpace].destRules[hostname]  // Line 1010
return ps.destinationRuleIndex.rootNamespaceLocal.destRules[hostname]               // Line 1020
return out  // from getExportedDestinationRuleFromNamespace                           // Line 1043
return out  // from getExportedDestinationRuleFromNamespace                           // Line 1050
```

All code paths return the merged configs from `consolidatedDestRules.destRules`, which contains only one config per merged group.

### 5. Push Filtering Uses DependsOnConfig

**File:** `/workspace/pilot/pkg/xds/proxy_dependencies.go`
**Functions:** `ConfigAffectsProxy()` (lines 32-58), `checkProxyDependencies()` (lines 60-74)

```go
// Line 32-58: ConfigAffectsProxy
for config := range req.ConfigsUpdated {
    affected := true
    // ... check proxy type ...
    if affected && checkProxyDependencies(proxy, config) {  // Line 52
        return true
    }
}
return false  // No config affected this proxy

// Line 60-74: checkProxyDependencies
func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        if proxy.SidecarScope.DependsOnConfig(config) {  // Line 64: THE CRITICAL CHECK
            return true
        } else if proxy.PrevSidecarScope != nil && proxy.PrevSidecarScope.DependsOnConfig(config) {
            return true
        }
    default:
        return true
    }
    return false
}
```

**File:** `/workspace/pilot/pkg/model/sidecar.go`
**Function:** `DependsOnConfig()` (lines 521-540)

```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    if sc == nil {
        return true
    }

    // ... cluster-scoped config check ...
    if _, f := clusterScopedConfigTypes[config.Kind]; f {
        return config.Namespace == sc.RootNamespace || config.Namespace == sc.Namespace
    }

    // ... unknown config type check ...
    if _, f := sidecarScopeKnownConfigTypes[config.Kind]; !f {
        return true
    }

    _, exists := sc.configDependencies[config.HashCode()]  // Line 538: Hash-based lookup
    return exists
}
```

**The failure:** When the second DR (reviews-subsets) is updated:
- `req.ConfigsUpdated` contains `ConfigKey{Kind: DestinationRule, Name: "reviews-subsets", Namespace: "default"}`
- `DependsOnConfig()` hashes this key and searches in `configDependencies`
- `configDependencies` only contains the hash of `ConfigKey{..., Name: "reviews-traffic-policy", ...}`
- The lookup returns `exists = false`
- `DependsOnConfig()` returns `false`
- Push is skipped

### 6. Push Request Flow

**File:** `/workspace/pilot/pkg/xds/ads.go`
**Function:** `PushProcess()` (lines 683-724, specifically line 688)

```go
if pushRequest.Full {
    s.updateProxy(con.proxy, pushRequest)  // Line 685: Proxy info updated
}

if !s.ProxyNeedsPush(con.proxy, pushRequest) {  // Line 688: THE FILTER
    log.Debugf("Skipping push to %v, no updates required", con.conID)
    return nil
}
// ... continue with push ...
```

The call to `s.ProxyNeedsPush()` (which is `DefaultProxyNeedsPush()` by default, line 191 of discovery.go) chains to `ConfigAffectsProxy()`, which calls `checkProxyDependencies()`, which calls `DependsOnConfig()`.

---

## Affected Components

1. **`pilot/pkg/model/destination_rule.go`**
   - `mergeDestinationRule()` function
   - Performs metadata-lossy merging of multiple DRs for the same host

2. **`pilot/pkg/model/push_context.go`**
   - `consolidatedDestRules` struct
   - `destinationRuleIndex` struct
   - `SetDestinationRules()` function
   - `destinationRule()` function
   - `getExportedDestinationRuleFromNamespace()` function
   - Maintains and retrieves merged DR configs without tracking all contributing sources

3. **`pilot/pkg/model/sidecar.go`**
   - `DefaultSidecarScopeForNamespace()` function (lines 173-251)
   - `ConvertToSidecarScope()` function (lines 254-431)
   - `AddConfigDependencies()` function (lines 544-555)
   - `DependsOnConfig()` function (lines 521-540)
   - Builds incomplete dependency maps from merged configs

4. **`pilot/pkg/xds/proxy_dependencies.go`**
   - `ConfigAffectsProxy()` function
   - `checkProxyDependencies()` function
   - `DefaultProxyNeedsPush()` function
   - Filters pushes based on incomplete dependency information

5. **`pilot/pkg/xds/ads.go` and `pilot/pkg/xds/delta.go`**
   - PushProcess() handlers that call `ProxyNeedsPush()`
   - Skip pushes when dependency filter returns false

---

## Causal Chain

1. **Symptom:** Operator updates DR-2 (reviews-subsets); Envoy sidecar continues serving stale configuration; `/debug/config_dump` shows old subsets/policies.

2. **First Hop:** `mergeDestinationRule()` in `destination_rule.go` (lines 41-104) merges DR-1 and DR-2 into a single config object with DR-1's metadata (name: "reviews-traffic-policy", namespace: "default"), discarding DR-2's identity.

3. **Second Hop:** `destinationRule()` in `push_context.go` (line 1010 and similar) returns the merged config from `consolidatedDestRules.destRules[hostname]`, containing only ONE config object (the first DR's metadata with merged content).

4. **Third Hop:** `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` in `sidecar.go` (lines 209-227 and 408-418) iterate over this merged-config list and call `AddConfigDependencies()` with only the first DR's ConfigKey: `{Kind: DestinationRule, Name: "reviews-traffic-policy", Namespace: "default"}`.

5. **Fourth Hop:** When DR-2 is updated in the Kubernetes API server, the control plane emits a push event with `ConfigKey{..., Name: "reviews-subsets", ...}` in `req.ConfigsUpdated`.

6. **Fifth Hop:** `ConfigAffectsProxy()` in `proxy_dependencies.go` (line 52) calls `checkProxyDependencies()`, which calls `proxy.SidecarScope.DependsOnConfig(ConfigKey{..., Name: "reviews-subsets", ...})`.

7. **Root Cause Reached:** `DependsOnConfig()` in `sidecar.go` (line 538) computes `ConfigKey{..., Name: "reviews-subsets", ...}.HashCode()` and searches `sc.configDependencies`. The map only contains the hash of `ConfigKey{..., Name: "reviews-traffic-policy", ...}`. The lookup returns `false`.

8. **Result:** `ConfigAffectsProxy()` returns `false` → `DefaultProxyNeedsPush()` returns `false` → `PushProcess()` in `ads.go` (line 688) skips the push → Envoy sidecar never receives the updated DR-2 configuration.

---

## Recommendation

### Fix Strategy

The root cause must be addressed at the point where metadata is lost: **the merging phase**. There are two high-level approaches:

#### Option A: Preserve All Contributing DR Metadata (Recommended)

Modify `mergeDestinationRule()` to **retain all contributing DRs** in the `destRules` list with their original metadata intact. Instead of merging into a single config, keep both configs but establish a logical relationship:

1. **Change `consolidatedDestRules` data structure** to track both:
   - Individual DR metadata (name/namespace of each contributing DR)
   - Merged routing content (consolidated subsets, traffic policies)

2. **Modify `mergeDestinationRule()`** to:
   - Append both DRs to `p.destRules[resolvedHost]` instead of merging into one
   - Mark or annotate which configs are merged and with what others
   - Ensure subsets and traffic policies are properly deduplicated but attributed to their sources

3. **Update dependency registration** in `sidecar.go` to iterate over ALL contributing DRs, not just the merged config.

#### Option B: Map Merged DRs Back to Sources

Create a metadata map in `consolidatedDestRules` that tracks:
- Which DRs contributed to each merged config
- A reverse mapping from individual DR's ConfigKey to the merged config's position

Then, during dependency registration, iterate over both the merged configs AND their contributing sources.

#### Option C: Defer Merging Until After Dependency Registration

Move the merging phase to after SidecarScope initialization, so dependency registration happens on individual, unmerged DRs.

### Diagnostic Steps

To verify the issue in a live cluster:

1. **Check the sidecar scope dependencies:**
   ```bash
   # On Istiod, add debug logging to SidecarScope.AddConfigDependencies()
   # Check which DR ConfigKeys are registered
   ```

2. **Monitor config updates:**
   ```bash
   # Watch Pilot logs for:
   # - Config update events with updated DR name/namespace
   # - Push filtering decisions showing "DependsOnConfig returned false"
   ```

3. **Trace the merge logic:**
   ```bash
   # Add debug logging to mergeDestinationRule() to confirm:
   # - Both DRs are processed
   # - Only the first DR's metadata survives
   # - The second DR is never appended
   ```

4. **Inspect the PushContext:**
   ```bash
   # Dump ps.destinationRuleIndex.namespaceLocal to verify:
   # - Only one config per merged hostname
   # - The config's Name/Namespace field matches only the first DR
   ```

---

## Related Code References

- **Config update event generation:** `pilot/pkg/xds/discovery.go` - `ConfigUpdate()` (line 389), `initPushContext()` (line 563)
- **Push filtering entry point:** `pilot/pkg/xds/ads.go` - `PushProcess()` (line 683)
- **Hash-based dependency lookup:** `pilot/pkg/model/config.go` - `ConfigKey.HashCode()` (line 60)
- **SidecarScope initialization:** `pilot/pkg/model/sidecar.go` - `DefaultSidecarScopeForNamespace()` (line 173), `ConvertToSidecarScope()` (line 254)

