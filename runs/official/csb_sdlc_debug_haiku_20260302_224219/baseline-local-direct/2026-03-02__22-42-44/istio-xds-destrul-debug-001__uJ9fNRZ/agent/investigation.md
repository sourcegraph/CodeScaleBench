# Investigation Report: Stale Envoy Route Configuration After DestinationRule Update in Istio

## Summary

When multiple DestinationRules (DRs) without workload selectors are defined for the same host, the Istio control plane merges them into a single config object, but only the first DR's Name and Namespace metadata is retained. When a contributing DR (not the first one) is subsequently updated, the xDS push is incorrectly skipped because the updated DR's identity was lost during merging and never registered as a config dependency. The proxy sidecar continues serving stale cluster and route configuration.

## Root Cause

The root cause is a three-stage failure across the DestinationRule merge pipeline and the xDS push filtering system:

### Stage 1: Metadata Loss During Merging (destination_rule.go)

In `/workspace/pilot/pkg/model/destination_rule.go`, the `mergeDestinationRule()` function (lines 38-109) implements an **in-place merge** strategy that discards non-first DR metadata:

1. When the first DR for a host is processed, it's appended to the `consolidatedDestRules.destRules` map (line 107):
   ```go
   p.destRules[resolvedHost] = append(p.destRules[resolvedHost], &destRuleConfig)
   ```
   Result: `destRules[host] = [&DR1_config]`

2. When a second DR without workload selectors arrives for the same host:
   - Lines 46, 59: The function detects that both DRs can be merged (no conflicting workload selectors)
   - Line 60: Sets `addRuleToProcessedDestRules = false` — indicating the new DR should NOT become a separate list entry
   - Line 65-66: Deep copies the existing DR-1 and **replaces it in place** with the merged version:
     ```go
     copied := mdr.DeepCopy()
     p.destRules[resolvedHost][i] = &copied
     ```
   - Lines 77-93: Merges the second DR's subsets and traffic policies into the copied config
   - Line 101-103: Since `addRuleToProcessedDestRules == false`, does NOT append the second DR
   - Result: `destRules[host]` still contains only **one config object** (DR-1 with merged subsets)

**Critical Issue**: The second DR's identity (`Name: "reviews-subsets"`, `Namespace: "default"`) is completely lost. The merged config object only carries DR-1's metadata.

### Stage 2: Incomplete Dependency Registration (sidecar.go)

In `/workspace/pilot/pkg/model/sidecar.go`, the `DefaultSidecarScopeForNamespace()` function (lines 173-251) builds the SidecarScope's config dependencies:

1. Line 209: Calls `ps.destinationRule(configNamespace, s)` which returns the merged destination rules for a service
2. Lines 219-227: Iterates over the returned list and registers each config as a dependency:
   ```go
   for _, drList := range out.destinationRules {
       for _, dr := range drList {
           out.AddConfigDependencies(ConfigKey{
               Kind:      gvk.DestinationRule,
               Name:      dr.Name,         // Only DR-1's Name
               Namespace: dr.Namespace,    // Only DR-1's Namespace
           })
       }
   }
   ```

**Critical Gap**: Since `destinationRules[host]` contains only the merged config with DR-1's identity, only DR-1's `ConfigKey` is registered. DR-2's `ConfigKey` is never added to the `SidecarScope.configDependencies` map.

The `AddConfigDependencies()` method (lines 544-555) stores these keys by their hash:
```go
func (sc *SidecarScope) AddConfigDependencies(dependencies ...ConfigKey) {
    for _, config := range dependencies {
        sc.configDependencies[config.HashCode()] = struct{}{}  // Hash includes Name, Namespace, Kind, Group, Version
    }
}
```

### Stage 3: Push Filter Returns False for Missing Dependency (proxy_dependencies.go + sidecar.go)

In `/workspace/pilot/pkg/xds/proxy_dependencies.go`, when a DR update occurs:

1. Lines 32-58: The `ConfigAffectsProxy()` function is called with the updated config
2. Line 52: For each updated config, calls `checkProxyDependencies(proxy, config)`
3. Lines 60-68 in proxy_dependencies.go: For SidecarProxy types, calls:
   ```go
   if proxy.SidecarScope.DependsOnConfig(config) {
       return true
   }
   ```

Back in `/workspace/pilot/pkg/model/sidecar.go` (lines 521-540), the `DependsOnConfig()` method checks:
```go
func (sc *SidecarScope) DependsOnConfig(config ConfigKey) bool {
    // ...
    _, exists := sc.configDependencies[config.HashCode()]
    return exists
}
```

**The Failure Path**: When DR-2 is updated:
- A PushRequest is created with `ConfigsUpdated = {ConfigKey{Name: "reviews-subsets", Namespace: "default"}}`
- The xDS system calls `ConfigAffectsProxy()` with this ConfigKey
- `checkProxyDependencies()` calls `DependsOnConfig(ConfigKey{Name: "reviews-subsets", ...})`
- The `configDependencies` map only contains the hash for `ConfigKey{Name: "reviews-traffic-policy", ...}`
- Since the hashes don't match (different Name), `DependsOnConfig()` returns `false`
- The proxy is not included in the push, and the Envoy sidecar never receives the updated CDS/RDS config

### Stage 4: PushContext Obscures the Merge Origin (push_context.go)

In `/workspace/pilot/pkg/model/push_context.go`, the `destinationRule()` method (lines 990-1067) returns destination rules from the `destinationRuleIndex`, which stores only the merged configs:

1. Lines 1006-1010: Queries `ps.destinationRuleIndex.namespaceLocal[proxyNameSpace].destRules[hostname]`
2. Returns the list stored in `consolidatedDestRules.destRules` — which has already lost the second DR's metadata
3. No tracking of which original DRs contributed to the merge

The structure definition (lines 251-256) of `consolidatedDestRules` shows it's designed to store multiple configs per hostname:
```go
type consolidatedDestRules struct {
    exportTo   map[host.Name]map[visibility.Instance]bool
    destRules  map[host.Name][]*config.Config  // Should be multiple, but ends up being one after merge
}
```

However, the merge logic ensures only one config per hostname is stored when multiple DRs without workload selectors exist for the same host.

## Evidence

### Code References with Line Numbers

**File: `/workspace/pilot/pkg/model/destination_rule.go`**
- Line 38: Function signature: `func (ps *PushContext) mergeDestinationRule(p *consolidatedDestRules, destRuleConfig config.Config, exportToMap map[visibility.Instance]bool)`
- Line 41-60: Merge detection logic checking for workload selectors
- Line 65-66: In-place replacement of existing config: `p.destRules[resolvedHost][i] = &copied`
- Line 77-93: Merge of subsets and traffic policies from second DR into first DR's config
- Line 101-103: Conditional append that skips adding the second DR when `addRuleToProcessedDestRules == false`

**File: `/workspace/pilot/pkg/model/sidecar.go`**
- Line 209: `if dr := ps.destinationRule(configNamespace, s); dr != nil { out.destinationRules[s.Hostname] = dr }`
- Line 219-227: Dependency registration loop that only iterates over the merged configs
- Line 221-225: AddConfigDependencies call that registers only the surviving config's Name/Namespace
- Line 538: Hash lookup in configDependencies: `_, exists := sc.configDependencies[config.HashCode()]`
- Line 553: Hash insertion during AddConfigDependencies: `sc.configDependencies[config.HashCode()] = struct{}{}`

**File: `/workspace/pilot/pkg/xds/proxy_dependencies.go`**
- Line 38-54: Loop through ConfigsUpdated and check each config against proxy
- Line 52: Call to `checkProxyDependencies(proxy, config)`
- Line 64: Call to `proxy.SidecarScope.DependsOnConfig(config)` for SidecarProxy types
- Line 65-68: Fallback to PrevSidecarScope if current scope doesn't match

**File: `/workspace/pilot/pkg/model/push_context.go`**
- Line 251-256: `consolidatedDestRules` struct definition with `destRules map[host.Name][]*config.Config`
- Line 1006-1010: `destinationRule()` method returning the merged config from the index
- Line 1716, 1739, 1742: Calls to `mergeDestinationRule()` during index initialization

**File: `/workspace/pilot/pkg/model/config.go`**
- Line 54-58: `ConfigKey` struct with Name, Namespace, Kind fields
- Line 60-70: `HashCode()` method that uses Name, Namespace, and Kind in the hash calculation

### Scenario Walkthrough

Given two DRs for `reviews.default.svc.cluster.local`:
- `DR-1` (reviews-traffic-policy): Defines `trafficPolicy.connectionPool`
- `DR-2` (reviews-subsets): Defines `subsets[v1, v2]`

**During Initial Push Context Build (SetDestinationRules)**:
1. Both DRs are processed via `mergeDestinationRule()` in `push_context.go:1716`
2. After processing both, the `destinationRuleIndex.namespaceLocal["default"].destRules["reviews.default.svc.cluster.local"]` contains:
   - A single `config.Config` object with:
     - `Name: "reviews-traffic-policy"` (from DR-1)
     - `Namespace: "default"` (from DR-1)
     - Spec contains merged subsets from both DRs and traffic policy

**During Sidecar Scope Initialization**:
1. `DefaultSidecarScopeForNamespace()` calls `ps.destinationRule("default", reviewsService)`
2. Gets back `[&merged_config_with_DR1_identity]`
3. Registers only: `ConfigKey{Name: "reviews-traffic-policy", Namespace: "default"}`

**When DR-2 is Updated**:
1. Config change event triggers with `ConfigKey{Name: "reviews-subsets", Namespace: "default"}`
2. `ConfigAffectsProxy()` → `checkProxyDependencies()` → `DependsOnConfig()`
3. Looks for hash of `ConfigKey{Name: "reviews-subsets", ...}` in `configDependencies`
4. Hash doesn't match (different Name), returns `false`
5. No push to proxy, Envoy sidecar never learns of subset changes

## Affected Components

1. **`pilot/pkg/model/destination_rule.go`** — Merge pipeline that loses metadata
2. **`pilot/pkg/model/sidecar.go`** — Dependency registration that only captures surviving metadata
3. **`pilot/pkg/xds/proxy_dependencies.go`** — Push filter that uses incomplete dependency map
4. **`pilot/pkg/model/push_context.go`** — Index storage that obscures merge history
5. **`pilot/pkg/model/config.go`** — ConfigKey hash mechanism (working as designed, but vulnerable to metadata loss)

## Causal Chain

1. **Symptom**: Envoy sidecar receives no update when DR-2 is modified; `/debug/config_dump` shows stale configuration
2. → **Intermediate 1**: `ConfigAffectsProxy()` returns `false` for the modified DR-2
3. → **Intermediate 2**: `checkProxyDependencies()` delegates to `DependsOnConfig()` which returns `false`
4. → **Intermediate 3**: `SidecarScope.configDependencies` map does not contain DR-2's ConfigKey hash
5. → **Intermediate 4**: During Sidecar scope initialization, only DR-1's ConfigKey was registered (line 223-225 of sidecar.go)
6. → **Intermediate 5**: The returned destination rules list contains only the merged config with DR-1's identity (from `ps.destinationRule()`)
7. → **Intermediate 6**: During merge in `destination_rule.go`, the merged config was stored at the position of DR-1 (line 66), and DR-2 was not appended (line 101-103)
8. → **Root Cause**: The `mergeDestinationRule()` function in `destination_rule.go` discards non-first DR metadata when performing in-place merging (lines 60-103)

## Recommendation

### Fix Strategy

The root cause is that the current merge strategy preserves only one DR's metadata while combining all their spec properties. Two possible fixes:

**Option A (Metadata Tracking)**: Modify `consolidatedDestRules` or the merged config object to track all contributing DRs' identities. When a DR is updated, check if it contributed to any merged config and regenerate that merged config.

**Option B (Preserving Separate Entries)**: Modify `mergeDestinationRule()` to preserve both configs in the `destRules` slice even after merging their specs. When a sidecar needs a destination rule for a hostname, concatenate the subsets and apply traffic policies from all contributing DRs rather than storing a pre-merged single config.

**Option C (Dual Index)**: Maintain both the merged config storage (for consumption by generators) and a reverse index mapping merged configs to contributing DRs. When a DR is updated, regenerate affected merged configs and notify affected proxies.

### Diagnostic Steps

To confirm the bug in a running Istio installation:

1. Apply two DestinationRules for the same host without workload selectors:
   ```bash
   kubectl apply -f dr-traffic-policy.yaml
   kubectl apply -f dr-subsets.yaml
   ```

2. Check the Istio control plane's internal state (requires access to Pilot container):
   ```bash
   curl -s http://localhost:8080/debug/configz | jq '.destinationRules' | grep -A 20 'reviews.default'
   ```
   Verify that the merged config shows only one Name/Namespace in its metadata.

3. Modify the second DR:
   ```bash
   kubectl patch destinationrule dr-subsets -p '{"spec":{"subsets":[{"name":"v3","labels":{"version":"v3"}}]}}'
   ```

4. Check the sidecar's xDS config dump:
   ```bash
   kubectl exec <sidecar-pod> -c istio-proxy -- curl -s localhost:15000/config_dump | grep -A 50 'cluster_name.*reviews'
   ```
   The configuration should remain stale (old subset list).

5. Restart the pod to verify it was a push issue, not a stale startup config:
   ```bash
   kubectl rollout restart deployment/<app>
   kubectl exec <new-sidecar-pod> -c istio-proxy -- curl -s localhost:15000/config_dump | grep -A 50 'cluster_name.*reviews'
   ```
   The new pod should show the updated configuration, confirming the bug is in the push mechanism, not in initial config generation.

6. Monitor Pilot logs for the update:
   ```bash
   kubectl logs -l app=istiod -c discovery | grep -i "destinationrule.*reviews-subsets"
   ```
   You should see the config change event logged, but verify that `ConfigAffectsProxy` returns `false` for affected sidecars.

### Implementation Priority

- **High**: This affects all deployments with multiple DestinationRules per host without workload selectors
- **Scope**: Impacts traffic policies, subset definitions, and TLS settings that are split across multiple DRs
- **Workaround**: Combine all DestinationRules for a host into a single CR or use workload selectors to prevent merging
