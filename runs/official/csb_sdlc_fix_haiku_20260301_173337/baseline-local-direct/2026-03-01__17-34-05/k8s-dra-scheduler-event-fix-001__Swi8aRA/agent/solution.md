# Kubernetes Scheduler: Missing ResourceSlice Event Handler Bug Analysis

## Files Examined
- `pkg/scheduler/schedule_one.go` — Entry point for pod scheduling; implements the scheduling cycle that invokes plugins
- `pkg/scheduler/eventhandlers.go` — Registers event handlers for cluster resource changes; handles Pod, Node, Storage, and DRA-related resources
- `pkg/scheduler/framework/types.go` — Defines GVK (Group/Version/Kind) constants for all resources that trigger scheduling queue re-evaluation
- `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go` — DRA plugin that validates pod resource claims; uses ResourceSliceLister but does NOT register ResourceSlice events
- `staging/src/k8s.io/api/resource/v1alpha2/types.go` — Defines ResourceSlice API type; used by DRA drivers to advertise available resources
- `staging/src/k8s.io/client-go/informers/resource/v1alpha2/interface.go` — SharedInformerFactory provides ResourceSlices() method for accessing ResourceSlice informer

## Dependency Chain
1. **Symptom observed in**: `pkg/scheduler/schedule_one.go:ScheduleOne()`
   - Pod requesting DRA devices arrives at scheduler
   - Plugin execution reaches dynamicresources plugin PreFilter phase

2. **Called from**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go:EventsToRegister()`
   - Plugin declares which events should trigger pod re-evaluation
   - RegisterResourceClaim, ResourceClass, PodSchedulingContext, etc. events registered
   - **BUT ResourceSlice events are NOT registered** (missing line)

3. **Propagated to**: `pkg/scheduler/scheduler.go:unionedGVKs()`
   - Collects all GVKs from all plugins' EventsToRegister()
   - Builds gvkMap: `map[framework.GVK]framework.ActionType`
   - ResourceSlice GVK never added because plugin didn't request it

4. **Passed to**: `pkg/scheduler/eventhandlers.go:addAllEventHandlers()`
   - Iterates through gvkMap to register informer event handlers
   - For each GVK, adds handler to move unschedulable pods to active/backoff queue on events
   - **No case for ResourceSlice in switch statement** (lines 396-542)

5. **Bug triggered by**: `pkg/scheduler/framework/types.go` lines 68-106
   - **ResourceSlice GVK constant is NOT DEFINED**
   - Means plugins cannot register ResourceSlice events structurally
   - UnrollWildCardResource() (lines 177-193) also missing ResourceSlice

## Root Cause

**File**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go`

**Function**: `EventsToRegister()` (line 381-413)

**Line**: ~410-411 (missing code block after ResourceClass event)

**Explanation**:
The dynamicresources plugin has three critical issues:

1. **Missing Event Registration**: The plugin's `EventsToRegister()` method registers events for ResourceClaim, ResourceClass, PodSchedulingContext, ResourceClaimParameters, and ResourceClassParameters, but **does NOT include ResourceSlice** events. This is the direct cause of the bug.

2. **ResourceSlice Not in Framework**: The `framework/types.go` file defines GVK constants for other DRA resources (ResourceClaim, ResourceClass, ResourceClaimParameters, ResourceClassParameters, PodSchedulingContext) but **ResourceSlice is missing**. This blocks the ability to register the event handler.

3. **Event Handler Not Implemented**: The `eventhandlers.go` file has a case for PodSchedulingContext (line 448), ResourceClaim (line 457), ResourceClass (line 466), ResourceClaimParameters (line 475), and ResourceClassParameters (line 484), but **no case for ResourceSlice**. Even if a plugin tried to register the event, the scheduler wouldn't know how to attach the event handler to the ResourceSlice informer.

**Why This Causes the Bug**:
- When a pod requesting DRA devices is scheduled before the DRA driver publishes ResourceSlices, the dynamicresources plugin's Filter hook returns `Unschedulable` because `structuredParameters.go:newResourceModel()` cannot find any ResourceSlices to validate available resources
- The pod is added to the unschedulable queue with the assumption that a future event will trigger re-evaluation
- Later, when the DRA driver publishes ResourceSlice objects, there is NO event handler listening to ResourceSlice changes
- No ClusterEvent is generated, so pods waiting in the unschedulable queue are never re-queued
- **The pod remains stuck permanently in Unschedulable state**

## Proposed Fix

### Fix 1: Add ResourceSlice GVK to framework/types.go

```diff
// pkg/scheduler/framework/types.go (lines 67-106)

const (
	// ... existing constants ...
	ResourceClass           GVK = "ResourceClass"
	ResourceClaimParameters GVK = "ResourceClaimParameters"
	ResourceClassParameters GVK = "ResourceClassParameters"
+	ResourceSlice           GVK = "ResourceSlice"

	// WildCard is a special GVK to match all resources.
	// e.g., If you register `{Resource: "*", ActionType: All}` in EventsToRegister,
	// all coming clusterEvents will be admitted. Be careful to register it, it will
	// increase the computing pressure in requeueing unless you really need it.
	//
	// Meanwhile, if the coming clusterEvent is a wildcard one, all pods
	// will be moved from unschedulablePod pool to activeQ/backoffQ forcibly.
	WildCard GVK = "*"
)
```

### Fix 2: Add ResourceSlice to UnrollWildCardResource() in framework/types.go

```diff
// pkg/scheduler/framework/types.go (lines 177-193)

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

### Fix 3: Add ResourceSlice event handler to eventhandlers.go

```diff
// pkg/scheduler/eventhandlers.go (lines 484-516)

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

### Fix 4: Add ResourceSlice events to dynamicresources plugin EventsToRegister() in dynamicresources.go

```diff
// pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go (lines 381-412)

func (pl *dynamicResources) EventsToRegister() []framework.ClusterEventWithHint {
	if !pl.enabled {
		return nil
	}

	events := []framework.ClusterEventWithHint{
		// Changes for claim or class parameters creation may make pods
		// schedulable which depend on claims using those parameters.
		{Event: framework.ClusterEvent{Resource: framework.ResourceClaimParameters, ActionType: framework.Add | framework.Update}, QueueingHintFn: pl.isSchedulableAfterClaimParametersChange},
		{Event: framework.ClusterEvent{Resource: framework.ResourceClassParameters, ActionType: framework.Add | framework.Update}, QueueingHintFn: pl.isSchedulableAfterClassParametersChange},

		// Allocation is tracked in ResourceClaims, so any changes may make the pods schedulable.
		{Event: framework.ClusterEvent{Resource: framework.ResourceClaim, ActionType: framework.Add | framework.Update}, QueueingHintFn: pl.isSchedulableAfterClaimChange},
		// When a driver has provided additional information, a pod waiting for that information
		// may be schedulable.
		{Event: framework.ClusterEvent{Resource: framework.PodSchedulingContext, ActionType: framework.Add | framework.Update}, QueueingHintFn: pl.isSchedulableAfterPodSchedulingContextChange},
		// A resource might depend on node labels for topology filtering.
		// A new or updated node may make pods schedulable.
		//
		// A note about UpdateNodeTaint event:
		// NodeAdd QueueingHint isn't always called because of the internal feature called preCheck.
		// As a common problematic scenario,
		// when a node is added but not ready, NodeAdd event is filtered out by preCheck and doesn't arrive.
		// In such cases, this plugin may miss some events that actually make pods schedulable.
		// As a workaround, we add UpdateNodeTaint event to catch the case.
		// We can remove UpdateNodeTaint when we remove the preCheck feature.
		// See: https://github.com/kubernetes/kubernetes/issues/110175
		{Event: framework.ClusterEvent{Resource: framework.Node, ActionType: framework.Add | framework.UpdateNodeLabel | framework.UpdateNodeTaint}},
		// A pod might be waiting for a class to get created or modified.
		{Event: framework.ClusterEvent{Resource: framework.ResourceClass, ActionType: framework.Add | framework.Update}},
+		// ResourceSlices published by DRA drivers may make pods schedulable by providing capacity information.
+		{Event: framework.ClusterEvent{Resource: framework.ResourceSlice, ActionType: framework.Add | framework.Update}, QueueingHintFn: pl.isSchedulableAfterResourceSliceChange},
	}
	return events
}
```

And add the corresponding QueueingHintFn method after the other isSchedulableAfter* methods:

```diff
// pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go (after line 500 or similar)

+// isSchedulableAfterResourceSliceChange is invoked for add and update resource slice events.
+// It checks whether that change made a previously unschedulable pod schedulable.
+// ResourceSlices are added by DRA drivers to advertise available resources, which may
+// allow previously stuck pods to be allocated.
+// It errs on the side of letting a pod scheduling attempt happen.
+func (pl *dynamicResources) isSchedulableAfterResourceSliceChange(logger klog.Logger, pod *v1.Pod, oldObj, newObj interface{}) (framework.QueueingHint, error) {
+	// Any ResourceSlice change might make a pod that uses structured parameters schedulable,
+	// so we should always retry scheduling for pods using claims.
+	return framework.Queue, nil
+}
```

## Analysis

### Execution Path from Symptom to Root Cause

1. **Initial Scheduling Attempt** (pod created before DRA driver starts):
   - Pod with ResourceClaim arrives at scheduler
   - `schedule_one.go:ScheduleOne()` begins scheduling cycle
   - Plugins execute PreFilter → Filter phases
   - dynamicresources plugin's `Filter()` hook runs
   - `structuredparameters.go:newResourceModel()` is called
   - ResourceSliceLister has NO ResourceSlices (driver hasn't started)
   - Plugin returns `Unschedulable` status: "cannot allocate all claims"
   - Pod marked as unschedulable, moved to unschedulable queue

2. **Pod Queued for Re-evaluation** (scheduling cycle completes):
   - Pod has UnschedulablePlugins = {dynamicResources}
   - Stored in scheduler's unschedulable pod pool
   - Waits for a registered ClusterEvent to trigger re-evaluation

3. **DRA Driver Starts** (driver publishes ResourceSlice):
   - DRA driver creates ResourceSlice objects with available resources
   - ResourceSlice objects appear in apiserver
   - **ResourceSlice informer receives Add event**
   - **BUT no event handler is registered for ResourceSlice**
   - Event is silently dropped (not delivered to scheduler)

4. **Pod Stays Stuck** (race condition manifests):
   - No ClusterEvent is generated for ResourceSlice changes
   - Scheduler never calls `MoveAllToActiveOrBackoffQueue` for unschedulable pods
   - Pod remains in unschedulable queue indefinitely
   - Pod will never be retried unless another event (like Node change) happens

### Why This is a Race Condition

- **If driver starts FIRST**: ResourceSlices exist when pod arrives → dynamicresources plugin sees resources → scheduling succeeds
- **If pod arrives FIRST**: No ResourceSlices exist → plugin marks pod unschedulable → driver starts and publishes ResourceSlices → but no event handler catches this → pod stuck forever

### The Missing Link

The scheduler's event-driven architecture works like this:
1. Plugins declare events they care about via `EventsToRegister()` → QueueingHintFn
2. Scheduler registers event handlers for those events with informers
3. When events fire, handlers call `MoveAllToActiveOrBackoffQueue()` with appropriate QueueingHints
4. Unschedulable pods matching QueueingHints are retried

ResourceSlice events were never added to this pipeline, so they never trigger pod re-evaluation.

## Impact

This bug prevents Dynamic Resource Allocation (DRA) from functioning in production scenarios where:
- DRA drivers (like GPU device plugins) start after user pods
- Pods request resources via ResourceClaim objects
- Pods become permanently stuck if scheduling is attempted before driver publishes ResourceSlices

The fix ensures that whenever a DRA driver publishes or updates ResourceSlices, pods waiting for those resources are immediately re-evaluated for scheduling.
