# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update in Istio

## Summary

When multiple DestinationRules are defined for the same host in Istio, updating one of them fails to trigger an xDS push to Envoy sidecars. The root cause is that the DestinationRule merging process loses metadata identity of contributing DRs, causing the xDS push filter to incorrectly skip affected proxies because their dependency tracking only registers the merged DR's identity (retained from the first DR), not all contributing DRs.

## Root Cause

The causal chain spans the merging pipeline (`destination_rule.go`), dependency tracking (`sidecar.go`), and xDS push filtering (`proxy_dependencies.go`):

1. **Metadata Loss During Merge**: When two DestinationRules for the same host are merged via `mergeDestinationRule()` (line 38 in `destination_rule.go`), the second DR's subsets and traffic policies are merged into the first DR's `config.Config` object. However, the second DR's Name and Namespace metadata are **never recorded** — only the first DR's metadata survives.

2. **Incomplete Dependency Registration**: When `DefaultSidecarScopeForNamespace()` (line 173 in `sidecar.go`) and `ConvertToSidecarScope()` (line 254 in `sidecar.go`) build a SidecarScope, they iterate over the merged destination rules and call `AddConfigDependencies()` (lines 221-225) to register which config resources the proxy depends on. Since the merged DR has only one name/namespace (the first DR's), only that one ConfigKey is registered. **The second DR's ConfigKey is completely absent from the dependency map**.

3. **Failed Push Detection**: When a DestinationRule is updated, the xDS system calls `ConfigAffectsProxy()` (line 32 in `proxy_dependencies.go`), which invokes `checkProxyDependencies()` (line 60). This calls `SidecarScope.DependsOnConfig()` (line 64 in `proxy_dependencies.go`), which checks if the updated config's ConfigKey hash exists in `configDependencies` (line 538 in `sidecar.go`). If the updated DR is the second one (whose ConfigKey was lost during merge), `DependsOnConfig()` returns `false`, and the push is **incorrectly skipped**.

## Evidence

### Merging Process (Loss of Metadata)

**File**: `pilot/pkg/model/destination_rule.go`
**Function**: `mergeDestinationRule()` (line 38)

```go
// When a second DR exists for the same host:
if mdrList, exists := p.destRules[resolvedHost]; exists {
    for i, mdr := range mdrList {
        // ... merge logic ...
        // Deep copy the FIRST rule (line 65)
        copied := mdr.DeepCopy()
        p.destRules[resolvedHost][i] = &copied
        mergedRule := copied.Spec.(*networking.DestinationRule)

        // Add subsets from incoming rule to merged rule (line 80)
        mergedRule.Subsets = append(mergedRule.Subsets, subset)

        // Add traffic policy from incoming rule if missing (line 92)
        if mergedRule.TrafficPolicy == nil && rule.TrafficPolicy != nil {
            mergedRule.TrafficPolicy = rule.TrafficPolicy
        }
    }
    // Line 101-102: The second rule is only added if it has different selectors
    if addRuleToProcessedDestRules {
        p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
    }
    return
}
```

**Critical Issue**: The merged `config.Config` object at `p.destRules[resolvedHost][i]` retains the metadata (Name/Namespace) of the first DR (`mdr`). The second DR's configuration is merged into the first, but the second DR's identity is lost.

### Dependency Registration (Only First DR Recorded)

**File**: `pilot/pkg/model/sidecar.go`
**Function**: `DefaultSidecarScopeForNamespace()` (line 173)

```go
// Line 209-211: Retrieve merged DRs from PushContext
if dr := ps.destinationRule(configNamespace, s); dr != nil {
    out.destinationRules[s.Hostname] = dr
}

// Line 219-226: Register dependencies for each DR
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,        // <-- Only the first DR's name is here
            Namespace: dr.Namespace,    // <-- Only the first DR's namespace is here
        })
    }
}
```

The loop at line 220-226 iterates over `out.destinationRules`, which is populated from `ps.destinationRule()`. This function (line 990 in `push_context.go`) returns the merged DRs from `ps.destinationRuleIndex`, which contains the result of the merge operation. **Only the merged DR is present in the list, so only one ConfigKey is registered, even though two physical DRs contributed to it**.

The same issue exists in `ConvertToSidecarScope()` (line 254 in `sidecar.go`), lines 299-303 and 345-349.

### Dependency Tracking via ConfigKey Hash

**File**: `pilot/pkg/model/config.go`
**Function**: `ConfigKey.HashCode()` (line 60)

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

The hash depends on Name and Namespace. If a second DR with a different name is updated, its ConfigKey will have a different hash that won't match any entry in `configDependencies`.

### Dependency Check (Missing Second DR)

**File**: `pilot/pkg/model/sidecar.go`
**Function**: `DependsOnConfig()` (line 523)

```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    if sc == nil {
        return true
    }

    // ... cluster-scoped and unknown config types ...

    // Line 538: Check if the config's hash is in the registered dependencies
    _, exists := sc.configDependencies[config.HashCode()]
    return exists
}
```

**File**: `pilot/pkg/model/sidecar.go`
**Function**: `AddConfigDependencies()` (line 544)

```go
func (sc *SidecarScope) AddConfigDependencies(dependencies ...ConfigKey) {
    // ...
    for _, config := range dependencies {
        // Line 553: Store the config's hash
        sc.configDependencies[config.HashCode()] = struct{}{}
    }
}
```

When the merged DR is registered, only its hash (based on the first DR's name/namespace) is stored. When the second DR is updated, its ConfigKey will hash to a different value (different name), so the lookup at line 538 returns `false`.

### xDS Push Filtering (Incorrect Skip)

**File**: `pilot/pkg/xds/proxy_dependencies.go`
**Function**: `ConfigAffectsProxy()` (line 32)

```go
func ConfigAffectsProxy(req *model.PushRequest, proxy *model.Proxy) bool {
    // ...
    for config := range req.ConfigsUpdated {
        affected := true
        // ... some filters ...

        // Line 52: Call checkProxyDependencies
        if affected && checkProxyDependencies(proxy, config) {
            return true
        }
    }

    return false
}
```

**Function**: `checkProxyDependencies()` (line 60)

```go
func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        // Line 64: Call DependsOnConfig with the updated config
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

When the second DR is updated (e.g., adding a subset), `ConfigAffectsProxy()` is called with that DR's ConfigKey. The call to `DependsOnConfig()` at line 64 returns `false` because the second DR's ConfigKey hash was never registered. The proxy is not marked for an xDS push.

## Affected Components

1. **pilot/pkg/model/destination_rule.go** — `mergeDestinationRule()` function loses metadata identity during merge
2. **pilot/pkg/model/sidecar.go** — `DefaultSidecarScopeForNamespace()`, `ConvertToSidecarScope()`, `AddConfigDependencies()`, `DependsOnConfig()` — dependency tracking only registers merged DR identity
3. **pilot/pkg/model/push_context.go** — `destinationRule()` returns merged configs, obscuring the fact that multiple DRs contributed
4. **pilot/pkg/xds/proxy_dependencies.go** — `ConfigAffectsProxy()`, `checkProxyDependencies()` — push filtering relies on incomplete dependency tracking

## Causal Chain

1. **Operator creates two DestinationRules for the same host**:
   - `reviews-traffic-policy`: defines trafficPolicy (e.g., connection pool)
   - `reviews-subsets`: defines subsets (v1, v2)

2. **During PushContext initialization**:
   - `initDestinationRules()` calls `mergeDestinationRule()` for each DR
   - The first DR (`reviews-traffic-policy`) is stored in `p.destRules[host]`
   - The second DR (`reviews-subsets`) is merged into the first
   - Result: A single merged config object with `reviews-traffic-policy` metadata (name/namespace)

3. **During SidecarScope creation**:
   - `ps.destinationRule()` returns the merged DR from `destinationRuleIndex`
   - The merged DR is added to `destinationRules` map
   - `AddConfigDependencies()` is called with ConfigKey for `reviews-traffic-policy` only
   - `reviews-subsets` ConfigKey is never registered

4. **When `reviews-subsets` is updated**:
   - An update event creates ConfigKey for `reviews-subsets`
   - `ConfigAffectsProxy()` checks if any proxy depends on it
   - `DependsOnConfig()` looks for the hash of `reviews-subsets` in the registered dependencies
   - The hash is **not found** (only `reviews-traffic-policy` hash is registered)
   - The proxy is not marked for push
   - Envoy sidecar receives no update and continues with stale configuration

5. **Only restarting the pod picks up the change** because:
   - Pod restart triggers `initSidecarScopes()` again
   - A fresh SidecarScope is computed with the current merged DRs
   - The pod receives the full configuration during reconnection

## Recommendation

### Fix Strategy

The root issue is that the merging process conflates multiple source DRs into a single merged DR while retaining only one's metadata. The solution requires tracking which DRs contributed to a merged DR so that dependency registration includes all contributors.

**Proposed approaches**:

1. **Option A - Extended Metadata**: Enhance `consolidatedDestRules` to track a list of contributing ConfigKeys alongside the merged config. Update `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` to register dependencies for all contributing DRs, not just the merged one.

2. **Option B - Separate Merging and Indexing**: Decouple the merging of subsets/traffic policies from the metadata identity. When returning merged DRs via `ps.destinationRule()`, include metadata about all contributing DRs so the SidecarScope can track them.

3. **Option C - Reverse-Lookup in xDS Filter**: When a DestinationRule is updated, check if it contributed to any merged DR in the destination rule index, then push to proxies that depend on that merged DR.

### Diagnostic Steps

1. **Verify the merged DR**: In Pilot, inspect the destination rule index after initialization:
   ```
   GET http://pilot:15014/debug/configz
   ```
   Search for `destinationRuleIndex` and verify that when two DRs target the same host, only one ConfigKey appears in the dependency maps.

2. **Trace SidecarScope dependencies**: Add debug logging to `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` to output all ConfigKey entries being registered. Compare this list against the actual DRs in the cluster.

3. **Monitor push events**: Use Pilot's push metrics to detect when a DestinationRule update doesn't trigger a proxy push:
   ```
   # In Prometheus
   rate(pilot_push_triggers[5m])
   rate(pilot_proxy_push_count[5m])
   ```
   Correlate DestinationRule updates with missing push events.

4. **Envoy config comparison**: Compare `GET http://envoy-sidecar:15000/config_dump` before and after the update to confirm it remains unchanged.

## Summary of Code Flow

```
DestinationRule Update
  ↓
initDestinationRules() [push_context.go:1644]
  ↓
mergeDestinationRule() [destination_rule.go:38]
  ├─ Merges subsets and traffic policies
  └─ LOSES second DR's metadata identity
  ↓
consolidatedDestRules.destRules[host] = [merged config]
  ↓
DefaultSidecarScopeForNamespace() [sidecar.go:173]
  ↓
ps.destinationRule(namespace, service) [push_context.go:990]
  ├─ Returns merged DRs from destinationRuleIndex
  └─ Only first DR's metadata present
  ↓
AddConfigDependencies(ConfigKey{Name: "reviews-traffic-policy", ...}) [sidecar.go:221]
  ├─ Registers only merged DR's ConfigKey
  └─ Second DR's ConfigKey NEVER registered
  ↓
Later: reviews-subsets DestinationRule is updated
  ↓
ConfigAffectsProxy(proxy, ConfigKey{Name: "reviews-subsets", ...}) [proxy_dependencies.go:32]
  ↓
checkProxyDependencies(proxy, config) [proxy_dependencies.go:60]
  ↓
DependsOnConfig(config) [sidecar.go:523]
  ├─ Looks for hash of "reviews-subsets" in configDependencies
  ├─ NOT FOUND (only "reviews-traffic-policy" hash present)
  └─ Returns false
  ↓
ConfigAffectsProxy returns false
  ↓
Proxy is NOT marked for xDS push
  ↓
Envoy sidecar remains on stale configuration
```
