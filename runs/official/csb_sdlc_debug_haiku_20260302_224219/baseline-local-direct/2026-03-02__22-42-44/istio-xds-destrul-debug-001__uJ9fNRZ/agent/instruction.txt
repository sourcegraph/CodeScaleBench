# Investigation: Stale Envoy Route Configuration After DestinationRule Update in Istio

**Repository:** istio/istio
**Task Type:** Deep Causal Chain (investigation only — no code fixes)

## Scenario

An Istio service mesh operator reports that updating a DestinationRule in their cluster **silently fails to propagate** to Envoy sidecars. Specifically, when they have multiple DestinationRules for the same host (e.g., one defining subsets, another defining traffic policy), updating one of them does not trigger an xDS push — the Envoy sidecar continues serving the **stale** cluster and route configuration.

The operator has two DestinationRules for `reviews.default.svc.cluster.local`:

**DR-1 (traffic policy):**
```yaml
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
      http:
        h2UpgradePolicy: UPGRADE
```

**DR-2 (subsets):**
```yaml
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
    - name: v2
      labels:
        version: v2
```

When the operator updates `reviews-subsets` (e.g., adding a `v3` subset), the Envoy sidecar does **not** receive updated CDS/RDS config. Only restarting the pod picks up the change. Updating `reviews-traffic-policy` also has no effect.

Istio debug endpoint `GET /debug/config_dump` on the sidecar shows the old configuration even after the DestinationRule has been updated in the Kubernetes API server.

## Your Task

Investigate the root cause of why updating a merged DestinationRule fails to trigger an xDS push, and produce a report at `/logs/agent/investigation.md`.

Your report MUST cover:

1. **How Istio merges multiple DestinationRules for the same host** — specifically the `mergeDestinationRule()` function in `pilot/pkg/model/destination_rule.go` and how it combines subsets and traffic policies from multiple DRs into a single merged config
2. **How the merged DestinationRule loses identity metadata** — when two DRs are merged, only one DR's `config.Config` metadata (name/namespace) survives in the `consolidatedDestRules` structure. The metadata of contributing DRs is lost.
3. **How SidecarScope builds config dependencies** — the `AddConfigDependencies()` calls in `pilot/pkg/model/sidecar.go` that register which config resources a proxy depends on. Specifically, how `DefaultSidecarScopeForNamespace()` and `ConvertToSidecarScope()` iterate over `destinationRules` and add `ConfigKey{Kind: DestinationRule, Name: dr.Name, Namespace: dr.Namespace}` for each DR
4. **The specific gap: only one DR's ConfigKey is registered** — because the merged DR has only one name/namespace, `AddConfigDependencies` registers only that one DR. The other contributing DR(s) are not tracked.
5. **How the xDS push filter uses DependsOnConfig** — when a config change event occurs, `pilot/pkg/xds/` calls `SidecarScope.DependsOnConfig(configKey)` to decide if the proxy needs a push. If the updated DR is the one whose metadata was lost during merging, `DependsOnConfig` returns `false` and the push is **incorrectly skipped**.
6. **The relationship between PushContext.destinationRule() and the merge pipeline** — how `pilot/pkg/model/push_context.go` stores the `destinationRuleIndex` and how `destinationRule()` returns the merged config, obscuring the fact that multiple DRs contributed to it

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding>

## Root Cause
<Specific file, function, and mechanism>

## Evidence
<Code references with file paths and line numbers>

## Affected Components
<List of packages/modules impacted>

## Causal Chain
<Ordered list: symptom → intermediate hops → root cause>

## Recommendation
<Fix strategy and diagnostic steps>
```

## Constraints

- Do NOT write any code fixes
- Do NOT modify any source files
- Your job is investigation and analysis only
- The causal chain spans at least 4 packages: `pilot/pkg/model/`, `pilot/pkg/xds/`, `pilot/pkg/networking/core/`, and `pilot/pkg/config/`
- Focus on how the DestinationRule merging in `destination_rule.go` interacts with dependency tracking in `sidecar.go` and push filtering in the xDS layer
