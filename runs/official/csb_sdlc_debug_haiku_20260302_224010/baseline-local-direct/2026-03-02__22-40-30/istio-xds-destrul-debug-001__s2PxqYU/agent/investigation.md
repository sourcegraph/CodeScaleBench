# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update in Istio

## Summary

When multiple DestinationRules target the same host (e.g., one defining subsets, another defining traffic policy), updating one of them fails to trigger an xDS push to affected Envoy sidecars. The root cause is that Istio's DestinationRule merging logic consolidates multiple DRs into a single merged configuration, but only the first DR's name/namespace metadata survives in the consolidated structure. When the second DR is updated, its ConfigKey is not registered as a dependency, so the xDS push filtering logic correctly determines the proxy doesn't depend on "what it thinks" is the changed resource.

## Root Cause

The root cause spans multiple components in a causal chain:

1. **Primary Issue (destination_rule.go):** The `mergeDestinationRule()` function at line 38-109 modifies the first DestinationRule in-place when merging with subsequent DRs for the same host. The merged DR retains only the first DR's `config.Config` metadata (Name/Namespace) while subsets and traffic policies from all DRs are combined. Contributing DRs' metadata is permanently lost.

2. **Secondary Issue (sidecar.go):** When building SidecarScope dependencies at lines 219-227, the code iterates `out.destinationRules` and registers `ConfigKey{Kind: gvk.DestinationRule, Name: dr.Name, Namespace: dr.Namespace}` for each DR. However, since `destinationRules` contains only the merged DR (with the first DR's name/namespace), only that single ConfigKey is registered, not the original contributing DRs' ConfigKeys.

3. **Push Filtering Gap (proxy_dependencies.go):** When a config update event occurs at line 32-58 (`ConfigAffectsProxy`), the system checks `checkProxyDependencies()` which calls `SidecarScope.DependsOnConfig()` at line 64. The `DependsOnConfig()` method (sidecar.go:523-539) performs a hash lookup in `configDependencies` using `config.HashCode()`. If the updated DR is the one that was merged away, its ConfigKey won't be found, returning false and causing the push to be incorrectly skipped.

## Evidence

### 1. DestinationRule Merging (destination_rule.go:38-109)

**File:** `pilot/pkg/model/destination_rule.go`

The function signature indicates it merges DRs for a given host:
```go
func (ps *PushContext) mergeDestinationRule(p *consolidatedDestRules,
    destRuleConfig config.Config, exportToMap map[visibility.Instance]bool)
```

**Critical merge behavior (lines 41-104):**
```go
if mdrList, exists := p.destRules[resolvedHost]; exists {
    for i, mdr := range mdrList {
        // ... validation logic ...

        // Deep copy existing DR at index i
        copied := mdr.DeepCopy()
        p.destRules[resolvedHost][i] = &copied
        mergedRule := copied.Spec.(*networking.DestinationRule)

        // Merge subsets from new rule into existing rule
        for _, subset := range rule.Subsets {
            // ... add subset logic ...
            mergedRule.Subsets = append(mergedRule.Subsets, subset)
        }

        // Merge traffic policy if not present
        if mergedRule.TrafficPolicy == nil && rule.TrafficPolicy != nil {
            mergedRule.TrafficPolicy = rule.TrafficPolicy
        }
    }
    // Only add as new entry if workload selectors don't match
    if addRuleToProcessedDestRules {
        p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
    }
    return  // <<< Returns here, doesn't add contributing DR separately
}
// First time seeing this host
p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
```

**Key insight:** The merged DR keeps its original metadata (`Name`, `Namespace` from `destRuleConfig`), while the incoming DR's metadata is permanently discarded. The first DR processed becomes the "primary" entry with merged content from all subsequent DRs.

### 2. Dependency Registration (sidecar.go:209-227)

**File:** `pilot/pkg/model/sidecar.go`

In `DefaultSidecarScopeForNamespace()`:
```go
// Line 209-211: Get merged DRs from PushContext
if dr := ps.destinationRule(configNamespace, s); dr != nil {
    out.destinationRules[s.Hostname] = dr  // dr is []*config.Config (slice)
}

// Lines 219-227: Register dependencies for EACH DR
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,              // <<< Uses merged DR's name
            Namespace: dr.Namespace,          // <<< Uses merged DR's namespace
        })
    }
}
```

The `ps.destinationRule()` call (line 209) returns `[]*config.Config` from the merged `destRules` index in `push_context.go:990-1066`. Since the index was built by `mergeDestinationRule()`, it contains the consolidated DRs with only the first DR's metadata.

The loop at lines 219-227 registers **only one ConfigKey per hostname**, corresponding to the merged DR's metadata.

### 3. Push Filtering with DependsOnConfig (proxy_dependencies.go:32-74)

**File:** `pilot/pkg/xds/proxy_dependencies.go`

```go
func ConfigAffectsProxy(req *model.PushRequest, proxy *model.Proxy) bool {
    // req.ConfigsUpdated contains ConfigKey{Kind, Name, Namespace} for changed resources

    for config := range req.ConfigsUpdated {
        // ... type-specific filtering ...

        if affected && checkProxyDependencies(proxy, config) {
            return true  // Push needed
        }
    }
    return false  // No push
}

func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        if proxy.SidecarScope.DependsOnConfig(config) {
            return true
        } else if proxy.PrevSidecarScope != nil &&
                  proxy.PrevSidecarScope.DependsOnConfig(config) {
            return true
        }
    }
    return false  // <<< Returns false if config not in dependencies
}
```

**File:** `pilot/pkg/model/sidecar.go` (DependsOnConfig method)

```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    // ... simplified logging logic ...
    _, exists := sc.configDependencies[config.HashCode()]
    return exists  // False if ConfigKey not registered
}

func (sc *SidecarScope) AddConfigDependencies(dependencies ...ConfigKey) {
    // ... logic ...
    sc.configDependencies[config.HashCode()] = struct{}{}
}
```

**File:** `pilot/pkg/model/config.go` (ConfigKey.HashCode)

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
    return binary.BigEndian.Uint64(hash.Sum(tmp[:0]))
}
```

**The Gap:** When `reviews-subsets` DR is updated, a ConfigKey is created with:
- `Kind: gvk.DestinationRule`
- `Name: "reviews-subsets"`
- `Namespace: "default"`

But the proxy's `configDependencies` only contains the hash for:
- `Name: "reviews-traffic-policy"` (the first DR that was merged)
- `Namespace: "default"`

The hash lookup fails, `DependsOnConfig()` returns `false`, and the push is skipped.

### 4. Route/Cluster Configuration Dependencies (route_cache.go, cluster_builder.go)

**File:** `pilot/pkg/networking/core/v1alpha3/route/route_cache.go`

The route cache also builds ConfigKey dependencies:
```go
configs = append(configs, model.ConfigKey{
    Kind:      gvk.DestinationRule,
    Name:      dr.Name,              // <<< Merged DR's name
    Namespace: dr.Namespace,          // <<< Merged DR's namespace
})
```

**File:** `pilot/pkg/networking/core/v1alpha3/cluster_builder.go`

```go
func (t clusterCache) DependentConfigs() []model.ConfigKey {
    configs := []model.ConfigKey{}
    if t.destinationRule != nil {
        configs = append(configs, model.ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      t.destinationRule.Name,       // <<< Merged DR's name
            Namespace: t.destinationRule.Namespace,  // <<< Merged DR's namespace
        })
    }
    return configs
}
```

These components depend on the DR metadata from `SidecarScope.destinationRules`, which is already contaminated with only the first DR's metadata.

### 5. PushContext.destinationRule() and Merging Pipeline (push_context.go:990-1066, 1668-1768)

**File:** `pilot/pkg/model/push_context.go`

The `SetDestinationRules()` function at line 1672 is called during PushContext initialization:

```go
func (ps *PushContext) SetDestinationRules(configs []config.Config) {
    // Lines 1675-1676: Sort by creation time
    sortConfigByCreationTime(configs)

    // Lines 1681-1743: For each namespace+host, call mergeDestinationRule
    for i := range configs {
        rule := configs[i].Spec.(*networking.DestinationRule)
        rule.Host = string(ResolveShortnameToFQDN(rule.Host, configs[i].Meta))
        exportToMap := make(map[visibility.Instance]bool)

        // ... exportTo logic ...

        // Lines 1716, 1739, 1742: Merge each DR into consolidated structure
        ps.mergeDestinationRule(namespaceLocalDestRules[configs[i].Namespace],
            configs[i], exportToMap)
    }

    // Lines 1764-1767: Store in index
    ps.destinationRuleIndex.namespaceLocal = namespaceLocalDestRules
    ps.destinationRuleIndex.exportedByNamespace = exportedDestRulesByNamespace
    ps.destinationRuleIndex.rootNamespaceLocal = rootNamespaceLocalDestRules
}
```

The `destinationRule()` method (line 990-1066) retrieves merged DRs from these indexes:
```go
func (ps *PushContext) destinationRule(proxyNameSpace string, service *Service) []*config.Config {
    // Returns []*config.Config from the merged index
    // Each entry is the consolidated DR with only first DR's metadata
}
```

This obscures the fact that multiple DRs contributed to the merged configuration.

## Affected Components

1. **pilot/pkg/model/destination_rule.go** - `mergeDestinationRule()` function performs in-place merge
2. **pilot/pkg/model/push_context.go** - `SetDestinationRules()` and `destinationRule()` manage the merged index
3. **pilot/pkg/model/sidecar.go** - `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` register dependencies based on merged DRs
4. **pilot/pkg/xds/proxy_dependencies.go** - `ConfigAffectsProxy()` and `checkProxyDependencies()` filter pushes based on incomplete dependency information
5. **pilot/pkg/networking/core/v1alpha3/cluster_builder.go** - `DependentConfigs()` uses merged DR metadata
6. **pilot/pkg/networking/core/v1alpha3/route/route_cache.go** - Routes also depend on merged DR metadata
7. **pilot/pkg/config/schema/gvk/** - The GroupVersionKind definitions used throughout

## Causal Chain

1. **Symptom:** Envoy sidecar continues serving stale cluster and route configuration after a DestinationRule is updated.

2. **Hop 1 - Configuration Collection:** When PushContext is initialized, `SetDestinationRules()` receives all DestinationRule configs from the API server.

3. **Hop 2 - Merging Loss of Identity:** For multiple DRs targeting the same host (e.g., `reviews.default.svc.cluster.local`), `mergeDestinationRule()` is called. The function merges subsets and traffic policies from all DRs into the **first DR**, modifying it in-place and discarding the subsequent DRs' metadata entirely.

4. **Hop 3 - Incomplete Dependency Registration:** When building SidecarScope for a proxy, the code iterates the merged `destinationRules` index and calls `AddConfigDependencies()` with each DR's name/namespace. Since only the merged DR exists in the index (with the first original DR's metadata), only that one ConfigKey is registered in `configDependencies`.

5. **Hop 4 - Update Event Triggers Wrong ConfigKey:** An operator updates the second DestinationRule (e.g., `reviews-subsets`). The config store generates a ConfigKey with:
   - `Name: "reviews-subsets"`
   - `Namespace: "default"`
   - This ConfigKey is added to the PushRequest's `ConfigsUpdated` set.

6. **Hop 5 - Push Filter Finds No Match:** When determining if the proxy needs a push, `ConfigAffectsProxy()` calls `checkProxyDependencies()`, which calls `proxy.SidecarScope.DependsOnConfig()` with the `reviews-subsets` ConfigKey.

7. **Hop 6 - Hash Lookup Fails:** The `DependsOnConfig()` method computes the ConfigKey's hash and looks it up in the proxy's `configDependencies` map. The map only contains the hash for `reviews-traffic-policy` (the first DR), not `reviews-subsets`. The lookup fails.

8. **Root Cause Effect:** `DependsOnConfig()` returns `false`, indicating the proxy does NOT depend on the updated config. `ConfigAffectsProxy()` returns `false`, and the xDS push to this proxy is **skipped**.

9. **Final Symptom:** The Envoy sidecar never receives the updated cluster/route configuration. The `/debug/config_dump` endpoint shows the old configuration. Only restarting the pod (which rebuilds the SidecarScope with a new PushContext) picks up the change.

## Recommendation

### Fix Strategy

The fix requires tracking **all contributing DRs** (not just the merged one) when consolidating multiple DRs for the same host:

1. **Preserve Contributing DR Metadata:** Modify `mergeDestinationRule()` to return or track a list of all DestinationRules that contributed to the merged configuration, not just the merged spec.

2. **Register All Contributing DRs as Dependencies:** Update `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` to register ConfigKeys for **all** contributing DRs, not just the merged DR.

3. **Option A - Modify consolidatedDestRules:**
   - Change the structure to store not just the merged `config.Config`, but also a slice of contributing DR ConfigKeys:
   ```go
   type consolidatedDestRules struct {
       destRules map[host.Name][]*config.Config
       contributingDRs map[host.Name][]ConfigKey  // <<< NEW
   }
   ```
   - Update `mergeDestinationRule()` to populate `contributingDRs` instead of discarding them.
   - When registering dependencies in `sidecar.go`, iterate both the merged DR and the contributing DR list.

4. **Option B - Create a Wrapper Type:**
   - Create a new wrapper type that pairs a merged `config.Config` with the list of contributing DRs:
   ```go
   type MergedDestinationRule struct {
       Config          *config.Config
       ContributingDRs []ConfigKey
   }
   ```
   - Update all index structures to use this wrapper type instead of `*config.Config`.

### Diagnostic Steps

To verify the root cause in an affected cluster:

1. **Check SidecarScope Dependencies:**
   ```bash
   # Enable debug logging in Pilot for sidecar scope creation
   # The logs should show ConfigKey dependencies being registered
   ```

2. **Verify Configuration Index:**
   ```bash
   # Inspect Pilot's internal state to see if destinationRules index
   # contains only one DR per hostname when multiple DRs exist
   ```

3. **Test Incremental Push:**
   - Create two DRs for the same host
   - Update the second DR
   - Check Pilot logs to see if `ConfigAffectsProxy()` returns false for proxies in the affected namespace

4. **Trace ConfigKey Hash:**
   - When a DR is updated, log the ConfigKey hash generated
   - Cross-reference with proxy's `configDependencies` map to confirm mismatch

### Prevention

- Add validation tests in `TestDestinationRuleConfiguration` to verify that all contributing DRs are properly tracked when multiple DRs target the same host.
- Add a metric to track "dropped DR metadata during merge" to detect this issue in production.
- Document the DestinationRule merging behavior and its limitations in the Istio API documentation.

## References

- `pilot/pkg/model/destination_rule.go:38-109` - Core merge logic
- `pilot/pkg/model/sidecar.go:219-227` - Dependency registration loop
- `pilot/pkg/model/push_context.go:1672-1768` - SetDestinationRules consolidation
- `pilot/pkg/xds/proxy_dependencies.go:32-74` - Push filtering decision
- `pilot/pkg/model/sidecar.go:523-539` - DependsOnConfig hash lookup
- `pilot/pkg/model/config.go:54-74` - ConfigKey definition and hashing
