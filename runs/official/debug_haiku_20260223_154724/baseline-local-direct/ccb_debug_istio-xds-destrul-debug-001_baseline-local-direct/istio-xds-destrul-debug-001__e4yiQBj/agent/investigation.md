# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update

## Summary

When multiple DestinationRules target the same host, Istio's `mergeDestinationRule()` function consolidates them into a single merged configuration, but only preserves the identity (name/namespace) of the first DR. When the second DR is updated, the xDS push filter cannot find it in the SidecarScope's config dependencies, so the push is incorrectly skipped, leaving Envoy sidecars with stale route configuration.

## Root Cause

The root cause is a **metadata loss bug in the DestinationRule merging pipeline** combined with **incomplete dependency tracking in SidecarScope**:

1. **Location**: `pilot/pkg/model/destination_rule.go:38-109` (`mergeDestinationRule` function)
2. **Mechanism**: When two DestinationRules are merged for the same host, the function modifies the first DR in-place to include subsets and traffic policies from the second DR, but **never adds the second DR's `config.Config` object to the consolidated list**. The second DR's metadata (Name, Namespace) is lost.
3. **Impact**: The consolidated DestinationRule list contains only the first DR's config object, obscuring the fact that multiple DRs contributed to the final configuration.

## Evidence

### 1. Merging Logic in `destination_rule.go:38-109`

**File**: `pilot/pkg/model/destination_rule.go`

```go
func (ps *PushContext) mergeDestinationRule(p *consolidatedDestRules, destRuleConfig config.Config, exportToMap map[visibility.Instance]bool) {
	rule := destRuleConfig.Spec.(*networking.DestinationRule)
	resolvedHost := ResolveShortnameToFQDN(rule.Host, destRuleConfig.Meta)
	if mdrList, exists := p.destRules[resolvedHost]; exists {
		// Line 41-100: If a DR for this host already exists, iterate over existing rules
		for i, mdr := range mdrList {
			existingRule := mdr.Spec.(*networking.DestinationRule)
			// Lines 46-48: Check if selectors match
			bothWithoutSelector := rule.GetWorkloadSelector() == nil && existingRule.GetWorkloadSelector() == nil
			bothWithSelector := existingRule.GetWorkloadSelector() != nil && rule.GetWorkloadSelector() != nil
			selectorsMatch := labels.Instance(existingRule.GetWorkloadSelector().GetMatchLabels()).Equals(rule.GetWorkloadSelector().GetMatchLabels())

			if bothWithoutSelector || (rule.GetWorkloadSelector() != nil && selectorsMatch) {
				// Lines 59-61: If they should be merged, flag not to add this rule to the list
				addRuleToProcessedDestRules = false
			}

			// Lines 63-67: Deep copy existing rule and replace it
			copied := mdr.DeepCopy()
			p.destRules[resolvedHost][i] = &copied
			mergedRule := copied.Spec.(*networking.DestinationRule)

			// Lines 69-87: Merge subsets from new rule into copied existing rule
			for _, subset := range rule.Subsets {
				if _, ok := existingSubset[subset.Name]; !ok {
					mergedRule.Subsets = append(mergedRule.Subsets, subset)
				}
			}

			// Lines 89-93: Merge traffic policy if not already set
			if mergedRule.TrafficPolicy == nil && rule.TrafficPolicy != nil {
				mergedRule.TrafficPolicy = rule.TrafficPolicy
			}
		}
		// Lines 101-103: BUG - if addRuleToProcessedDestRules is false, do NOT append the new DR
		if addRuleToProcessedDestRules {
			p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
		}
		return
	}
}
```

**Critical Issue**: When `addRuleToProcessedDestRules = false` (lines 59-61), the incoming `destRuleConfig` (which is the second DR) is **never added** to `p.destRules[resolvedHost]`. Only the first DR remains in the list.

### 2. Consolidated Data Structure in `push_context.go:251-256`

**File**: `pilot/pkg/model/push_context.go`

```go
type consolidatedDestRules struct {
	// Map of dest rule host to the list of namespaces to which this destination rule has been exported to
	exportTo map[host.Name]map[visibility.Instance]bool
	// Map of dest rule host and the merged destination rules for that host
	destRules map[host.Name][]*config.Config
}
```

**Issue**: The `destRules` map stores a list of `*config.Config` objects per hostname. When multiple DRs are merged, only one `config.Config` object (the first one) remains in this list. The `config.Config` object contains metadata like `Name` and `Namespace`, which uniquely identifies each original DR.

### 3. Destination Rule Lookup in `push_context.go:990-1010`

**File**: `pilot/pkg/model/push_context.go`

```go
func (ps *PushContext) destinationRule(proxyNameSpace string, service *Service) []*config.Config {
	// ...
	// Line 1008-1010: Return the merged list from the index
	if ps.destinationRuleIndex.namespaceLocal[proxyNameSpace] != nil {
		if hostname, ok := MostSpecificHostMatch(service.Hostname,
			ps.destinationRuleIndex.namespaceLocal[proxyNameSpace].destRules,
		); ok {
			// Returns consolidated list - only contains merged DRs
			return ps.destinationRuleIndex.namespaceLocal[proxyNameSpace].destRules[hostname]
		}
	}
	// ...
}
```

**Issue**: This function returns the consolidated `[]*config.Config` list from the `destRuleIndex`. Because only the first DR's config object is in the list (due to the bug in `mergeDestinationRule`), the second DR's metadata is unavailable.

### 4. Dependency Tracking in `sidecar.go:219-227` (DefaultSidecarScopeForNamespace)

**File**: `pilot/pkg/model/sidecar.go`

```go
for _, drList := range out.destinationRules {
	for _, dr := range drList {
		out.AddConfigDependencies(ConfigKey{
			Kind:      gvk.DestinationRule,
			Name:      dr.Name,        // Only the first DR's name is tracked
			Namespace: dr.Namespace,
		})
	}
}
```

**Issue**: This loop iterates over `out.destinationRules` which was populated by `ps.destinationRule()` at line 209-211. Since that function returns only the merged DR (with the first DR's metadata), only that one DR's ConfigKey is added to `configDependencies`. The second DR's ConfigKey is never registered.

### 5. Same Issue in ConvertToSidecarScope at `sidecar.go:408-416`

**File**: `pilot/pkg/model/sidecar.go`

```go
if drList := ps.destinationRule(configNamespace, s); drList != nil {
	out.destinationRules[s.Hostname] = drList
	for _, dr := range drList {
		out.AddConfigDependencies(ConfigKey{
			Kind:      gvk.DestinationRule,
			Name:      dr.Name,        // Only the first DR's name is tracked
			Namespace: dr.Namespace,
		})
	}
}
```

**Issue**: Same as above - only the consolidated DR's metadata is available.

### 6. Config Dependency Structure in `sidecar.go:110`

**File**: `pilot/pkg/model/sidecar.go`

```go
type SidecarScope struct {
	// ...
	// Set of known configs this sidecar depends on.
	// This field will be used to determine the config/resource scope
	// which means which config changes will affect the proxies within this scope.
	configDependencies map[uint64]struct{}
	// ...
}
```

**Issue**: This map stores the hash codes of ConfigKeys that the sidecar depends on. When merging causes a DR's metadata to be lost, its ConfigKey cannot be added to this map.

### 7. Dependency Check in `sidecar.go:523-540` (DependsOnConfig)

**File**: `pilot/pkg/model/sidecar.go`

```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
	if sc == nil {
		return true
	}

	// This kind of config will trigger a change if made in the root namespace or the same namespace
	if _, f := clusterScopedConfigTypes[config.Kind]; f {
		return config.Namespace == sc.RootNamespace || config.Namespace == sc.Namespace
	}

	// This kind of config is unknown to sidecarScope.
	if _, f := sidecarScopeKnownConfigTypes[config.Kind]; !f {
		return true
	}

	_, exists := sc.configDependencies[config.HashCode()]
	return exists  // Returns false if the ConfigKey's hash is not in the map
}
```

**Issue**: When the second DR is updated, its ConfigKey is looked up in `configDependencies`. If the second DR was merged away and its metadata was lost, its ConfigKey hash is not in the map, so this function returns **false**, indicating the proxy does not depend on this config.

### 8. XDS Push Filter Decision in `xds/proxy_dependencies.go:60-74`

**File**: `pilot/pkg/xds/proxy_dependencies.go`

```go
func checkProxyDependencies(proxy *model.Proxy, config model.ConfigKey) bool {
	// Detailed config dependencies check.
	switch proxy.Type {
	case model.SidecarProxy:
		if proxy.SidecarScope.DependsOnConfig(config) {
			return true  // Push if the proxy depends on this config
		} else if proxy.PrevSidecarScope != nil && proxy.PrevSidecarScope.DependsOnConfig(config) {
			return true
		}
	default:
		// TODO We'll add the check for other proxy types later.
		return true
	}
	return false  // No push if DependsOnConfig returns false
}
```

**Issue**: When this function is called with the second DR's ConfigKey, `DependsOnConfig` returns false, so `checkProxyDependencies` returns false. This causes the xDS push to be skipped.

### 9. Push Event Decision in `xds/proxy_dependencies.go:32-58` (ConfigAffectsProxy)

**File**: `pilot/pkg/xds/proxy_dependencies.go`

```go
func ConfigAffectsProxy(req *model.PushRequest, proxy *model.Proxy) bool {
	// Empty changes means "all" to get a backward compatibility.
	if len(req.ConfigsUpdated) == 0 {
		return true
	}

	for config := range req.ConfigsUpdated {
		affected := true

		// Some configKinds only affect specific proxy types
		if kindAffectedTypes, f := configKindAffectedProxyTypes[config.Kind]; f {
			affected = false
			for _, t := range kindAffectedTypes {
				if t == proxy.Type {
					affected = true
					break
				}
			}
		}

		if affected && checkProxyDependencies(proxy, config) {
			return true  // Push if any config affects this proxy
		}
	}

	return false  // No push if no config affects this proxy
}
```

**Issue**: When an update to the second DR is received, `ConfigAffectsProxy` returns false because `checkProxyDependencies` returns false, so the xDS push is **incorrectly skipped**.

## Affected Components

1. **`pilot/pkg/model/destination_rule.go`**: The `mergeDestinationRule()` function that causes metadata loss
2. **`pilot/pkg/model/push_context.go`**: The `destinationRuleIndex` structure and `destinationRule()` function that return incomplete information
3. **`pilot/pkg/model/sidecar.go`**: The `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` functions that fail to track all contributing DRs; also `DependsOnConfig()` that relies on incomplete dependency tracking
4. **`pilot/pkg/xds/proxy_dependencies.go`**: The `ConfigAffectsProxy()` and `checkProxyDependencies()` functions that make push decisions based on incomplete dependency information
5. **`pilot/pkg/config/config.go`**: The `ConfigKey` structure and its `HashCode()` method used for dependency tracking

## Causal Chain

1. **Symptom**: Updating "reviews-subsets" DR does not trigger an xDS push to the Envoy sidecar
2. **Envoy state**: The sidecar continues to serve the configuration from before the update
3. **xDS discovery service skips push**: `ConfigAffectsProxy()` in `xds/proxy_dependencies.go:52` returns `false` for the updated DR
4. **Dependency check fails**: `checkProxyDependencies()` at line 64 calls `proxy.SidecarScope.DependsOnConfig(config)` which returns `false`
5. **Config not in dependencies**: `DependsOnConfig()` at line 538 of `sidecar.go` returns `false` because the second DR's ConfigKey hash is not in `sc.configDependencies`
6. **Incomplete dependency tracking**: The SidecarScope was built by iterating over destination rules returned by `ps.destinationRule()`, which only contains the merged DR
7. **Only first DR tracked**: At lines 219-227 of `sidecar.go`, only `out.AddConfigDependencies()` calls register the first DR's ConfigKey
8. **Merged list incomplete**: The destination rule list returned by `ps.destinationRule()` at line 1010 of `push_context.go` only contains the first DR's config object
9. **Second DR not appended**: In `mergeDestinationRule()` at lines 101-103 of `destination_rule.go`, when the second DR is merged with the first, `addRuleToProcessedDestRules` is set to `false`, so the second DR is never appended to the list
10. **Root cause**: The `mergeDestinationRule()` function modifies the first DR in-place but does not preserve the identity of the second DR in the consolidated list

## Recommendation

### Fix Strategy

The root fix requires modifying the DestinationRule merging and dependency tracking pipeline to preserve the identity of all contributing DRs:

1. **Option A - Track All Contributors** (Recommended):
   - Modify `consolidatedDestRules` to track not just the final merged config but also a list of all contributing DRs' metadata
   - Update `mergeDestinationRule()` to maintain a list of all original DR ConfigKeys that contributed to the merged result
   - Update `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` to add ConfigDependencies for all contributing DRs, not just the returned config
   - This requires changes to: `destination_rule.go`, `push_context.go` (consolidatedDestRules struct), and `sidecar.go`

2. **Option B - Don't Merge Metadata**:
   - Return all contributing DRs from `destinationRule()` instead of just the merged result
   - Each proxy would track dependencies on all individual DRs
   - This preserves per-DR identity at the cost of more memory usage and complexity
   - Would require changes to: `push_context.go` (destinationRule function) and impact all CDS/RDS code

3. **Option C - Preserve Second DR as Separate Entry**:
   - Modify `mergeDestinationRule()` to append the second DR's config to the list even when merging occurs
   - Track both the merged result and the original DR separately
   - This maintains backward compatibility while preserving identity

### Diagnostic Steps

To confirm this issue in a running cluster:

1. **Check SidecarScope dependencies**:
   ```bash
   kubectl port-forward -n istio-system <istiod-pod> 15014:15014
   curl http://localhost:15014/debug/sidecars/<proxy-name> | grep -A 20 configDependencies
   ```
   - Verify that only one DR's ConfigKey is listed for hosts with multiple DRs

2. **Check merged destination rules**:
   ```bash
   curl http://localhost:15014/debug/push_context | jq '.destinationRuleIndex.namespaceLocal[].destRules'
   ```
   - Verify that for each hostname, only one config.Config object is stored despite multiple DRs being defined

3. **Monitor push events**:
   - Enable debug logging in Istiod: `istioctl analyze`
   - Update a second DR and observe the logs
   - Verify that no push event is generated for affected sidecars

4. **Test with single DR**:
   - Temporarily delete one of the DRs for a host
   - Updates to the remaining DR should trigger pushes
   - This confirms the issue is specific to merged DRs

### Implementation Priority

**High Priority**: This affects any deployment with multiple DestinationRules targeting the same service, which is a common pattern for:
- Separating traffic policies from subset definitions
- Different exportTo scopes for the same service
- Workload selector-based DR overrides

The fix should be implemented in a way that maintains the merged behavior for performance while preserving the identity metadata for dependency tracking.
