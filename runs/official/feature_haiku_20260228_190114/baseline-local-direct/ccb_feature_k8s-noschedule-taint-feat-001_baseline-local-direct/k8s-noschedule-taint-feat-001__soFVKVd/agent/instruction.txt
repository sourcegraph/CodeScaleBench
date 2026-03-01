# [Kubernetes] Add NoScheduleNoTraffic Taint Effect

**Repository:** kubernetes/kubernetes  
**Difficulty:** HARD  
**Category:** big_code_feature
**Task Type:** Feature Implementation - Large Codebase

**Reference:** [Trevor's Big Code Research](../../../docs/TREVOR_RESEARCH_DEC2025.md#2-kubernetes-noschedulenotraffic-taint-effect)

## Description

Implement a new Node taint effect called `NoScheduleNoTraffic` that:
1. **Prevents new pods from being scheduled** (like `NoSchedule`)
2. **Removes the node from Service EndpointSlices** (affects traffic routing)
3. **Does NOT evict existing pods** (unlike `NoExecute`)

This is a distinct effect from existing `NoSchedule` (which doesn't affect traffic) and `NoExecute` (which evicts pods).

## Task

This task requires implementing code changes to add `NoScheduleNoTraffic` support.

### Required Implementation

Address implementation concerns in these areas:

1. **Taint Effect Constants & Enums**:
   - Find where taint effects (`NoSchedule`, `NoExecute`, etc.) are defined as constants
   - Add `NoScheduleNoTraffic` alongside them

2. **Pod Admission Logic**:
   - Find the scheduler/admission controller that checks taint effects
   - Add logic to reject pods on nodes with `NoScheduleNoTraffic` taint
   - Must handle toleration matching for the new effect

3. **Endpoint Slice Update Logic**:
   - Find where service endpoints are updated based on taint effects
   - Add logic to exclude nodes with `NoScheduleNoTraffic` from EndpointSlices
   - Ensure traffic doesn't route to tainted nodes

4. **Node Controller Logic**:
   - Verify taint effect handling in node lifecycle
   - Ensure `NoScheduleNoTraffic` doesn't trigger pod eviction (unlike `NoExecute`)

5. **Tests & Validation**:
   - Add test cases for the new taint effect
   - Verify scheduling is blocked
   - Verify traffic is redirected away from tainted nodes
   - Verify pods are NOT evicted

### Implementation Steps

1. **Understand taint effect architecture**:
   - Find all definitions of taint effects constants
   - Find where `NoSchedule` and `NoExecute` are used
   - Understand the tolerance matching algorithm
   - Find endpoint slice controller logic

2. **Implement the new effect**:
   - Add `NoScheduleNoTraffic` as a new taint effect constant
   - Update all scheduler/admission checks to handle the new effect
   - Modify endpoint slice controller to exclude nodes with the new effect
   - Add Go tests covering the new behavior

3. **Verify no regressions**:
   - Existing taint effects still work correctly
   - Scheduling tests pass
   - Endpoint controller tests pass
   - Node lifecycle tests pass

## Success Criteria

[x] New taint effect `NoScheduleNoTraffic` is defined and used throughout codebase  
[x] Pods cannot be scheduled on nodes with the taint (unless they have matching toleration)  
[x] Nodes with the taint are excluded from Service EndpointSlices  
[x] Existing pods on nodes with the taint are NOT evicted  
[x] All Kubernetes tests pass  
[x] Code follows Kubernetes conventions  

## Testing

```bash
make test
```

**Time Limit:** 15 minutes
**Estimated Context:** 15,000 tokens
