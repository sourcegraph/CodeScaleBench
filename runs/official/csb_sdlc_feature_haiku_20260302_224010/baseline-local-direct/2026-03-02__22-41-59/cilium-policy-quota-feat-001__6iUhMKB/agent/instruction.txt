# Task: Implement PolicyQuotaController for Cilium

## Objective
Create a `PolicyQuotaController` in Cilium that enforces per-namespace limits on the
number of `CiliumNetworkPolicy` resources, preventing policy sprawl in multi-tenant clusters.

## Requirements

1. **Create `pkg/policy/quota/controller.go`** with:
   - `PolicyQuotaController` struct that watches CiliumNetworkPolicy resources
   - `NewPolicyQuotaController(client, informer, maxPerNamespace int)` constructor
   - `Run(ctx context.Context)` method implementing the controller loop
   - Per-namespace counting using a thread-safe map
   - `CheckQuota(namespace string) error` method that returns error if quota exceeded

2. **Create CRD type** `pkg/k8s/apis/cilium.io/v2/types_policy_quota.go`:
   - `CiliumPolicyQuota` struct with `Spec.MaxPoliciesPerNamespace` field
   - Follow existing Cilium CRD patterns (DeepCopy, runtime.Object)

3. **Create `pkg/policy/quota/controller_test.go`** with tests

4. **Follow Cilium patterns**:
   - Use `hive` dependency injection framework
   - Use `resource.Resource[T]` for watching K8s resources
   - Use `logfields` for structured logging

## Key Reference Files
- `pkg/policy/k8s/watcher.go` — CiliumNetworkPolicy watcher pattern
- `pkg/k8s/apis/cilium.io/v2/types_cnp.go` — CiliumNetworkPolicy CRD type
- `operator/pkg/ciliumenvoyconfig/` — controller using hive pattern
- `pkg/k8s/resource/resource.go` — resource watching framework

## Success Criteria
- PolicyQuotaController struct with Run method exists
- CheckQuota method performs namespace counting
- CiliumPolicyQuota CRD type exists
- Uses Cilium's hive/resource patterns
- Test file exists with test functions
