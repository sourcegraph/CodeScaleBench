# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update

## Summary

When multiple DestinationRules target the same host, updating one of them fails to trigger an xDS push to Envoy sidecars because only one DR's metadata is retained during merging, causing the other DR's ConfigKey to never be registered in the proxy's config dependencies, leading to change detection failure.

## Root Cause

The root cause spans three interconnected systems:

1. **DestinationRule Merging Loss of Identity** (`pilot/pkg/model/destination_rule.go:38-109`)
2. **Incomplete Config Dependency Registration** (`pilot/pkg/model/sidecar.go:219-227, 410-416`)
3. **xDS Push Filter Using Missing Dependencies** (`pilot/pkg/xds/proxy_dependencies.go:52-74`)

## Evidence

### 1. DestinationRule Merging Loses Metadata Identity

**File:** `pilot/pkg/model/destination_rule.go:38-109`

The `mergeDestinationRule()` function merges multiple DRs for the same FQDN host into a single consolidated rule:

```go
func (ps *PushContext) mergeDestinationRule(p *consolidatedDestRules, destRuleConfig config.Config, exportToMap map[visibility.Instance]bool) {
    rule := destRuleConfig.Spec.(*networking.DestinationRule)
    resolvedHost := ResolveShortnameToFQDN(rule.Host, destRuleConfig.Meta)

    if mdrList, exists := p.destRules[resolvedHost]; exists {
        // ... matching logic ...
        for i, mdr := range mdrList {
            // Line 65-66: Deep copy and update existing rule in place
            copied := mdr.DeepCopy()
            p.destRules[resolvedHost][i] = &copied
            mergedRule := copied.Spec.(*networking.DestinationRule)

            // Lines 77-87: Merge subsets from new rule into existing rule
            for _, subset := range rule.Subsets {
                // append subsets to existing rule
                mergedRule.Subsets = append(mergedRule.Subsets, subset)
            }

            // Lines 91-93: Merge traffic policy if not present
            if mergedRule.TrafficPolicy == nil && rule.TrafficPolicy != nil {
                mergedRule.TrafficPolicy = rule.TrafficPolicy
            }
        }
        if addRuleToProcessedDestRules {
            // New rule is added to list
            p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
        }
        return
    }

    // First rule is simply added
    p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
}
```

**Critical Issue:** When two DRs are merged:
- The first DR's config metadata (Name="reviews-traffic-policy", Namespace="default") is preserved
- The second DR's metadata (Name="reviews-subsets", Namespace="default") is lost—only its Spec (subsets, traffic policy) is merged into the first DR's config
- `p.destRules[resolvedHost]` contains only ONE config.Config element after merging, with the first DR's metadata

### 2. Config Dependency Registration Only Tracks Surviving DR

**File:** `pilot/pkg/model/sidecar.go:219-227` (in `DefaultSidecarScopeForNamespace()`)

```go
// Lines 219-227
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,                    // Only the FIRST DR's name survives here
            Namespace: dr.Namespace,
        })
    }
}
```

**Critical Issue:**
- `out.destinationRules` is populated from `ps.destinationRule(configNamespace, s)` (line 209)
- This method returns the merged destination rules from `consolidatedDestRules`
- Since only one DR's metadata survives the merge, only ONE ConfigKey is registered
- When a new SidecarScope is created (line 254, `ConvertToSidecarScope()`), the same issue occurs at lines 410-416

### 3. config.Config Metadata Structure

**File:** `pilot/pkg/model/push_context.go:251-256`

```go
type consolidatedDestRules struct {
    // Map of dest rule host to the list of namespaces to which this destination rule has been exported to
    exportTo map[host.Name]map[visibility.Instance]bool
    // Map of dest rule host and the merged destination rules for that host
    destRules map[host.Name][]*config.Config  // Only ONE config.Config survives per host!
}
```

### 4. xDS Push Filter Uses Missing Dependencies

**File:** `pilot/pkg/xds/proxy_dependencies.go:52-74`

```go
func ConfigAffectsProxy(req *model.PushRequest, proxy *model.Proxy) bool {
    for config := range req.ConfigsUpdated {
        // ... type checking ...
        if affected && checkProxyDependencies(proxy, config) {
            return true
        }
    }
    return false
}

func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        // LINE 64: Calls DependsOnConfig with the updated DR's ConfigKey
        if proxy.SidecarScope.DependsOnConfig(config) {
            return true
        }
        // ...
    }
    return false
}
```

**File:** `pilot/pkg/model/sidecar.go:523-540` (in `DependsOnConfig()`)

```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    if sc == nil {
        return true
    }

    if _, f := clusterScopedConfigTypes[config.Kind]; f {
        return config.Namespace == sc.RootNamespace || config.Namespace == sc.Namespace
    }

    if _, f := sidecarScopeKnownConfigTypes[config.Kind]; !f {
        return true
    }

    // LINE 538: Check if the ConfigKey's hash is in the registered dependencies
    _, exists := sc.configDependencies[config.HashCode()]
    return exists
}
```

**Critical Issue:** When a DestinationRule update event occurs:
1. The event contains the ConfigKey for the updated DR: `{Kind: DestinationRule, Name: "reviews-subsets", Namespace: "default"}`
2. This ConfigKey's hash is computed (lines 60-74 in `pilot/pkg/model/config.go`)
3. `DependsOnConfig()` checks if this hash exists in `configDependencies`
4. Since only "reviews-traffic-policy" was registered, the hash for "reviews-subsets" is NOT in the map
5. `DependsOnConfig()` returns `false`
6. The xDS push is SKIPPED

### 5. Hash Computation

**File:** `pilot/pkg/model/config.go:60-74`

```go
func (key ConfigKey) HashCode() uint64 {
    hash := md5.New()
    for _, v := range []string{
        key.Name,
        key.Namespace,
        key.Kind.Kind,
        key.Kind.Group,
        key.Kind.Version,
    } {
        hash.Write([]byte(v))
    }
    var tmp [md5.Size]byte
    sum := hash.Sum(tmp[:0])
    return binary.BigEndian.Uint64(sum)
}
```

The hash includes the DR's Name, so:
- "reviews-traffic-policy" → hash H1 (registered)
- "reviews-subsets" → hash H2 (NOT registered)

When "reviews-subsets" is updated, its ConfigKey generates hash H2, which is not in `configDependencies`, so the push is rejected.

## Affected Components

1. **`pilot/pkg/model/destination_rule.go`**
   - `mergeDestinationRule()` - loses DR identity during merge

2. **`pilot/pkg/model/sidecar.go`**
   - `DefaultSidecarScopeForNamespace()` - only registers one DR's ConfigKey
   - `ConvertToSidecarScope()` - only registers one DR's ConfigKey
   - `AddConfigDependencies()` - called with incomplete list of DRs
   - `DependsOnConfig()` - correctly checks dependencies but only has one DR's key

3. **`pilot/pkg/xds/proxy_dependencies.go`**
   - `ConfigAffectsProxy()` - correctly filters based on dependencies
   - `checkProxyDependencies()` - correctly checks if proxy depends on config

4. **`pilot/pkg/model/push_context.go`**
   - `destinationRule()` - returns merged DRs with only one metadata
   - `consolidatedDestRules` - stores only one config.Config per host
   - `destinationRuleIndex` - stores consolidated rules without tracking all contributors

5. **`pilot/pkg/model/config.go`**
   - `ConfigKey.HashCode()` - correctly hashes individual keys, but only some keys are registered

## Causal Chain

1. **Symptom**: Operator updates `reviews-subsets` DR → Envoy sidecar receives no xDS update
2. **Event Propagation**: Istio control plane detects the DestinationRule update event
3. **Push Filtering (FAILURE POINT)**: `ConfigAffectsProxy()` is called with ConfigKey{Name: "reviews-subsets", ...}
4. **Dependency Check**: `DependsOnConfig()` is called, which checks if hash of "reviews-subsets" is in `configDependencies`
5. **Missing Dependency**: The hash for "reviews-subsets" is NOT found (only "reviews-traffic-policy" was registered)
6. **Push Rejected**: `ConfigAffectsProxy()` returns `false`, push is skipped
7. **Root Cause - Incomplete Registration**: Only "reviews-traffic-policy"'s ConfigKey was added to dependencies because:
   - `DefaultSidecarScopeForNamespace()` or `ConvertToSidecarScope()` called `ps.destinationRule()` which returned the merged DR
   - The merged DR list contained only ONE config.Config (with "reviews-traffic-policy" metadata)
   - Only one ConfigKey was registered via `AddConfigDependencies()`
8. **Root Cause - Merging**: Only one DR's metadata survived the merge because:
   - When `mergeDestinationRule()` processed the second DR, it merged its Spec into the first DR's config
   - It never added a second config.Config to the `destRules[host]` list (unless workload selectors required it)
   - The second DR's metadata was discarded

## Diagnostic Steps

To verify this root cause in a live cluster:

1. **Inspect the merged DR list:**
   ```bash
   kubectl port-forward -n istio-system <istiod-pod> 8080:8080
   curl http://localhost:8080/debug/configz | jq '.destinationRules'
   ```
   Check that only ONE DR's Name/Namespace appears per host, despite multiple DRs being defined.

2. **Inspect the SidecarScope dependencies:**
   ```bash
   curl http://localhost:8080/debug/configz | jq '.sidecarScopes[].configDependencies'
   ```
   Verify that only one DestinationRule ConfigKey is registered.

3. **Trace the update event:**
   Enable debug logging in Istiod and watch for:
   - The DestinationRule update event being received
   - `ConfigAffectsProxy()` being called with the updated DR's ConfigKey
   - `DependsOnConfig()` returning `false` (no push triggered)

4. **Compare with a single DR:**
   Define only one DestinationRule per host and verify that updates DO trigger xDS pushes.

## Recommendation

**Fix Strategy:**

The solution requires registering ALL contributing DestinationRules in the SidecarScope dependencies, not just the one whose metadata survives the merge.

### Option 1: Track Contributing DRs During Merge (Preferred)
- Modify `consolidatedDestRules` to maintain a list of contributing DR ConfigKeys alongside the merged config
- When creating SidecarScope dependencies, iterate over ALL contributing DRs, not just the merged result
- **Impact**: Preserves the current merging behavior while fixing dependency tracking

### Option 2: Store All DRs Without Merging Metadata
- Modify `consolidatedDestRules.destRules` to keep multiple config.Config entries (one per source DR)
- Only merge the Spec (subsets, traffic policy) into the first DR's config
- Preserve each original DR's metadata separately
- **Impact**: Requires changes to how merged DRs are retrieved by consumers

### Option 3: Separate Merging from Dependency Tracking
- Create a mapping from merged DR ConfigKey to all contributing DR ConfigKeys
- When checking dependencies, include both direct matches and merged-into matches
- **Impact**: Requires cross-referencing in the dependency lookup path

**Minimal Necessary Fix:**
1. In `consolidatedDestRules`, add a field: `contributingDRs map[host.Name][]ConfigKey` to track all contributing DR identities
2. In `mergeDestinationRule()`, append each source DR's ConfigKey to the contributing list
3. In `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()`, iterate over contributing DRs instead of just the merged result
4. Update `DependsOnConfig()` or the push filter to recognize that a proxy depends on a DR if it depends on any merged variant of that DR

This ensures that when ANY contributing DR is updated, the proxy receives the push.
