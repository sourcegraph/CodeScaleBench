# Investigation Report: DRA AllocationMode API Change Impact Analysis

## Summary

Proposed change to allow `AllocationMode: All` allocation mode on multi-node resource pools will impact the scheduler's device allocation logic, validation layers, kubelet's device preparation, and requires careful consideration of pool constraints that currently enforce single-node allocation restrictions.

## Root Cause

Currently, the DRA (Dynamic Resource Allocation) structured allocator restricts `AllocationMode: All` allocations to devices on a single node through implicit constraints in the node selector creation logic. When allocating devices with `AllocationMode: All`, if any device is marked as node-local (has `nodeName` set in the ResourceSlice), the allocation immediately restricts the entire claim to that single node. This behavior prevents multi-node resource pools from providing all their devices to a single claim.

The proposed change would remove this implicit single-node restriction and allow `AllocationMode: All` to span multiple nodes within a resource pool, enabling more flexible device allocation patterns for multi-node device scenarios (e.g., distributed GPUs, multi-node storage arrays).

## Evidence

### 1. AllocationMode Type Definitions
**Files:**
- `pkg/apis/resource/types.go:1064-1070`
- `staging/src/k8s.io/api/resource/v1/types.go:1107-1115`
- `staging/src/k8s.io/api/resource/v1beta1/types.go:1114-1122`
- `staging/src/k8s.io/api/resource/v1beta2/types.go:1107-1115`

Constants defined: `DeviceAllocationModeExactCount` and `DeviceAllocationModeAll`

### 2. Core Allocator Logic - Node Selector Constraint
**File:** `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/stable/allocator_stable.go:1234-1290`

This is the critical constraint function:
```go
func (alloc *allocator) createNodeSelector(result []internalDeviceResult) (*v1.NodeSelector, error) {
    // Lines 1255-1267: When ANY device has nodeName set,
    // entire allocation is restricted to that single node
    if nodeName != nil {
        return &v1.NodeSelector{
            NodeSelectorTerms: []v1.NodeSelectorTerm{{
                MatchFields: []v1.NodeSelectorRequirement{{
                    Key:      "metadata.name",
                    Operator: v1.NodeSelectorOpIn,
                    Values:   []string{*nodeName},  // Single node only
                }},
            }},
        }, nil
    }
}
```

**Identical implementation in:**
- `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/incubating/allocator_incubating.go:1328-1337`
- `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/experimental/allocator_experimental.go:1533-1542`

### 3. AllocationMode All Processing Logic
**File:** `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/stable/allocator_stable.go:402-437`

The allocator iterates through ALL pools and collects devices:
```go
case resourceapi.DeviceAllocationModeAll:
    requestData.allDevices = make([]deviceWithID, 0, resourceapi.AllocationResultsMaxSize)
    for _, pool := range pools {
        if pool.IsIncomplete {
            return requestData, fmt.Errorf("claim %s, request %s: asks for all devices,
                but resource pool %s is currently being updated", ...)
        }
        for _, slice := range pool.Slices {
            // Collects devices from the slice and pools them
        }
    }
```

**Identical in:**
- `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/incubating/allocator_incubating.go:414-430`
- `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/experimental/allocator_experimental.go:506-522`

### 4. Validation of AllocationMode
**File:** `pkg/apis/resource/validation/validation.go:268-286`

Current validation ensures:
- `AllocationMode: All` has count == 0
- `AllocationMode: ExactCount` has count > 0

### 5. Test Case for Multi-Node Pool with AllocationMode All
**File:** `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/allocatortesting/allocator_testing.go:5093-5126`

Test case: `"allocation-mode-all-with-multi-host-resource-pool"` (lines 5093-5126)
- Creates a resource pool "pool1" with devices on two nodes (node1, node2)
- Requests AllocationMode: All
- **Expected result:** Only device1 from node1 is allocated (not device2 from node2)
- Demonstrates current single-node restriction

### 6. Pool Gathering Logic
**Files:**
- `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/stable/pools_stable.go:52-82`
- `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/incubating/pools_incubating.go:52-82`
- `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/experimental/pools_experimental.go:52-82`

Pool identification includes both driver name and pool name, supporting multi-node pools through ResourceSlices on multiple nodes with the same pool identifier.

### 7. Node Selector Usage in Scheduler Plugin
**File:** `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go:569-573, 909-916`

The scheduler uses the NodeSelector from allocation status to filter which nodes can satisfy the allocation:
```go
if nodeSelector := state.informationsForClaim[index].availableOnNodes;
    nodeSelector != nil && !nodeSelector.Match(node) {
    // Node doesn't match the allocation's node selector - pod cannot run here
}
```

## Affected Components

### **High Risk (Core Allocation Logic)**

1. **Allocator Implementations** (3 variants)
   - `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/stable/allocator_stable.go`
   - `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/incubating/allocator_incubating.go`
   - `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/experimental/allocator_experimental.go`
   - **Impact:** Core device selection logic; changes must maintain feature parity across all three implementations

2. **Scheduler DRA Plugin**
   - `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go`
   - **Impact:** Must properly handle multi-node allocations in scheduling decisions; performance implications for large multi-node pools

3. **Pool Gathering**
   - `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/*/pools_*.go`
   - **Impact:** Pool completeness checks must account for multi-node scenarios; incomplete pool detection becomes more critical

### **Medium Risk (Validation & API)**

4. **Resource Validation**
   - `pkg/apis/resource/validation/validation.go:268-286`
   - `pkg/registry/resource/resourceclaim/declarative_validation_test.go`
   - **Impact:** May need new validation rules to prevent unsupported multi-node allocation patterns

5. **Kubelet DRA Manager**
   - `pkg/kubelet/cm/dra/manager.go`
   - **Impact:** Must prepare resources from multiple nodes; NodePrepareResources RPC calls may span multiple nodes

6. **Scheduler Framework Integration**
   - `pkg/scheduler/framework/plugins/dynamicresources/dra_manager.go`
   - **Impact:** State management for allocations spanning multiple nodes

### **Low Risk (Test & Documentation)**

7. **Test Infrastructure**
   - `staging/src/k8s.io/dynamic-resource-allocation/structured/internal/allocatortesting/allocator_testing.go`
   - `test/e2e/dra/dra.go`
   - `test/integration/scheduler_perf/dra/`
   - **Impact:** New test cases required for multi-node AllocationMode All scenarios

8. **Feature Gates**
   - `pkg/features/kube_features.go:2056-2073`
   - **Impact:** No immediate changes; existing DRA feature gates still apply

## Scheduler Hot Paths Affected

### **PreFilter Phase**
- File: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go:PreFilter()`
- **Impact:** Validation that claims are allocated; minimal overhead expected

### **Filter Phase**
- File: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go:Filter()`
- **Impact:** Node selector matching for multi-node allocations; **PERFORMANCE SENSITIVE**
  - Current implementation: Single node match = fast lookup
  - Proposed: Multi-node allocation requires matching against NodeSelector with multiple terms/values
  - **Timeout protection:** `DRASchedulerFilterTimeout` feature gate (beta in 1.34, line 1182) mitigates runaway filtering

### **PostFilter Phase**
- File: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go:PostFilter()`
- **Impact:** Allocator invocation with structured parameters; complexity increases with multi-node considerations

## Downstream Consumers

### **Kubelet Device Plugin Integration**
- File: `pkg/kubelet/cm/dra/manager.go`
- **Change:** Node-local assumption breaks; must handle devices from multiple nodes
- **Implication:** ResourceClaims with multi-node allocations require coordinated device preparation across nodes

### **Device Plugin RPC Protocol**
- Files: `staging/src/k8s.io/kubelet/pkg/apis/dra/v1/api.proto` and `v1beta1/api.proto`
- **Current:** NodePrepareResources RPC called for each node independently
- **Change:** Pod may require devices from multiple nodes; kubelet must sequence NodePrepareResources calls correctly

### **Node Affinity & Scheduling**
- File: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go:570-573`
- **Change:** Multi-node NodeSelector parsing and matching becomes more complex
- **Risk:** Incorrect node selector handling could lead to pods scheduled on wrong nodes

## Risk Assessment

### **Critical Risks**

1. **Node Selector Correctness**
   - **Risk:** If `createNodeSelector()` returns incorrect multi-node selectors, pods will be scheduled on nodes that cannot provide allocated devices
   - **Mitigation:** Extensive unit tests in allocator_testing.go; integration tests verifying pod-to-device-to-node mapping

2. **Scheduler Performance Degradation**
   - **Risk:** Filter phase becomes slower when matching multi-node device allocations against nodes
   - **Mitigation:** Timeout protection via `DRASchedulerFilterTimeout` feature gate; performance testing in `test/integration/scheduler_perf/dra/`

3. **Pool Completeness Assumptions**
   - **Risk:** Allocators assume pools are complete before allocating; multi-node pools with incomplete nodes may cause incorrect "all" device counts
   - **Mitigation:** Stricter validation in pool gathering; existing incomplete pool detection in lines 412-414 already addresses this

### **High Risks**

4. **API Stability Across Versions**
   - **Risk:** Changing behavior of AllocationMode could affect existing claims if upgrade/downgrade occurs
   - **Mitigation:** Feature gate controlled; rolling upgrades recommended

5. **Kubelet-Scheduler Coordination**
   - **Risk:** If scheduler allocates devices across N nodes but kubelet only prepares on 1 node, pods fail
   - **Mitigation:** Pre-bind validation; clear error messages when preparation fails

### **Medium Risks**

6. **Backwards Compatibility with Device Plugins**
   - **Risk:** Old device drivers may not expect multi-node allocations
   - **Mitigation:** Feature gate guards the behavior; existing single-node allocation mode unchanged

## Testing Plan

### **Unit Tests**
1. Extend `allocator_testing.go:allocation-mode-all-with-multi-host-resource-pool` to verify correct multi-node device collection
2. Add tests for incomplete pool detection with multi-node pools
3. Add node selector creation tests for multi-node scenarios

### **Integration Tests**
1. Create multi-node DRA test cluster with devices on multiple nodes
2. Verify claims with AllocationMode:All span multiple nodes correctly
3. Verify pods are scheduled correctly based on multi-node device allocations
4. Verify kubelet successfully prepares devices from multiple nodes

### **Performance Tests**
1. Benchmark scheduler filter phase with large multi-node pools
2. Verify timeout protection is effective
3. Compare performance: single-node vs. multi-node allocations

### **End-to-End Tests**
1. Deploy pod requesting AllocationMode:All from multi-node pool
2. Verify device preparation on all allocated nodes
3. Verify container has access to all allocated devices

## Recommendation

**Proceed with caution under the following conditions:**

1. **Feature Gate:** Implement behind a new feature gate (`DRAMultiNodeAllocation` or similar) to control rollout
2. **Validation Enhancement:** Add validation rules in `validation.go` to catch known unsupported patterns early
3. **Test Coverage:** Require passing all unit, integration, and e2e tests before merging
4. **Performance Baseline:** Establish performance baseline before and after to detect regressions
5. **Phased Rollout:**
   - Alpha: Introduced with feature gate disabled by default
   - Beta: Enable by default, monitor field reports
   - Stable: Only after 1+ releases at beta with no critical issues

**Key Risks to Monitor Post-Deployment:**
- Scheduler filter latency increase
- Incorrect node selection causing pod failures
- Kubelet device preparation failures across nodes
- Device plugin compatibility issues

