# Investigation Report

## Summary

When multiple DestinationRules are created for the same host, the `mergeDestinationRule()` function in `pilot/pkg/model/destination_rule.go` merges their specifications (subsets, traffic policies) into a single consolidated config while discarding the metadata identity of the contributing DRs. Consequently, only the first DR's ConfigKey is registered in the proxy's `SidecarScope.configDependencies`. When a contributing DR that was not preserved in the consolidated config is updated, the update event does not match any registered dependency, causing `DependsOnConfig()` to return false and the proxy push to be incorrectly skipped, leaving the Envoy sidecar with stale configuration.

## Root Cause

**File:** `pilot/pkg/model/destination_rule.go` (merging logic)
**Function:** `mergeDestinationRule()` (lines 38-109)
**Mechanism:** Metadata loss during consolidation

When multiple DestinationRules target the same FQDN host:

1. **First DR arrives** → added to `p.destRules[resolvedHost]` (line 107)
2. **Second DR arrives** → merges with first:
   - Deep copies the first DR (line 65)
   - Merges subsets and traffic policies from second DR into the copy (lines 77-93)
   - Updates `p.destRules[resolvedHost][0]` with the merged copy (line 66)
   - Does **not** add the second DR as a separate entry (line 101-104: `addRuleToProcessedDestRules` is false, so the second DR is discarded)

**Result:** `p.destRules[resolvedHost]` now contains only one config.Config object (the first DR, with merged specs). The second DR's identity (Name, Namespace) is permanently lost.

## Evidence

### 1. Merging Logic (destination_rule.go:38-109)

```go
func (ps *PushContext) mergeDestinationRule(p *consolidatedDestRules, destRuleConfig config.Config, ...) {
    // ...line 41: If a DR already exists for this host...
    if mdrList, exists := p.destRules[resolvedHost]; exists {
        // ...line 65-66: Deep copy the FIRST DR, modify it in-place
        copied := mdr.DeepCopy()
        p.destRules[resolvedHost][i] = &copied

        // ...line 77-87: Add subsets from the NEW DR to the copied FIRST DR
        for _, subset := range rule.Subsets {
            mergedRule.Subsets = append(mergedRule.Subsets, subset)
        }

        // ...line 91-92: Add traffic policy from NEW DR if FIRST DR doesn't have one
        if mergedRule.TrafficPolicy == nil && rule.TrafficPolicy != nil {
            mergedRule.TrafficPolicy = rule.TrafficPolicy
        }
    }
    // ...line 101-104: If addRuleToProcessedDestRules is false, do NOT add the new DR separately
    if addRuleToProcessedDestRules {
        p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
    }
}
```

**Key Issue:** The `destRuleConfig` (second DR) is never added to `p.destRules[resolvedHost]` when `addRuleToProcessedDestRules` is false. Its specs are merged into a copy of the first DR, but its metadata (Name, Namespace from `destRuleConfig.Name` and `destRuleConfig.Namespace`) is lost forever.

### 2. Dependency Tracking in SidecarScope (sidecar.go:219-227, 410-416)

**DefaultSidecarScopeForNamespace (lines 219-227):**
```go
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,           // Only uses the config's Name field
            Namespace: dr.Namespace,       // Only uses the config's Namespace field
        })
    }
}
```

**ConvertToSidecarScope (lines 410-416):**
```go
for _, dr := range drList {
    out.AddConfigDependencies(ConfigKey{
        Kind:      gvk.DestinationRule,
        Name:      dr.Name,               // Only uses the config's Name field
        Namespace: dr.Namespace,           // Only uses the config's Namespace field
    })
}
```

**Problem:** Both iterate over `out.destinationRules` (which comes from `ps.destinationRule()`), which returns the consolidated list from `p.destRules[hostname]`. Since only the first DR is in this list, only its ConfigKey is registered. The second DR's ConfigKey is never added to `configDependencies`.

### 3. xDS Push Filter (proxy_dependencies.go:60-74)

```go
func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        if proxy.SidecarScope.DependsOnConfig(config) {  // Line 64
            return true
        } else if proxy.PrevSidecarScope != nil && proxy.PrevSidecarScope.DependsOnConfig(config) {
            return true
        }
    }
    return false
}
```

**DependsOnConfig (sidecar.go:523-540):**
```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    // ... check for cluster-scoped configs ...

    // Line 538: Check if this config's hash is in registered dependencies
    _, exists := sc.configDependencies[config.HashCode()]
    return exists
}
```

**Failure:** When an update event for the second DR (reviews-subsets) arrives, it creates a ConfigKey with Name="reviews-subsets" and Namespace="default". The hash of this key is looked up in `configDependencies`. Since only the first DR's key is registered, the lookup fails and `DependsOnConfig()` returns false. The proxy is not pushed.

### 4. Config Update Event Handler (bootstrap/server.go:881-904)

```go
configHandler := func(prev config.Config, curr config.Config, event model.Event) {
    pushReq := &model.PushRequest{
        Full: true,
        ConfigsUpdated: map[model.ConfigKey]struct{}{{
            Kind:      curr.GroupVersionKind,       // DestinationRule
            Name:      curr.Name,                   // reviews-subsets (when updated)
            Namespace: curr.Namespace,               // default
        }: {}},
        Reason: []model.TriggerReason{model.ConfigUpdate},
    }
    s.XDSServer.ConfigUpdate(pushReq)
}
```

**Result:** When `reviews-subsets` is updated, the event handler creates a PushRequest with ConfigKey{Name: "reviews-subsets", Namespace: "default"}. However, the proxy's `SidecarScope.configDependencies` only contains the hash of ConfigKey{Name: "reviews-traffic-policy", Namespace: "default"}. The push filtering rejects the update as not affecting this proxy.

## Affected Components

1. **pilot/pkg/model/destination_rule.go**
   - `mergeDestinationRule()` - Merges multiple DRs but discards metadata identity

2. **pilot/pkg/model/sidecar.go**
   - `DefaultSidecarScopeForNamespace()` - Registers only DRs present in consolidated list
   - `ConvertToSidecarScope()` - Same limitation
   - `AddConfigDependencies()` - Receives incomplete DR list

3. **pilot/pkg/model/push_context.go**
   - `destinationRule()` - Returns only consolidated DRs, not original sources
   - `SetDestinationRules()` - Calls `mergeDestinationRule()`
   - `consolidatedDestRules` struct - Stores only consolidated, not original, DRs

4. **pilot/pkg/xds/proxy_dependencies.go**
   - `checkProxyDependencies()` - Relies on complete dependency registration
   - `ConfigAffectsProxy()` - Calls dependency check

5. **pilot/pkg/bootstrap/server.go**
   - `configHandler()` - Creates update events with original DR metadata

## Causal Chain

1. **Symptom:** Envoy sidecar shows stale cluster and route configuration after DestinationRule update
   - Verified via `GET /debug/config_dump` on sidecar
   - Pod restart picks up the change (because full recomputation happens)

2. **→ xDS push was skipped** for the updated DestinationRule
   - No CDS/RDS update was sent to the sidecar
   - `ConfigAffectsProxy()` returned false in `proxy_dependencies.go:32-58`

3. **→ Push filter rejected the update** because proxy didn't depend on the updated DR
   - `checkProxyDependencies()` called `DependsOnConfig()` (line 64)
   - `DependsOnConfig()` returned false (sidecar.go:538)

4. **→ Updated DR's ConfigKey was not in registered dependencies**
   - The updated DR (e.g., "reviews-subsets") had a ConfigKey hash not in `configDependencies`
   - Only the first DR's ConfigKey was registered in sidecar scope initialization

5. **→ Only the first DR's metadata survived consolidation**
   - When `mergeDestinationRule()` processed the second DR (line 38-109 in destination_rule.go)
   - It merged the second DR's specs into a copy of the first DR
   - But did not add the second DR to `p.destRules[resolvedHost]` (line 101-104)
   - The second DR's Name and Namespace were lost

6. **→ Root cause: Merged DestinationRule loses contributor identities**
   - `mergeDestinationRule()` consolidates multiple DRs for the same host into one
   - The consolidated config retains the first DR's metadata
   - Subsequent DRs' metadata is discarded after their specs are merged in
   - No audit trail or tracking of which original DRs contributed to the consolidated config

## Recommendation

### Fix Strategy

The root cause is the loss of identity metadata during DR consolidation. Two approaches:

**Option A (Preferred): Track all contributing DRs**
- Modify `consolidatedDestRules` to store a list of original ConfigKeys that contributed to each consolidated DR
- When building `SidecarScope.configDependencies`, register all contributing DRs' ConfigKeys, not just the consolidated one
- Requires changes to:
  - `consolidatedDestRules` struct in `push_context.go` (add field like `contributingDRs map[host.Name][]ConfigKey`)
  - `mergeDestinationRule()` in `destination_rule.go` (track which DRs were merged)
  - `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` in `sidecar.go` (register all contributing DRs)

**Option B (Alternative): Preserve all merged DRs separately**
- Modify `mergeDestinationRule()` to keep all DRs (not just the consolidated one) in `p.destRules[resolvedHost]`
- Each DR would be in the list, with their separate specs and metadata preserved
- Requires rethinking the consolidation strategy (may have other implications for RDS/CDS generation)

### Diagnostic Steps for Users

1. **Check if issue is occurring:**
   ```bash
   # On pod with old config:
   istioctl debug config-dump <pod> | grep -A 20 "cluster:"

   # Check if more recent than pod restart:
   kubectl get dr -A -o json | jq '.items[] | {name, creationTime}'
   ```

2. **Identify affected DRs:**
   - Find all DRs for the same host: `kubectl get dr -A | grep <hostname>`
   - Check creation times and spec differences
   - If two or more exist for same host, they're being merged

3. **Workaround (temporary):**
   - Combine conflicting DRs into a single DestinationRule with all subsets and policies
   - Delete the redundant DRs
   - Verify pod picks up changes without restart

4. **Verify fix:**
   - After fix, update one of multiple DRs for same host
   - Monitor sidecar logs: `kubectl logs <pod> -c istio-proxy | grep updated`
   - Check `config_dump` for fresh timestamps
   - No pod restart should be needed
