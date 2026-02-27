# Kubernetes Scheduler Bug Analysis: Missing ResourceSlice Event Handler in DRA

## Files Examined

- **pkg/scheduler/schedule_one.go** — Entry point `ScheduleOne()` method showing pod scheduling cycle workflow
- **pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go** — DRA plugin implementation with `EventsToRegister()` function
- **pkg/scheduler/framework/plugins/dynamicresources/structuredparameters.go** — `newResourceModel()` function that loads ResourceSlices from lister
- **pkg/scheduler/framework/types.go** — GVK resource type definitions and event system constants

## Dependency Chain

1. **Symptom observed in**: `pkg/scheduler/schedule_one.go:ScheduleOne()` (line 66)
   - Pod gets stuck in `Unschedulable` state when scheduled before DRA driver starts

2. **Called from**: `schedule_one.go:schedulingCycle()` (line 139)
   - Calls `sched.SchedulePod()` which triggers framework plugins including DynamicResources

3. **Invokes**: `schedule_one.go:findNodesThatFitPod()` (line 442)
   - Runs PreFilter and Filter plugins on each node

4. **Calls DRA PreFilter**: `dynamicresources.go:PreFilter()` (line 834)
   - Loads resource model via `newResourceModel()` to check claim feasibility

5. **Resource model loaded**: `structuredparameters.go:newResourceModel()` (line 48)
   - Lists all ResourceSlices from lister at line 51: `resourceSliceLister.List(labels.Everything())`
   - If no ResourceSlices exist, resource availability data is missing

6. **Filter phase**: `dynamicresources.go:Filter()` (line 1101)
   - Calls `controller.nodeIsSuitable()` which uses the resource model from PreFilter
   - Returns Unschedulable if resources appear unavailable (because no ResourceSlices exist)

7. **Pod marked unschedulable**: `schedule_one.go:handleSchedulingFailure()` (line 1013)
   - Pod is added to unschedulable queue waiting for triggering events

8. **Bug triggered by**: `dynamicresources.go:EventsToRegister()` (line 381)
   - **Missing ResourceSlice event handler** ← ROOT CAUSE
   - When driver creates/updates ResourceSlices, no event is registered to re-queue the pod

## Root Cause

### Primary Issue: Missing GVK Definition
- **File**: `pkg/scheduler/framework/types.go`
- **Lines**: 68-106 (GVK constant definitions)
- **Issue**: `ResourceSlice` is not defined as a GVK constant

The GVK constants define the resource types that the event system understands. The following are defined:
```go
Pod                     GVK = "Pod"
Node                    GVK = "Node"
PersistentVolume        GVK = "PersistentVolume"
PersistentVolumeClaim   GVK = "PersistentVolumeClaim"
CSINode                 GVK = "storage.k8s.io/CSINode"
CSIDriver               GVK = "storage.k8s.io/CSIDriver"
CSIStorageCapacity      GVK = "storage.k8s.io/CSIStorageCapacity"
StorageClass            GVK = "storage.k8s.io/StorageClass"
PodSchedulingContext    GVK = "PodSchedulingContext"
ResourceClaim           GVK = "ResourceClaim"
ResourceClass           GVK = "ResourceClass"
ResourceClaimParameters GVK = "ResourceClaimParameters"
ResourceClassParameters GVK = "ResourceClassParameters"
WildCard                GVK = "*"
```

**Missing**: `ResourceSlice`

### Secondary Issue: Missing Event Registration
- **File**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go`
- **Function**: `EventsToRegister()` (line 381)
- **Issue**: No event listener for ResourceSlice Add/Update events

The function registers events for:
- ResourceClaimParameters (Add | Update)
- ResourceClassParameters (Add | Update)
- ResourceClaim (Add | Update)
- PodSchedulingContext (Add | Update)
- Node (Add | UpdateNodeLabel | UpdateNodeTaint)
- ResourceClass (Add | Update)

**Missing**: ResourceSlice (Add | Update)

## Why This Is a Bug

### The Race Condition

**Scenario 1: Driver starts first (works fine)**
1. Driver creates ResourceSlices advertising available resources
2. Pod is created requesting DRA devices
3. Scheduler runs, PreFilter calls `newResourceModel()` which loads ResourceSlices
4. Filter checks `nodeIsSuitable()` against the resource model and finds suitable nodes
5. Pod is scheduled successfully ✓

**Scenario 2: Pod created first (BROKEN)**
1. Pod is created requesting DRA devices and structured parameters
2. Scheduler runs PreFilter, calls `newResourceModel()`
3. No ResourceSlices exist yet (driver hasn't started)
4. Resource model is empty → no suitable nodes found
5. Pod gets marked as Unschedulable (added to unschedulable queue)
6. Driver starts and creates ResourceSlices
7. **STUCK**: ResourceSlice event is not registered, so:
   - No `EventsToRegister()` handler for ResourceSlice events
   - Pod is never re-queued from unschedulable queue
   - Pod remains in Unschedulable state forever ✗

### Why the Event System Fails

The Kubernetes scheduler uses a queue-based event-driven architecture:

1. When a pod becomes unschedulable, it enters the `unschedulablePods` queue
2. The scheduler waits for specific events (defined in `EventsToRegister()`) to move it back to the active or backoff queue
3. The event handler checks if the event might make the pod schedulable using the `QueueingHintFn`
4. If an event is not registered, the scheduler ignores it even if the informer processes it

**Without ResourceSlice events being registered**, the scheduler never knows to re-evaluate pods waiting for resource availability.

## Proposed Fix

### Fix 1: Add ResourceSlice to GVK Constants

**File**: `pkg/scheduler/framework/types.go`

**Location**: After line 96 (after ResourceClassParameters), add:

```diff
	ResourceClaim           GVK = "ResourceClaim"
	ResourceClass           GVK = "ResourceClass"
	ResourceClaimParameters GVK = "ResourceClaimParameters"
	ResourceClassParameters GVK = "ResourceClassParameters"
+	ResourceSlice           GVK = "ResourceSlice"

	// WildCard is a special GVK to match all resources.
```

Also add to `UnrollWildCardResource()` function:

```diff
	{Event: ClusterEvent{Resource: ResourceClaim, ActionType: All}},
	{Event: ClusterEvent{Resource: ResourceClass, ActionType: All}},
	{Event: ClusterEvent{Resource: ResourceClaimParameters, ActionType: All}},
	{Event: ClusterEvent{Resource: ResourceClassParameters, ActionType: All}},
+	{Event: ClusterEvent{Resource: ResourceSlice, ActionType: All}},
}
```

### Fix 2: Add Event Handler for ResourceSlice in DynamicResources Plugin

**File**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go`

**Location**: In `EventsToRegister()` function, add ResourceSlice event after the comment about resource availability (around line 411):

```diff
	// A pod might be waiting for a class to get created or modified.
	{Event: framework.ClusterEvent{Resource: framework.ResourceClass, ActionType: framework.Add | framework.Update}},
+	// ResourceSlices published by drivers advertise available resources.
+	// When a ResourceSlice is created or updated, a pod waiting for resource availability
+	// may become schedulable.
+	{Event: framework.ClusterEvent{Resource: framework.ResourceSlice, ActionType: framework.Add | framework.Update}, QueueingHintFn: pl.isSchedulableAfterResourceSliceChange},
}
return events
```

### Fix 3: Implement ResourceSlice Event Handler

**File**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go`

**Add new method** after `isSchedulableAfterClassParametersChange()` (around line 566):

```go
// isSchedulableAfterResourceSliceChange is invoked for add and update ResourceSlice events reported by
// an informer. ResourceSlices contain information about available resources from drivers.
// A pod waiting for resource availability in structured parameter claims may become
// schedulable when a ResourceSlice is created or updated.
// It errs on the side of letting a pod scheduling attempt happen.
func (pl *dynamicResources) isSchedulableAfterResourceSliceChange(logger klog.Logger, pod *v1.Pod, oldObj, newObj interface{}) (framework.QueueingHint, error) {
	newSlice, ok := newObj.(*resourcev1alpha2.ResourceSlice)
	if !ok {
		// This shouldn't happen.
		return framework.Queue, fmt.Errorf("unexpected object type in isSchedulableAfterResourceSliceChange: %T", newObj)
	}

	// Check if this pod has any claims with structured parameters.
	// If yes, the new/updated ResourceSlice might affect its scheduling.
	hasStructuredParams := false
	if err := pl.foreachPodResourceClaim(pod, func(_ string, claim *resourcev1alpha2.ResourceClaim) {
		if claim.Status.Allocation == nil &&
			(claim.Spec.AllocationMode == resourcev1alpha2.AllocationModeWaitForFirstConsumer ||
				claim.Spec.AllocationMode == resourcev1alpha2.AllocationModeImmediate) {
			// Check if this claim uses structured parameters
			class, err := pl.classLister.Get(claim.Spec.ResourceClassName)
			if err == nil && class.StructuredParameters != nil && *class.StructuredParameters {
				hasStructuredParams = true
			}
		}
	}); err != nil {
		// Pod is not schedulable for some reason.
		logger.V(4).Info("pod is not schedulable", "pod", klog.KObj(pod), "resourceslice", klog.KObj(newSlice), "reason", err.Error())
		return framework.QueueSkip, nil
	}

	if !hasStructuredParams {
		// This pod doesn't use structured parameters, so ResourceSlice changes don't affect it.
		logger.V(6).Info("pod does not use structured parameters", "pod", klog.KObj(pod), "resourceslice", klog.KObj(newSlice))
		return framework.QueueSkip, nil
	}

	// The ResourceSlice might provide resources needed by the pod's structured parameter claims.
	logger.V(4).Info("ResourceSlice created or updated, may affect pod scheduling", "pod", klog.KObj(pod), "resourceslice", klog.KObj(newSlice))
	return framework.Queue, nil
}
```

## Analysis

### Execution Path Summary

1. **ScheduleOne()** initiates pod scheduling (entry point)
2. **schedulingCycle()** calls SchedulePod() for the pod
3. **findNodesThatFitPod()** runs PreFilter and Filter plugins
4. **PreFilter()** loads resource model by listing all ResourceSlices
5. **Filter()** checks if pod can fit using the resource model
6. If no ResourceSlices exist → Filter returns Unschedulable
7. **handleSchedulingFailure()** puts pod in unschedulable queue
8. Scheduler waits for events registered in **EventsToRegister()**
9. **BUG**: ResourceSlice events are not registered, so pod is never re-queued when driver creates ResourceSlices

### Why This Bug Occurs

The dynamicResources plugin was designed to handle events from:
- Resource class/claim parameter changes
- Pod scheduling context updates (driver feedback on where to try allocating)
- Node changes (topology filtering)
- Resource claim updates (allocation status changes)

However, the developers missed that ResourceSlices themselves (which come directly from drivers advertising available resources) also need to trigger re-scheduling attempts.

### Impact

- **Severity**: HIGH - Pods can become permanently stuck
- **Scope**: Only affects pods using DRA with structured parameters (StructuredParameters: true)
- **Workaround**: Restart the scheduler or manually delete and recreate the pod after the driver is running
- **Detectability**: Hard to diagnose - pod shows "Unschedulable" but resources actually exist

### Testing

To verify the fix works:
1. Create a pod requesting DRA devices with structured parameters
2. Verify pod becomes Unschedulable (no ResourceSlices yet)
3. Start the DRA driver
4. Verify ResourceSlices are created
5. Verify pod is automatically re-queued and scheduled (instead of staying stuck)

## Related Code References

- **DRA feature documentation**: `pkg/features/kube_features.go` - EnableDynamicResourceAllocation flag
- **ResourceClaim informer setup**: `dynamicresources.go` line 351-356
- **ResourceSlice lister**: `dynamicresources.go` line 280, 356
- **Queue re-evaluation mechanism**: `pkg/scheduler/internal/queue/` - scheduling queue implementation
- **Event hinting system**: `pkg/scheduler/framework/plugins/` - other plugins using QueueingHintFn
