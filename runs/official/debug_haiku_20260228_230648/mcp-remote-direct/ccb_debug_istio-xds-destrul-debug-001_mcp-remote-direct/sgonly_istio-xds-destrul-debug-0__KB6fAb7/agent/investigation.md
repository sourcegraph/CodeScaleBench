# Investigation Report

## Summary

When multiple DestinationRules target the same host, Istio merges them into a single consolidated configuration. However, only the first DestinationRule's metadata (name/namespace) is retained in the merged structure, causing all other contributing DRs to lose their identity. Later, when SidecarScope registers config dependencies for xDS push filtering, it only registers the surviving DR's metadata. This causes updates to non-surviving DRs to be invisible to the push filter, resulting in stale Envoy configuration.

## Root Cause

**The root cause is a two-part failure in metadata preservation during DestinationRule merging:**

1. **Metadata loss during merging** (`pilot/pkg/model/destination_rule.go:38-109`): The `mergeDestinationRule()` function consolidates multiple DRs for the same host into a single `config.Config` object in the `consolidatedDestRules` structure. When a second DR is merged into an existing one, only the first DR's `config.Meta` (Name/Namespace) is preserved. The second DR's metadata is discarded.

2. **Incomplete dependency registration** (`pilot/pkg/model/sidecar.go:219-227, 410-416`): When SidecarScope builds its config dependencies, it iterates over the merged destination rules. Since the merged structure only contains one `config.Config` per hostname (due to step 1), only that one DR's ConfigKey (Kind, Name, Namespace) gets registered in `configDependencies`.

3. **Push filter bypass** (`pilot/pkg/xds/proxy_dependencies.go:60-74`): When a config update event occurs, the xDS push filter calls `SidecarScope.DependsOnConfig()` to check if the proxy depends on the updated config. The check uses a hash computed from the ConfigKey's Name, Namespace, and Kind. If the updated DR was the one whose metadata was lost during merging, its hash won't exist in `configDependencies`, causing `DependsOnConfig()` to return false and the push to be incorrectly skipped.

## Evidence

### File: `pilot/pkg/model/destination_rule.go`

**Function: `mergeDestinationRule()` (lines 38-109)**
- Line 41: `if mdrList, exists := p.destRules[resolvedHost]; exists {`
- Line 66: `p.destRules[resolvedHost][i] = &copied` — Updates the existing DR in-place with merged content
- Lines 77-87: Subsets from new DR are appended to existing DR's subsets
- Lines 91-92: Traffic policy from new DR is merged into existing DR if not present
- **Missing**: No code to preserve the second DR's metadata; it's discarded after merging

### File: `pilot/pkg/model/sidecar.go`

**Function: `DefaultSidecarScopeForNamespace()` (lines 219-227)**
```go
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,              // Only the surviving DR's name
            Namespace: dr.Namespace,          // Only the surviving DR's namespace
        })
    }
}
```

**Function: `ConvertToSidecarScope()` (lines 410-416)**
```go
for _, dr := range drList {
    out.AddConfigDependencies(ConfigKey{
        Kind:      gvk.DestinationRule,
        Name:      dr.Name,                  // Only the surviving DR's name
        Namespace: dr.Namespace,              // Only the surviving DR's namespace
    })
}
```

Both functions only register dependencies for DRs that appear in the final merged list.

### File: `pilot/pkg/model/sidecar.go`

**Function: `DependsOnConfig()` (lines 523-540)**
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

    _, exists := sc.configDependencies[config.HashCode()]  // Line 538: Lookup in dependencies
    return exists                                            // Line 539: Returns false if not found
}
```

If the ConfigKey for an updated DR is not in `configDependencies` (because it was merged and lost its identity), this function returns false.

### File: `pilot/pkg/xds/proxy_dependencies.go`

**Function: `checkProxyDependencies()` (lines 60-74)**
```go
func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        if proxy.SidecarScope.DependsOnConfig(config) {
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

This calls `DependsOnConfig()` which returns false for merged-away DRs, causing the entire `ConfigAffectsProxy()` check to fail.

**Function: `ConfigAffectsProxy()` (lines 32-58)**
```go
func ConfigAffectsProxy(req *model.PushRequest, proxy *model.Proxy) bool {
    if len(req.ConfigsUpdated) == 0 {
        return true
    }

    for config := range req.ConfigsUpdated {
        affected := true

        if kindAffectedTypes, f := configKindAffectedProxyTypes[config.Kind]; f {
            affected = false
            for _, t := range kindAffectedTypes {
                if t == proxy.Type {
                    affected = true
                    break
                }
            }
        }

        if affected && checkProxyDependencies(proxy, config) {  // Line 52: Calls checkProxyDependencies
            return true
        }
    }

    return false
}
```

If `checkProxyDependencies()` returns false, the proxy won't be pushed.

### File: `pilot/pkg/model/push_context.go`

**Function: `SetDestinationRules()` (lines 1672-1768)**
- Lines 1716 and 1739: Calls `ps.mergeDestinationRule()` for each DR
- This populates the `destinationRuleIndex` with only the surviving merged DRs
- Example (lines 1764-1766):
```go
ps.destinationRuleIndex.namespaceLocal = namespaceLocalDestRules      // Contains merged DRs only
ps.destinationRuleIndex.exportedByNamespace = exportedDestRulesByNamespace
ps.destinationRuleIndex.rootNamespaceLocal = rootNamespaceLocalDestRules
```

**Function: `destinationRule()` (lines 990-1066)**
- This function retrieves merged destination rules from the index
- Returns `[]*config.Config` but the list only contains the surviving merged DRs
- No way to trace back to the original contributing DRs

### File: `pilot/pkg/model/config.go`

**Type: `ConfigKey` (lines 54-58)**
```go
type ConfigKey struct {
    Kind      config.GroupVersionKind
    Name      string
    Namespace string
}
```

**Function: `HashCode()` (lines 60-74)**
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
    // ...
    return binary.BigEndian.Uint64(sum)
}
```

The hash is computed from Name and Namespace. If these are not registered in `configDependencies`, the hash won't match during xDS push filtering.

## Affected Components

1. **`pilot/pkg/model/destination_rule.go`** — DestinationRule merging logic
2. **`pilot/pkg/model/sidecar.go`** — SidecarScope and config dependency tracking
3. **`pilot/pkg/model/push_context.go`** — PushContext and DestinationRule indexing
4. **`pilot/pkg/model/config.go`** — ConfigKey and hashing
5. **`pilot/pkg/xds/proxy_dependencies.go`** — xDS push filtering
6. **`pilot/pkg/networking/core/`** — CDS/RDS generators that consume merged DRs

## Causal Chain

1. **Operator creates two DestinationRules for the same host** — `reviews-subsets` and `reviews-traffic-policy` both target `reviews.default.svc.cluster.local`

2. **Pilot's SetDestinationRules() processes DRs in order** (`pilot/pkg/model/push_context.go:1672`)
   - First DR (`reviews-traffic-policy`) is added to the consolidated structure
   - Second DR (`reviews-subsets`) is merged into the first

3. **mergeDestinationRule() loses the second DR's metadata** (`pilot/pkg/model/destination_rule.go:38-109`)
   - The merged result has only the first DR's Name/Namespace
   - The second DR's Name/Namespace is discarded
   - The merged structure contains combined subsets and traffic policies but only one metadata entry

4. **SidecarScope registers dependencies based on merged DRs** (`pilot/pkg/model/sidecar.go:219-227, 410-416`)
   - When iterating over `out.destinationRules`, only one DR per hostname exists (the merged one)
   - Only the surviving DR's ConfigKey is added to `configDependencies`
   - The other DR's ConfigKey is never registered

5. **Operator updates `reviews-subsets`** in the Kubernetes API
   - Control plane detects the update
   - A PushRequest is generated with ConfigKey for `reviews-subsets`

6. **xDS push filter evaluates whether to push to proxies** (`pilot/pkg/xds/proxy_dependencies.go:32-58`)
   - Calls `ConfigAffectsProxy()` for each proxy
   - For SidecarProxy, calls `checkProxyDependencies()` → `DependsOnConfig()`

7. **DependsOnConfig() fails to find the updated DR** (`pilot/pkg/model/sidecar.go:538`)
   - Tries to look up the hash of ConfigKey{Kind: DestinationRule, Name: "reviews-subsets", Namespace: "default"}
   - But only ConfigKey{Kind: DestinationRule, Name: "reviews-traffic-policy", Namespace: "default"} is registered
   - Hash lookup returns false, meaning "proxy doesn't depend on this config"

8. **ConfigAffectsProxy returns false** for the updated `reviews-subsets` DR
   - The proxy is excluded from the push

9. **Envoy sidecar never receives updated CDS/RDS config**
   - Old subset and cluster configuration persists
   - Only restarting the pod clears the stale config (forcing a new SidecarScope computation)

## Recommendation

**Fix Strategy:**

The root cause must be addressed at the point where metadata is lost — the `mergeDestinationRule()` function and subsequent dependency registration.

**Option 1: Preserve all contributing DRs' identities (Recommended)**
- Modify the consolidated structure to track **all contributing DRs**, not just the merged result
- When registering dependencies in SidecarScope, register **all contributing DRs**, not just the consolidated one
- This maintains full traceability and ensures any update to any contributing DR triggers a push

**Option 2: Create a synthetic "consolidated" DR ConfigKey**
- Create a virtual ConfigKey that represents the merged DestinationRule
- When any contributing DR is updated, translate that update to reference the consolidated ConfigKey
- Register only this synthetic key in configDependencies
- This is complex because it requires intercepting config update events

**Option 3: Re-index on every update**
- Instead of caching merged DRs, re-compute merging on every config change
- This is inefficient but ensures correctness

**Diagnostic Steps:**

To verify this is the issue:

1. **Check SidecarScope dependencies:**
   ```
   # Inspect a proxy's SidecarScope.configDependencies
   # Verify that BOTH "reviews-traffic-policy" and "reviews-subsets" are present
   # Expected: Only "reviews-traffic-policy" will be present (the bug)
   ```

2. **Monitor xDS updates:**
   ```
   # Update "reviews-subsets" DR and watch for CDS/RDS updates to affected proxies
   # Expected behavior: CDS/RDS updates pushed
   # Actual behavior: No updates pushed
   ```

3. **Trace the merge process:**
   ```
   # Add logging to mergeDestinationRule() to see when metadata is lost
   # Monitor what DRs end up in destinationRuleIndex after SetDestinationRules()
   # Expected: Both DRs listed; Actual: Only merged DR listed
   ```

4. **Verify the fix:**
   ```
   # After fix, both DRs should appear in SidecarScope.configDependencies
   # Both should trigger xDS pushes when updated
   ```

## Related Configuration Scenario

The issue manifests specifically when:
- Multiple DestinationRules exist for the same FQDN host
- At least one has subsets, and at least one has a top-level traffic policy
- These are merged into a single consolidated DR
- An update occurs to one of the merged DRs (not the one whose metadata survived)
- The updated DR happens to be the one whose metadata was lost during merging

This scenario is common in multi-team environments where:
- Team A defines traffic policies globally (created first)
- Team B defines subsets for the same service (created later, gets merged into Team A's DR)
- Team B updates subsets (update is lost because Team B's DR metadata is gone)
