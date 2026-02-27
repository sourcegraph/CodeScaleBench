# Bug Analysis: Missing ResourceSlice Event Handler in Kubernetes Scheduler

## Files Examined

- `pkg/scheduler/framework/types.go` — Examined to identify GVK constants available in framework
- `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go` — Examined for EventsToRegister() implementation and Filter() method
- `pkg/scheduler/eventhandlers.go` — Examined to understand how event handlers are registered based on GVK list
- `pkg/scheduler/scheduler.go` — Examined for unionedGVKs() function that builds event handler map
- `pkg/scheduler/schedule_one.go` — Entry point to understand how scheduling failures trigger re-queueing

## Dependency Chain

1. **Symptom observed in**: `pkg/scheduler/schedule_one.go` line 112 (`ScheduleOne()` method)
   - When `schedulingCycle()` fails with `Unschedulable` status, `FailureHandler()` is called

2. **FailureHandler calls**: `pkg/scheduler/schedule_one.go` line 1068 (`handleSchedulingFailure()`)
   - This calls `AddUnschedulableIfNotPresent()` to move the pod to the unschedulable queue

3. **Queue re-evaluation triggered by**: `pkg/scheduler/eventhandlers.go` line 377 (`buildEvtResHandler()`)
   - When an event occurs, this calls `MoveAllToActiveOrBackoffQueue()` to re-evaluate unschedulable pods

4. **Events come from**: `pkg/scheduler/eventhandlers.go` line 395 (switch statement on `gvkMap`)
   - The switch statement registers event handlers only for GVKs present in `gvkMap`

5. **gvkMap built by**: `pkg/scheduler/scheduler.go` line 525 (`unionedGVKs()` function)
   - Collects all GVK events declared in `EventsToRegister()` methods of plugins

6. **Events declared in**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go` line 381 (`EventsToRegister()`)
   - Lists all events that should trigger pod re-evaluation when plugin rejects a pod

7. **Bug triggered by**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go` line 1139 (`nodeIsSuitable()`)
   - Filter method fails when checking if a node has suitable resources (returns Unschedulable)
   - This happens when no ResourceSlices exist yet

## Root Cause

**File**: `pkg/scheduler/framework/types.go` and `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go`

**Primary Issue (Line ~95 in types.go)**: ResourceSlice is not defined as a GVK constant in the framework

**Secondary Issue (Lines 381-412 in dynamicresources.go)**: ResourceSlice is not included in EventsToRegister()

**Tertiary Issue (Lines 395-492 in eventhandlers.go)**: No case for framework.ResourceSlice in the event handler registration switch statement

### Explanation

The bug is a **race condition in the event-driven queue re-evaluation system**:

1. **The Problem**: When a pod requesting DRA devices arrives before the DRA driver publishes ResourceSlice objects, the scheduler marks the pod as Unschedulable because:
   - The dynamicresources Filter plugin calls `nodeIsSuitable()`
   - This function queries the ResourceSlices to determine if a node has suitable resources
   - Since no ResourceSlices exist yet, the check fails and returns Unschedulable

2. **Why the Pod Gets Stuck**: When ResourceSlices are created/updated after the pod is unschedulable:
   - **ResourceSlice is not defined as a GVK constant** in `pkg/scheduler/framework/types.go`
   - Therefore, it cannot be used in the dynamicresources plugin's `EventsToRegister()` method
   - Without being registered, ResourceSlice events are never added to the `gvkMap`
   - Without being in `gvkMap`, the scheduler's event handler registration code in `eventhandlers.go` never creates event handlers for ResourceSlice changes
   - Without event handlers, ResourceSlice creation/update events are **silently dropped**
   - The unschedulable pod is never moved to the activeQ for re-evaluation

3. **Why This Happens**:
   - The DynamicResourceAllocation (DRA) feature was added without completing the event handler integration
   - ResourceSlice is a valid Kubernetes resource (resource.k8s.io/v1alpha2) but was never added to the framework's GVK constants
   - The plugin's EventsToRegister() can only register events for GVKs defined in the framework

### Data Flow Diagram

```
Pod arrives (no ResourceSlices yet)
    ↓
schedulingCycle() → SchedulePod()
    ↓
dynamicresources.Filter() checks nodeIsSuitable()
    ↓
nodeIsSuitable() queries ResourceSlices (finds none)
    ↓
Filter returns Unschedulable → Pod added to unschedulablePodPool
    ↓
DRA driver starts and creates ResourceSlice
    ↓
ResourceSlice event occurs ❌ BUT...
    ❌ No GVK defined for ResourceSlice in framework/types.go
    ❌ Therefore, not in dynamicresources.EventsToRegister()
    ❌ Therefore, not in gvkMap
    ❌ Therefore, no event handler registered
    ❌ Event is silently dropped
    ↓
Pod remains in unschedulablePodPool FOREVER ❌
```

## Proposed Fix

### 1. Add ResourceSlice GVK Constant

**File**: `pkg/scheduler/framework/types.go` (after line 95)

```diff
 	ResourceClaim           GVK = "ResourceClaim"
 	ResourceClass           GVK = "ResourceClass"
 	ResourceClaimParameters GVK = "ResourceClaimParameters"
 	ResourceClassParameters GVK = "ResourceClassParameters"
+	ResourceSlice           GVK = "ResourceSlice"

 	// WildCard is a special GVK to match all resources.
```

### 2. Add ResourceSlice to UnrollWildCardResource

**File**: `pkg/scheduler/framework/types.go` (line 177-193)

```diff
 func UnrollWildCardResource() []ClusterEventWithHint {
 	return []ClusterEventWithHint{
 		{Event: ClusterEvent{Resource: Pod, ActionType: All}},
 		{Event: ClusterEvent{Resource: Node, ActionType: All}},
 		{Event: ClusterEvent{Resource: PersistentVolume, ActionType: All}},
 		{Event: ClusterEvent{Resource: PersistentVolumeClaim, ActionType: All}},
 		{Event: ClusterEvent{Resource: CSINode, ActionType: All}},
 		{Event: ClusterEvent{Resource: CSIDriver, ActionType: All}},
 		{Event: ClusterEvent{Resource: CSIStorageCapacity, ActionType: All}},
 		{Event: ClusterEvent{Resource: StorageClass, ActionType: All}},
 		{Event: ClusterEvent{Resource: PodSchedulingContext, ActionType: All}},
 		{Event: ClusterEvent{Resource: ResourceClaim, ActionType: All}},
 		{Event: ClusterEvent{Resource: ResourceClass, ActionType: All}},
 		{Event: ClusterEvent{Resource: ResourceClaimParameters, ActionType: All}},
 		{Event: ClusterEvent{Resource: ResourceClassParameters, ActionType: All}},
+		{Event: ClusterEvent{Resource: ResourceSlice, ActionType: All}},
 	}
 }
```

### 3. Add ResourceSlice Event Handler Registration

**File**: `pkg/scheduler/eventhandlers.go` (after line 492)

```diff
 		case framework.ResourceClassParameters:
 			if utilfeature.DefaultFeatureGate.Enabled(features.DynamicResourceAllocation) {
 				if handlerRegistration, err = informerFactory.Resource().V1alpha2().ResourceClassParameters().Informer().AddEventHandler(
 					buildEvtResHandler(at, framework.ResourceClassParameters, "ResourceClassParameters"),
 				); err != nil {
 					return err
 				}
 				handlers = append(handlers, handlerRegistration)
 			}
+		case framework.ResourceSlice:
+			if utilfeature.DefaultFeatureGate.Enabled(features.DynamicResourceAllocation) {
+				if handlerRegistration, err = informerFactory.Resource().V1alpha2().ResourceSlices().Informer().AddEventHandler(
+					buildEvtResHandler(at, framework.ResourceSlice, "ResourceSlice"),
+				); err != nil {
+					return err
+				}
+				handlers = append(handlers, handlerRegistration)
+			}
 		case framework.StorageClass:
 			if at&framework.Add != 0 {
 				if handlerRegistration, err = informerFactory.Storage().V1().StorageClasses().Informer().AddEventHandler(
```

### 4. Add ResourceSlice Event Registration in Plugin

**File**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go` (after line 410)

```diff
 		// A pod might be waiting for a class to get created or modified.
 		{Event: framework.ClusterEvent{Resource: framework.ResourceClass, ActionType: framework.Add | framework.Update}},
+		// A pod requesting a resource may become schedulable when a ResourceSlice is created
+		// or updated with suitable resources for the node.
+		{Event: framework.ClusterEvent{Resource: framework.ResourceSlice, ActionType: framework.Add | framework.Update}, QueueingHintFn: pl.isSchedulableAfterResourceSliceChange},
 	}
 	return events
```

### 5. Add QueueingHintFn for ResourceSlice Changes

**File**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go` (after line 564 or at end of file before PostBind)

```go
// isSchedulableAfterResourceSliceChange checks whether a ResourceSlice change makes an unschedulable pod schedulable.
// A pod waiting for resource allocation may be schedulable once ResourceSlices are available with suitable resources.
func (pl *dynamicResources) isSchedulableAfterResourceSliceChange(logger klog.Logger, pod *v1.Pod, oldObj, newObj interface{}) (framework.QueueingHint, error) {
	// Check if this pod uses dynamic resources
	if err := pl.foreachPodResourceClaim(pod, nil); err != nil {
		// Pod doesn't use any ResourceClaims or cannot be scheduled
		return framework.QueueSkip, nil
	}

	// ResourceSlice changes might make this pod schedulable, so always queue it
	// (conservative approach since we can't easily determine which pod depends on which ResourceSlice)
	logger.V(6).Info("ResourceSlice was added or updated, requeuing pod that uses dynamic resources", "pod", klog.KObj(pod))
	return framework.Queue, nil
}
```

## Analysis

### Why This Bug Occurs

The Kubernetes scheduler uses an event-driven architecture where:

1. **Plugins declare events** via `EventsToRegister()` that should trigger re-evaluation of unschedulable pods
2. **The scheduler collects these events** and builds a map of GVK → ActionType
3. **Event handlers are registered** only for GVKs present in this map
4. **When events occur**, handlers call `MoveAllToActiveOrBackoffQueue()` to re-evaluate pods

The DRA feature was added but **ResourceSlice was never added to the framework's GVK constants**. This means:
- It cannot be declared in EventsToRegister()
- It is never added to the event handler registration map
- No handlers are registered for it
- Events are silently dropped

### Why This Matters

This is a **silent failure** — no errors are logged, but pods get permanently stuck:
- The scheduler correctly marks the pod as Unschedulable (because no ResourceSlices exist)
- The pod should be re-evaluated when ResourceSlices become available
- But the re-evaluation never happens because the event is never delivered
- The operator sees a pod stuck in Pending state indefinitely

### Severity

**Critical** — Pods requesting DRA resources will be permanently stuck if:
1. A pod is created before the DRA driver publishes ResourceSlices
2. This will work around the bug if pods are created after ResourceSlices exist
3. But race conditions make this unpredictable in production

### Fix Scope

The fix is minimal and consists of:
1. Adding one GVK constant
2. Adding one entry to the wildcard resource list
3. Adding one case in the event handler switch statement
4. Adding one event entry in the plugin's EventsToRegister()
5. Adding one optional QueueingHintFn for efficiency

The fix is **backward compatible** and introduces no breaking changes.
