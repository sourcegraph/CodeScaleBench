# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update

## Summary

When multiple DestinationRules for the same host are merged during PushContext initialization, only the metadata (name/namespace) of the first DR is retained in the consolidated structure. Consequently, when SidecarScope builds config dependencies, only that one DR's ConfigKey is registered. When the second (or other contributing) DR is updated later, its ConfigKey is not found in the sidecar's `configDependencies`, causing `DependsOnConfig()` to return false and the xDS push to be incorrectly skipped.

---

## Root Cause

**Location**: `pilot/pkg/model/destination_rule.go` line 38-109, specifically the `mergeDestinationRule()` function in conjunction with dependency tracking in `pilot/pkg/model/sidecar.go` lines 219-227 and 410-416.

**Mechanism**:
1. When `mergeDestinationRule()` merges multiple DRs for the same host, the function modifies the first matching DR in-place by appending subsets and traffic policies from the incoming DR
2. The consolidated entry in `destRules[resolvedHost]` contains merged spec from both DRs but retains **only** the metadata (Name/Namespace) of the first DR
3. When `DefaultSidecarScopeForNamespace()` or `ConvertToSidecarScope()` iterate over `destinationRules` to register dependencies, they call `AddConfigDependencies(ConfigKey{Kind: DestinationRule, Name: dr.Name, Namespace: dr.Namespace})` only for the DRs that exist in the consolidated list
4. Since the second DR was merged into the first and not added as a separate entry, its ConfigKey is never registered
5. When the second DR is updated, `ConfigAffectsProxy()` calls `DependsOnConfig()` with the second DR's ConfigKey, which returns false (not in `configDependencies`), and the push is skipped

---

## Evidence

### 1. Merge Process in destination_rule.go

**File**: `pilot/pkg/model/destination_rule.go:38-109`

The `mergeDestinationRule()` function handles multiple DRs for the same host:

```go
func (ps *PushContext) mergeDestinationRule(p *consolidatedDestRules, destRuleConfig config.Config, exportToMap map[visibility.Instance]bool) {
	rule := destRuleConfig.Spec.(*networking.DestinationRule)
	resolvedHost := ResolveShortnameToFQDN(rule.Host, destRuleConfig.Meta)
	if mdrList, exists := p.destRules[resolvedHost]; exists {
		// Line 43-44: Loop through existing merged destination rules
		for i, mdr := range mdrList {
			existingRule := mdr.Spec.(*networking.DestinationRule)
			// ... selector matching logic ...

			// Line 65-66: Deep copy the FIRST matched DR and modify it in place
			copied := mdr.DeepCopy()
			p.destRules[resolvedHost][i] = &copied
			mergedRule := copied.Spec.(*networking.DestinationRule)

			// Line 77-87: Append subsets from incoming DR to the first DR
			for _, subset := range rule.Subsets {
				if _, ok := existingSubset[subset.Name]; !ok {
					mergedRule.Subsets = append(mergedRule.Subsets, subset)
				}
			}
			// ... continue with traffic policy merging ...
		}
		// Line 101-103: If addRuleToProcessedDestRules is false (merge happened),
		// the incoming DR is NOT added to the list
		if addRuleToProcessedDestRules {
			p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
		}
		return
	}
	// ...
}
```

**Critical observation**: After merging, `destRules[resolvedHost]` contains only ONE config.Config entry (the modified first DR). The second DR's subsets are merged into this entry, but the second DR itself is not stored in the consolidated list. **The Name and Namespace of the second DR are lost**.

### 2. Consolidation Structure

**File**: `pilot/pkg/model/push_context.go:251-256`

```go
type consolidatedDestRules struct {
	// Map of dest rule host to the list of namespaces to which this destination rule has been exported to
	exportTo map[host.Name]map[visibility.Instance]bool
	// Map of dest rule host and the merged destination rules for that host
	destRules map[host.Name][]*config.Config  // <-- Only stores config.Config pointers, not original metadata
}
```

The `destRules` map stores pointers to `config.Config` objects. After merging, each `config.Config` entry has only the metadata of whichever DR was originally stored (and potentially modified).

### 3. Dependency Registration in SidecarScope

**File**: `pilot/pkg/model/sidecar.go:219-227` (DefaultSidecarScopeForNamespace)

```go
for _, drList := range out.destinationRules {
	for _, dr := range drList {
		out.AddConfigDependencies(ConfigKey{
			Kind:      gvk.DestinationRule,
			Name:      dr.Name,                 // <-- Only the FIRST DR's Name
			Namespace: dr.Namespace,            // <-- Only the FIRST DR's Namespace
		})
	}
}
```

Similarly in `pilot/pkg/model/sidecar.go:410-416` (ConvertToSidecarScope):

```go
if drList := ps.destinationRule(configNamespace, s); drList != nil {
	out.destinationRules[s.Hostname] = drList
	for _, dr := range drList {
		out.AddConfigDependencies(ConfigKey{
			Kind:      gvk.DestinationRule,
			Name:      dr.Name,              // <-- dr.Name from consolidated list
			Namespace: dr.Namespace,         // <-- dr.Namespace from consolidated list
		})
	}
}
```

**Issue**: These loops iterate over the consolidated list `destRules[hostname]`, which only contains the first DR after merging. The second DR's ConfigKey is never registered.

### 4. AddConfigDependencies Implementation

**File**: `pilot/pkg/model/sidecar.go:542-555`

```go
func (sc *SidecarScope) AddConfigDependencies(dependencies ...ConfigKey) {
	if sc == nil {
		return
	}
	if sc.configDependencies == nil {
		sc.configDependencies = make(map[uint64]struct{})
	}

	for _, config := range dependencies {
		sc.configDependencies[config.HashCode()] = struct{}{}  // <-- Hash of ConfigKey stored
	}
}
```

The hash is computed from ConfigKey fields including Name and Namespace (see `pilot/pkg/model/config.go:60-69`).

### 5. Dependency Checking in DependsOnConfig

**File**: `pilot/pkg/model/sidecar.go:521-540`

```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
	if sc == nil {
		return true
	}
	// ... cluster-scoped config logic ...

	// This kind of config is unknown to sidecarScope.
	if _, f := sidecarScopeKnownConfigTypes[config.Kind]; !f {
		return true
	}

	_, exists := sc.configDependencies[config.HashCode()]  // <-- Hash lookup
	return exists
}
```

When the second DR is updated, its ConfigKey's hash is computed and looked up. If not found, this returns false.

### 6. xDS Push Filtering

**File**: `pilot/pkg/xds/proxy_dependencies.go:32-74`

When a config change event occurs:

```go
func ConfigAffectsProxy(req *model.PushRequest, proxy *model.Proxy) bool {
	if len(req.ConfigsUpdated) == 0 {
		return true  // No filter = all proxies affected
	}

	for config := range req.ConfigsUpdated {
		// ... proxy type filtering ...
		if affected && checkProxyDependencies(proxy, config) {
			return true
		}
	}
	return false  // No match = proxy not affected
}

func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
	switch proxy.Type {
	case model.SidecarProxy:
		if proxy.SidecarScope.DependsOnConfig(config) {  // <-- CRITICAL CHECK
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

**Critical flow**:
1. When second DR is updated, PushRequest is created with `ConfigsUpdated` containing the second DR's ConfigKey (e.g., `{Kind: DestinationRule, Name: "reviews-subsets", Namespace: "default"}`)
2. `ConfigAffectsProxy()` iterates through ConfigsUpdated and calls `checkProxyDependencies()`
3. `checkProxyDependencies()` calls `proxy.SidecarScope.DependsOnConfig(secondDRKey)`
4. Since only the first DR's ConfigKey is in `configDependencies`, this returns false
5. If all configs return false, `ConfigAffectsProxy()` returns false, and the proxy is NOT pushed

### 7. Event Handling and PushRequest Creation

**File**: `pilot/pkg/bootstrap/server.go:881-903`

```go
configHandler := func(prev config.Config, curr config.Config, event model.Event) {
	// ...
	pushReq := &model.PushRequest{
		Full: true,
		ConfigsUpdated: map[model.ConfigKey]struct{}{{
			Kind:      curr.GroupVersionKind,      // DestinationRule
			Name:      curr.Name,                  // e.g., "reviews-subsets"
			Namespace: curr.Namespace,             // e.g., "default"
		}: {}},
		Reason: []model.TriggerReason{model.ConfigUpdate},
	}
	s.XDSServer.ConfigUpdate(pushReq)
}
```

When the second DR is updated in the API server, this handler fires with the second DR's ConfigKey.

### 8. The Hidden Consolidation in PushContext

**File**: `pilot/pkg/model/push_context.go:1672-1768`

`SetDestinationRules()` is called during PushContext initialization:

```go
func (ps *PushContext) SetDestinationRules(configs []config.Config) {
	// ... sorting and initialization ...

	for i := range configs {
		rule := configs[i].Spec.(*networking.DestinationRule)
		// ...

		// Line 1716: Merge into namespace local pool
		ps.mergeDestinationRule(namespaceLocalDestRules[configs[i].Namespace], configs[i], exportToMap)

		// Line 1739: Merge into exported pool
		ps.mergeDestinationRule(exportedDestRulesByNamespace[configs[i].Namespace], configs[i], exportToMap)
	}

	// Line 1764-1767: Store consolidated index
	ps.destinationRuleIndex.namespaceLocal = namespaceLocalDestRules
	ps.destinationRuleIndex.exportedByNamespace = exportedDestRulesByNamespace
	// ...
}
```

The merged results are stored in `destinationRuleIndex`. When `destinationRule()` is called later (lines 990-1066), it returns the consolidated list, masking the fact that multiple original DRs contributed to it.

---

## Affected Components

1. **pilot/pkg/model/destination_rule.go**
   - `mergeDestinationRule()` function (lines 38-109)
   - Only first DR's metadata survives consolidation

2. **pilot/pkg/model/push_context.go**
   - `SetDestinationRules()` (lines 1672-1768)
   - `destinationRule()` (lines 990-1066)
   - `consolidatedDestRules` type definition (lines 251-256)
   - `destinationRuleIndex` type definition (lines 111-130)

3. **pilot/pkg/model/sidecar.go**
   - `DefaultSidecarScopeForNamespace()` (lines 173-251)
   - `ConvertToSidecarScope()` (lines 254-431)
   - `DependsOnConfig()` (lines 523-540)
   - `AddConfigDependencies()` (lines 542-555)
   - `configDependencies` field in `SidecarScope` (line 110)

4. **pilot/pkg/xds/proxy_dependencies.go**
   - `ConfigAffectsProxy()` (lines 32-58)
   - `checkProxyDependencies()` (lines 60-74)

5. **pilot/pkg/bootstrap/server.go**
   - `initRegistryEventHandlers()` (lines 863-915)
   - Config change event handler (lines 881-903)
   - Populates `ConfigsUpdated` in PushRequest

6. **pilot/pkg/config/config.go**
   - `ConfigKey` type (lines 54-58)
   - `HashCode()` method (lines 60-69)

---

## Causal Chain

1. **Symptom**: Operator updates DR-2 (reviews-subsets) adding a v3 subset, but Envoy sidecar does not receive updated xDS config

2. **→ Intermediate Hop 1**: When DR-2 is updated in the Kubernetes API server, config controller in `bootstrap/server.go:881` detects the change and creates a PushRequest with ConfigsUpdated containing DR-2's ConfigKey: `{Kind: DestinationRule, Name: "reviews-subsets", Namespace: "default"}`

3. **→ Intermediate Hop 2**: The xDS layer calls `ConfigAffectsProxy()` in `proxy_dependencies.go:32` to determine if the proxy needs a push, passing the DR-2 ConfigKey

4. **→ Intermediate Hop 3**: `checkProxyDependencies()` at line 60 calls `proxy.SidecarScope.DependsOnConfig(dr2_configkey)`, which checks if DR-2's ConfigKey is in the sidecar's `configDependencies` map

5. **→ Intermediate Hop 4**: During initial SidecarScope construction (in `sidecar.go:219-227` or `410-416`), the dependency registration loop iterates over merged destination rules returned by `ps.destinationRule()`, which has consolidated DR-1 and DR-2 into a single entry

6. **→ Intermediate Hop 5**: The merged entry in `consolidatedDestRules.destRules[hostname]` contains only ONE `config.Config` object with the Name="reviews-traffic-policy" and Namespace="default" (the first DR that was stored before merging)

7. **→ Root Cause**: In `destination_rule.go:38-109`, when `mergeDestinationRule()` was called for DR-2 after DR-1 was already in the consolidated list, it modified the first DR in-place (line 66) and appended DR-2's subsets to it (lines 77-87), but did NOT add DR-2 as a separate entry in the list (line 101). Consequently, only DR-1's metadata survives in the consolidated structure, and only `ConfigKey{Name: "reviews-traffic-policy"}` is registered in `configDependencies`, NOT `ConfigKey{Name: "reviews-subsets"}`

8. **Result**: When DR-2 is updated, `DependsOnConfig()` is called with `ConfigKey{Name: "reviews-subsets"}`, which was never registered, so the hash lookup at `sidecar.go:538` fails, returns false, and the proxy is excluded from the push

9. **Final Outcome**: Envoy sidecar does not receive xDS update and continues serving stale cluster and route configuration; operator must restart the pod to trigger a full rebuild

---

## Recommendation

### Root Cause Fix
The fundamental issue is the loss of identity metadata during DestinationRule consolidation. There are several potential fix strategies:

**Option 1 (Recommended): Track All Contributing DRs**
- Modify `consolidatedDestRules` to maintain a list of all contributing DR metadata, not just the consolidated spec
- When registering dependencies in SidecarScope, iterate over ALL contributing DRs and register each one's ConfigKey
- This ensures that updates to ANY contributing DR trigger a push

**Option 2: Hash-based Dependency Tracking**
- Instead of registering ConfigKey by (Name, Namespace), register a hash of the resolved host
- When a DestinationRule for that host is updated, check if it matches the host before filtering
- Less precise but avoids metadata loss

**Option 3: Separate Registry for Merged Config Origins**
- Maintain a separate map `mergedConfigOrigins: map[host.Name][]ConfigKey` that tracks which original DRs were merged to create each consolidated entry
- When pushing, expand the ConfigsUpdated set to include all origins before calling `DependsOnConfig()`

### Diagnostic Steps
1. Enable debug logging in `sidecar.go:AddConfigDependencies()` to log all registered ConfigKeys
2. Compare registered ConfigKeys with actual DestinationRules in the cluster
3. Verify that after merging, the consolidated list contains entries for BOTH contributing DRs (or at least metadata for both)
4. Add validation in `mergeDestinationRule()` to warn if consolidation results in loss of metadata

### Test Cases to Add
1. Create two DRs for the same host (one with subsets, one with traffic policy)
2. Update the DR that was "lost" in consolidation
3. Verify that the sidecar receives an xDS push
4. Check that `configDependencies` contains ConfigKeys for both DRs

### Longer-term Improvements
- Consider deprecating the implicit merging behavior and requiring users to define a single DR per host with all subsets and policies
- Document the consolidation semantics more clearly in API and implementation comments
- Add metrics to track how many DRs are consolidated per host to aid observability
