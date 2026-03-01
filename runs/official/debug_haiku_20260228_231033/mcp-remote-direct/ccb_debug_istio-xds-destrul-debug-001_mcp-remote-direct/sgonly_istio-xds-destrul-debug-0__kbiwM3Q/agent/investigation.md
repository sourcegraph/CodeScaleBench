# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update

## Summary

When multiple DestinationRules exist for the same host (e.g., one defining subsets, another defining traffic policy), updating one of them fails to trigger an xDS push to Envoy sidecars. The root cause is that during the merge process, only one DestinationRule's metadata (Name/Namespace) is preserved in the consolidated structure, causing the other DR's ConfigKey to never be registered as a dependency. Subsequently, when that DR is updated, the xDS push filter incorrectly determines the proxy does not depend on it and skips the push.

## Root Cause

The bug spans the intersection of three components:

1. **Destination Rule Merging** (`pilot/pkg/model/destination_rule.go:mergeDestinationRule()`)
   - Multiple DestinationRules for the same host are merged into a single entry in the `consolidatedDestRules.destRules` map
   - The merge combines specs (subsets, traffic policy) but preserves only one DR's `config.Config` metadata

2. **Config Dependency Tracking** (`pilot/pkg/model/sidecar.go:DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()`)
   - These functions iterate over the merged DRs and call `AddConfigDependencies()` with each DR's Name and Namespace
   - Since merged DRs have only one metadata record, only one DR's ConfigKey is registered

3. **xDS Push Filtering** (`pilot/pkg/xds/proxy_dependencies.go:ConfigAffectsProxy()`)
   - When a config change occurs, it checks if the proxy depends on that config via `SidecarScope.DependsOnConfig()`
   - If the changed DR's metadata was lost during merging, its ConfigKey is not in the registered dependencies
   - `DependsOnConfig()` returns false, and the xDS push is skipped

## Evidence

### 1. Destination Rule Merge Process

**File:** `pilot/pkg/model/destination_rule.go:38-109`

The `mergeDestinationRule()` function processes a new DestinationRule:

- **Line 41-104:** If an existing DR exists for the same host:
  - **Line 65-66:** A deep copy is made: `copied := mdr.DeepCopy()` and then `p.destRules[resolvedHost][i] = &copied`
  - **Line 70-87:** Subsets from the new DR are merged into the existing one's spec
  - **Line 89-93:** Traffic policy is merged if the existing one is nil

- **Line 101-103:** If no existing DR matches: `p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)`
- **Line 107-108:** If no DR exists for the host at all: `p.destRules[resolvedHost] = append(...)`

**Critical Issue:** The merged entry retains the metadata (Name, Namespace) of the **first** DR that matched. When a second DR for the same host merges into it, the second DR's metadata is discarded.

### 2. Consolidation Flow

**File:** `pilot/pkg/model/push_context.go:1672-1744`

The `SetDestinationRules()` function builds the consolidated index:

- **Line 1675:** Configs are sorted by creation time
- **Line 1676-1678:** Three consolidation structures are created: `namespaceLocalDestRules`, `exportedDestRulesByNamespace`, and `rootNamespaceLocalDestRules` (all of type `*consolidatedDestRules`)
- **Line 1716, 1739, 1742:** `mergeDestinationRule()` is called for each DR, passing the consolidation structure

**Result:** After consolidation, the `consolidatedDestRules.destRules` map contains only one config.Config entry per host, with the metadata of whichever DR was processed first.

### 3. Config Dependency Registration

**File:** `pilot/pkg/model/sidecar.go:219-227 (DefaultSidecarScopeForNamespace)`

```go
for _, drList := range out.destinationRules {
    for _, dr := range drList {
        out.AddConfigDependencies(ConfigKey{
            Kind:      gvk.DestinationRule,
            Name:      dr.Name,
            Namespace: dr.Namespace,
        })
    }
}
```

- **Line 209:** `out.destinationRules[s.Hostname] = dr` retrieves the merged DRs from `ps.destinationRule()`
- **Line 219-227:** For each DR in the list, a ConfigKey is added

**Problem:** Since `out.destinationRules` contains only one merged entry per hostname, only one DR's ConfigKey is added to the dependency set.

Similarly, in `ConvertToSidecarScope()` at **lines 408-417**, the same pattern repeats.

### 4. SidecarScope Dependency Filtering

**File:** `pilot/pkg/model/sidecar.go:521-540`

The `DependsOnConfig()` method checks if a ConfigKey is registered:

```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    // ...
    _, exists := sc.configDependencies[config.HashCode()]
    return exists
}
```

- **Line 538:** The method looks up `config.HashCode()` in the map
- **Line 539:** Returns true only if the ConfigKey is registered

**Impact:** If a DR's ConfigKey was never added (because its metadata was lost during merging), this returns false.

### 5. xDS Push Decision

**File:** `pilot/pkg/xds/proxy_dependencies.go:30-74`

The `ConfigAffectsProxy()` function determines if a config change requires an xDS push:

```go
func ConfigAffectsProxy(req *model.PushRequest, proxy *model.Proxy) bool {
    for config := range req.ConfigsUpdated {
        affected := true
        // ...
        if affected && checkProxyDependencies(proxy, config) {
            return true
        }
    }
    return false
}

func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
    switch proxy.Type {
    case model.SidecarProxy:
        if proxy.SidecarScope.DependsOnConfig(config) {
            return true
        }
        // ...
    }
    return false
}
```

- **Line 38-54:** For each updated config, checks if it affects the proxy via `checkProxyDependencies()`
- **Line 64:** Calls `SidecarScope.DependsOnConfig(config)`
- **Line 52-54:** Only returns true if the dependency check passes

**Failure:** When a DR's ConfigKey (whose metadata was lost during merge) is in `ConfigsUpdated`, `DependsOnConfig()` returns false, so `ConfigAffectsProxy()` returns false, and the proxy is **not pushed** new configuration.

### 6. Merged Structure Definition

**File:** `pilot/pkg/model/push_context.go:251-256`

```go
type consolidatedDestRules struct {
    // Map of dest rule host to the list of namespaces to which this destination rule has been exported to
    exportTo map[host.Name]map[visibility.Instance]bool
    // Map of dest rule host and the merged destination rules for that host
    destRules map[host.Name][]*config.Config
}
```

- **Line 255:** Each hostname maps to a **list** of `config.Config`, but in practice only one entry (with merged spec) exists per hostname when multiple DRs are consolidated
- **No tracking** of which DRs contributed to the merge

## Affected Components

1. **`pilot/pkg/model/destination_rule.go`** - Merge logic that loses metadata
2. **`pilot/pkg/model/push_context.go`** - Consolidation and indexing of merged DRs
3. **`pilot/pkg/model/sidecar.go`** - Config dependency registration that only registers visible metadata
4. **`pilot/pkg/xds/proxy_dependencies.go`** - Push filtering that relies on incomplete dependency information

## Causal Chain

1. **Symptom:** Envoy sidecar receives stale configuration after updating a merged DestinationRule

2. **First Hop - Merge Process:**
   - Operator applies two DestinationRules for `reviews.default.svc.cluster.local`
   - DR-1 (with traffic policy) is processed first → stored in `consolidatedDestRules.destRules[reviews...][0]`
   - DR-2 (with subsets) is processed second
   - `mergeDestinationRule()` matches DR-2 to DR-1's entry and merges specs
   - **Result:** `consolidatedDestRules.destRules[reviews...]` contains **one** entry with DR-1's metadata and merged spec

3. **Second Hop - Dependency Registration:**
   - When building SidecarScope for a proxy in the namespace:
   - `DefaultSidecarScopeForNamespace()` or `ConvertToSidecarScope()` calls `ps.destinationRule()`
   - This returns the merged entry from `consolidatedDestRules.destRules`
   - Code iterates over the returned list and adds ConfigKey for each: **only DR-1's ConfigKey is added**
   - DR-2's ConfigKey is **never added** because its metadata was discarded

4. **Third Hop - Update Event:**
   - Operator updates DR-2 (e.g., adding a `v3` subset)
   - Config controller emits ConfigChangeEvent with ConfigKey(Name=reviews-subsets, Namespace=default)
   - Event is packaged into `PushRequest.ConfigsUpdated`

5. **Fourth Hop - Push Decision:**
   - xDS discoveryServer processes the push request
   - Calls `ConfigAffectsProxy()` for each proxy with ConfigKey(Name=reviews-subsets, Namespace=default)
   - Calls `checkProxyDependencies(proxy, config)`
   - Calls `proxy.SidecarScope.DependsOnConfig(config)`
   - Looks up ConfigKey hash in `configDependencies` map
   - **Hash not found** because only DR-1's ConfigKey was registered
   - Returns `false`

6. **Root Cause:**
   - `ConfigAffectsProxy()` returns `false` for this proxy
   - The proxy is **not added** to the push list
   - Envoy sidecar **does not receive** the updated configuration
   - **Result:** Stale configuration persists until pod restart

## Recommendation

**Fix Strategy:**

The consolidation process must preserve metadata for **all** contributing DestinationRules, not just the first one. Two approaches:

### Approach 1: Extend consolidatedDestRules Structure
Modify `consolidatedDestRules` to track all contributing DRs:
```go
type consolidatedDestRules struct {
    exportTo map[host.Name]map[visibility.Instance]bool
    destRules map[host.Name][]*config.Config
    // NEW: Track all DRs that contributed to each hostname
    contributingDRs map[host.Name][][]ConfigKey  // hostname -> list of (list of contributing DR ConfigKeys)
}
```
Then in sidecar.go, when adding dependencies, iterate over `contributingDRs` instead of just the final merged DRs.

### Approach 2: Flatten Consolidated Structure
Instead of merging multiple DRs into one entry, keep them separate but with a merged spec:
```go
// When merging, create a new entry with merged spec but all original metadata
consolidatedEntry := &consolidatedDRMetadata{
    mergedSpec: ... // combined subsets + traffic policy
    sourceNames: []string{dr1.Name, dr2.Name}  // track sources
    sourceNamespaces: []string{dr1.Namespace, dr2.Namespace}
}
```

**Diagnostic Steps:**

1. Add logging to `mergeDestinationRule()` to track which DRs are being merged
2. In sidecar.go, log all ConfigKeys being added to dependencies for each service
3. In proxy_dependencies.go, log why `DependsOnConfig()` returned false for specific ConfigKeys
4. Compare the logged dependencies against `ConfigsUpdated` in a config change event

**Immediate Workaround:**

Until the fix is deployed, users experiencing this issue should:
1. Consolidate multiple DestinationRules for the same host into a single CR
2. Or restart affected pods after updating any merged DestinationRule to force re-pulls of merged configuration
