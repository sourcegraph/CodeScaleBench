# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update

## Summary

When multiple DestinationRules (DRs) target the same host, Istio merges them into a single consolidated configuration during PushContext initialization. The merging process **loses the metadata identity (Name/Namespace) of contributing DRs**, causing only one DR's ConfigKey to be registered in the SidecarScope's config dependencies. When a non-primary DR is updated, the xDS push filter uses DependsOnConfig() to check if the proxy is affected, but the check fails because the updated DR's ConfigKey was never registered. As a result, the xDS push is **silently skipped**, and the Envoy sidecar receives no updated configuration until the pod is restarted.

---

## Root Cause

The root cause is the **loss of metadata identity during DestinationRule merging**, combined with **incomplete dependency tracking** and **incorrect xDS push filtering**.

### Mechanism

1. **Metadata Loss During Merge** (`pilot/pkg/model/destination_rule.go:38-109`)
   - The `mergeDestinationRule()` function merges multiple DRs for the same host by:
     - Finding the existing DR in `p.destRules[hostname]`
     - Modifying the EXISTING DR's config object in-place (subsets, traffic policies)
     - If selectors match, setting `addRuleToProcessedDestRules = false` (line 60)
     - NOT appending the new DR's config to the list (line 102 is skipped when `addRuleToProcessedDestRules == false`)
   - **Result**: Only the first DR's `config.Config` object survives in `p.destRules[hostname]`. The second (and subsequent) DR's Name/Namespace metadata is **never stored**.

2. **Incomplete Dependency Registration** (`pilot/pkg/model/sidecar.go:219-227`)
   - `DefaultSidecarScopeForNamespace()` iterates over `ps.destinationRule(configNamespace, s)` results
   - For each returned DR, it calls:
     ```go
     out.AddConfigDependencies(ConfigKey{
         Kind:      gvk.DestinationRule,
         Name:      dr.Name,      // Only the MERGED DR's name
         Namespace: dr.Namespace, // Only the MERGED DR's namespace
     })
     ```
   - Since `ps.destinationRule()` returns only one `config.Config` per hostname (the merged one), only ONE ConfigKey is registered.
   - **Result**: The second DR's ConfigKey is never added to `sc.configDependencies`.

3. **Push Filter Skips Unknown ConfigKeys** (`pilot/pkg/model/sidecar.go:521-540`)
   - When a config update occurs, `DependsOnConfig()` checks if the proxy depends on that config:
     ```go
     _, exists := sc.configDependencies[config.HashCode()]
     return exists
     ```
   - The HashCode is based on Kind, Name, and Namespace (lines 60-74 in `pilot/pkg/model/config.go`)
   - If the updated DR's ConfigKey hash is NOT in the map, `DependsOnConfig()` returns `false`.

4. **xDS Push Is Skipped** (`pilot/pkg/xds/proxy_dependencies.go:60-74` and `pilot/pkg/xds/ads.go:688`)
   - `checkProxyDependencies()` calls `proxy.SidecarScope.DependsOnConfig(config)` (line 64)
   - If it returns `false`, the push is filtered out
   - At line 688 of `ads.go`, if `ProxyNeedsPush()` returns `false`, the push to the proxy is **skipped entirely**
   - The proxy receives no updated xDS configuration and continues serving stale routes/clusters

---

## Evidence

### 1. Merge Function Loses Metadata (`destination_rule.go:38-109`)

**Line 38-60: Merge Detection and Decision**
```go
func (ps *PushContext) mergeDestinationRule(p *consolidatedDestRules, destRuleConfig config.Config, ...) {
    rule := destRuleConfig.Spec.(*networking.DestinationRule)
    resolvedHost := ResolveShortnameToFQDN(rule.Host, destRuleConfig.Meta)
    if mdrList, exists := p.destRules[resolvedHost]; exists {
        addRuleToProcessedDestRules := true
        for i, mdr := range mdrList {
            existingRule := mdr.Spec.(*networking.DestinationRule)
            bothWithoutSelector := rule.GetWorkloadSelector() == nil && existingRule.GetWorkloadSelector() == nil
            bothWithSelector := existingRule.GetWorkloadSelector() != nil && rule.GetWorkloadSelector() != nil
            selectorsMatch := labels.Instance(existingRule.GetWorkloadSelector().GetMatchLabels()).Equals(rule.GetWorkloadSelector().GetMatchLabels())

            if bothWithoutSelector || (rule.GetWorkloadSelector() != nil && selectorsMatch) {
                addRuleToProcessedDestRules = false  // LINE 60: Don't add new DR
            }
```

**Lines 63-93: Merge Data Into Existing Config**
```go
            copied := mdr.DeepCopy()  // Deep copy the EXISTING config
            p.destRules[resolvedHost][i] = &copied
            mergedRule := copied.Spec.(*networking.DestinationRule)

            // Add subsets from new rule to existing rule
            for _, subset := range rule.Subsets {
                if _, ok := existingSubset[subset.Name]; !ok {
                    mergedRule.Subsets = append(mergedRule.Subsets, subset)
                }
            }

            // Add traffic policy if missing
            if mergedRule.TrafficPolicy == nil && rule.TrafficPolicy != nil {
                mergedRule.TrafficPolicy = rule.TrafficPolicy
            }
        }
```

**Lines 101-104: New DR Config Is NOT Added**
```go
        if addRuleToProcessedDestRules {  // This is FALSE when merged
            p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
        }
        return  // Exit without adding new DR's config
    }
```

**Result**: The second DR's `config.Config` object (with Name: "reviews-subsets", Namespace: "default") is never stored.

---

### 2. Incomplete Dependency Registration (`sidecar.go:219-227`)

**DefaultSidecarScopeForNamespace() registers only merged DRs:**
```go
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,         // Only MERGED DR's name
            Namespace: dr.Namespace,    // Only MERGED DR's namespace
        })
    }
}
```

Since `out.destinationRules` is populated from `ps.destinationRule()` (line 209), which returns only the merged config, only one DR's metadata is registered.

Similarly, lines 410-416 in `ConvertToSidecarScope()`:
```go
for _, dr := range drList {
    out.AddConfigDependencies(ConfigKey{
        Kind:      gvk.DestinationRule,
        Name:      dr.Name,      // Only MERGED DR
        Namespace: dr.Namespace,
    })
}
```

---

### 3. ConfigKey Hash Lookup (`config.go:60-74` and `sidecar.go:538`)

**ConfigKey.HashCode() is based on Name, Namespace, and Kind:**
```go
func (key ConfigKey) HashCode() uint64 {
    hash := md5.New()
    for _, v := range []string{
        key.Name,       // Different for "reviews-subsets" vs "reviews-traffic-policy"
        key.Namespace,  // Same
        key.Kind.Kind,  // Same (DestinationRule)
        key.Kind.Group,
        key.Kind.Version,
    } {
        hash.Write([]byte(v))
    }
    ...
    return binary.BigEndian.Uint64(sum)
}
```

**DependsOnConfig() checks for the hash:**
```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    if sc == nil {
        return true
    }
    ...
    _, exists := sc.configDependencies[config.HashCode()]
    return exists  // FALSE if "reviews-subsets" was never registered
}
```

When `reviews-subsets` is updated, DependsOnConfig() is called with:
```
ConfigKey{Kind: DestinationRule, Name: "reviews-subsets", Namespace: "default"}
```

Its hash is NOT in `configDependencies` because only "reviews-traffic-policy" was registered.

---

### 4. xDS Push Filtering (`proxy_dependencies.go:60-74` and `ads.go:688`)

**checkProxyDependencies() calls DependsOnConfig():**
```go
func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        if proxy.SidecarScope.DependsOnConfig(config) {  // Returns FALSE
            return true
        } else if proxy.PrevSidecarScope != nil && proxy.PrevSidecarScope.DependsOnConfig(config) {
            return true
        }
    }
    return false  // Returns FALSE here
}
```

**ConfigAffectsProxy() uses checkProxyDependencies():**
```go
func ConfigAffectsProxy(req *model.PushRequest, proxy *model.Proxy) bool {
    for config := range req.ConfigsUpdated {
        if affected && checkProxyDependencies(proxy, config) {
            return true
        }
    }
    return false  // Returns FALSE
}
```

**DefaultProxyNeedsPush() checks ConfigAffectsProxy():**
```go
func DefaultProxyNeedsPush(proxy *model.Proxy, req *model.PushRequest) bool {
    if ConfigAffectsProxy(req, proxy) {  // Returns FALSE
        return true
    }
    ...
    return false  // Returns FALSE
}
```

**ads.go:688 skips the push:**
```go
if !s.ProxyNeedsPush(con.proxy, pushRequest) {
    log.Debugf("Skipping push to %v, no updates required", con.conID)
    if pushRequest.Full {
        reportAllEvents(s.StatusReporter, con.conID, pushRequest.Push.LedgerVersion, nil)
    }
    return nil  // PUSH IS SKIPPED
}
```

The proxy receives no updated configuration and continues serving stale Envoy routes and clusters.

---

### 5. Consolidated Structure Hides Multiple DRs (`push_context.go:251-256`)

```go
type consolidatedDestRules struct {
    exportTo map[host.Name]map[visibility.Instance]bool
    destRules map[host.Name][]*config.Config  // Map of hostname to LIST of configs
}
```

While the structure supports multiple DRs per hostname (a list), the merging process ensures that:
- For matching selectors, only ONE config object survives
- The others' metadata is lost, making them "invisible" to dependency tracking

---

## Affected Components

1. **`pilot/pkg/model/destination_rule.go`** - Merges multiple DRs, loses metadata
2. **`pilot/pkg/model/push_context.go`** - Stores merged DRs in index, no tracking of contributing DRs
3. **`pilot/pkg/model/sidecar.go`** - Registers only merged DR's metadata in configDependencies
4. **`pilot/pkg/model/config.go`** - ConfigKey hash depends on Name/Namespace
5. **`pilot/pkg/xds/proxy_dependencies.go`** - Filters pushes using DependsOnConfig() check
6. **`pilot/pkg/xds/ads.go`** - Skips push if ProxyNeedsPush() returns false
7. **`pilot/pkg/xds/delta.go`** - Similar push filtering for incremental updates

---

## Causal Chain

```
Step 1: Multiple DestinationRules for same host are created
        |
        v
Step 2: mergeDestinationRule() merges DR-2 into DR-1
        - Modifies DR-1's config object in-place
        - Sets addRuleToProcessedDestRules = false
        - Does NOT add DR-2's config.Config to destRules[hostname] list
        |
        v
Step 3: Only DR-1's metadata (Name, Namespace) is stored
        - DR-2's metadata is completely lost
        - p.destRules[hostname] = [DR-1 config only]
        |
        v
Step 4: DefaultSidecarScopeForNamespace() registers config dependencies
        - Iterates over ps.destinationRule() results
        - Calls AddConfigDependencies(ConfigKey{Name: DR-1.Name, ...})
        - DR-2's ConfigKey is never registered
        |
        v
Step 5: User updates DR-2 (e.g., adds v3 subset)
        - Config update event: ConfigKey{Name: "reviews-subsets", ...}
        |
        v
Step 6: xDS checks ConfigAffectsProxy() with DR-2's ConfigKey
        - Calls checkProxyDependencies()
        - Calls proxy.SidecarScope.DependsOnConfig(DR-2's ConfigKey)
        |
        v
Step 7: DependsOnConfig() computes DR-2's ConfigKey.HashCode()
        - Looks up hash in sc.configDependencies map
        - Hash NOT found (only DR-1's hash is there)
        - Returns FALSE
        |
        v
Step 8: checkProxyDependencies() returns FALSE
        - ConfigAffectsProxy() returns FALSE
        - DefaultProxyNeedsPush() returns FALSE
        |
        v
Step 9: ads.go:688 skips the push
        - if !s.ProxyNeedsPush(...) is TRUE
        - return nil without pushing to proxy
        |
        v
Step 10: Envoy sidecar receives NO updated configuration
        - Continues serving stale routes and clusters
        - Only a pod restart picks up the change
```

---

## Recommendation

### Fix Strategy

The root issue is that **multiple contributing DRs lose their identity during merging**. To fix this:

1. **Track All Contributing DRs**: Store the list of ALL contributing DR ConfigKeys in the `consolidatedDestRules` structure:
   ```go
   type consolidatedDestRules struct {
       exportTo map[host.Name]map[visibility.Instance]bool
       destRules map[host.Name][]*config.Config
       // NEW: Track ALL DRs that contributed to this merge
       contributingConfigKeys map[host.Name][]ConfigKey
   }
   ```

2. **Update mergeDestinationRule()** to record the ConfigKey of each incoming DR:
   - When a merge occurs, append the incoming DR's ConfigKey to `contributingConfigKeys`
   - When a new DR is added (no merge), record its ConfigKey

3. **Update AddConfigDependencies()** in `sidecar.go`:
   - Instead of only iterating `drList` (the merged config objects):
     ```go
     // OLD CODE: Only registers one DR per host
     for _, dr := range drList {
         out.AddConfigDependencies(ConfigKey{Name: dr.Name, ...})
     }
     ```
   - Iterate ALL contributing ConfigKeys from the consolidatedDestRules:
     ```go
     // NEW CODE: Registers ALL contributing DRs
     for _, cfg := range consolidatedDestRules.contributingConfigKeys[hostname] {
         out.AddConfigDependencies(cfg)
     }
     ```

### Diagnostic Steps

To verify this issue in a cluster:

1. Create two DestinationRules for the same host:
   ```bash
   kubectl apply -f - <<EOF
   apiVersion: networking.istio.io/v1alpha3
   kind: DestinationRule
   metadata:
     name: reviews-traffic-policy
     namespace: default
   spec:
     host: reviews.default.svc.cluster.local
     trafficPolicy:
       connectionPool:
         tcp:
           maxConnections: 100
   ---
   apiVersion: networking.istio.io/v1alpha3
   kind: DestinationRule
   metadata:
     name: reviews-subsets
     namespace: default
   spec:
     host: reviews.default.svc.cluster.local
     subsets:
       - name: v1
         labels:
           version: v1
   EOF
   ```

2. Check the sidecar's config dump:
   ```bash
   kubectl exec <pod> -c istio-proxy -- curl localhost:15000/config_dump | \
     jq '.configs[] | select(.type_url | contains("Cluster"))' | \
     grep -A5 "reviews"
   ```

3. Update `reviews-subsets` to add a new subset:
   ```bash
   kubectl patch destinationrule reviews-subsets --type merge \
     -p '{"spec":{"subsets":[{"name":"v1","labels":{"version":"v1"}},{"name":"v3","labels":{"version":"v3"}}]}}'
   ```

4. Check the sidecar config again - it should update **immediately**. If it doesn't, the bug is present.

5. Enable debug logging to observe the push filtering:
   ```bash
   kubectl port-forward -n istio-system svc/istiod 9881:9881
   curl http://localhost:9881/debug/pprof/trace?seconds=5 > trace.out
   # Look for calls to DependsOnConfig() returning false for "reviews-subsets"
   ```

---

## Files and Line Numbers for Reference

| Component | File | Lines | Purpose |
|-----------|------|-------|---------|
| Merge logic | `destination_rule.go` | 38-109 | Merges multiple DRs, loses metadata |
| Consolidated structure | `push_context.go` | 251-256 | Stores merged DRs (line 255 has map) |
| Merge calls | `push_context.go` | 1716, 1739, 1742 | Triggers mergeDestinationRule() |
| Dependency registration (default) | `sidecar.go` | 219-227 | DefaultSidecarScopeForNamespace registers DR deps |
| Dependency registration (custom) | `sidecar.go` | 410-416 | ConvertToSidecarScope registers DR deps |
| Dependency check | `sidecar.go` | 521-540 | DependsOnConfig checks if config affects proxy |
| Config hash | `config.go` | 60-74 | ConfigKey.HashCode() based on Name/Namespace |
| Proxy dependency check | `proxy_dependencies.go` | 60-74 | checkProxyDependencies calls DependsOnConfig |
| xDS push filtering | `ads.go` | 688 | Skips push if ProxyNeedsPush returns false |
| Similar filtering | `delta.go` | 141 | Incremental updates also skip based on ProxyNeedsPush |

