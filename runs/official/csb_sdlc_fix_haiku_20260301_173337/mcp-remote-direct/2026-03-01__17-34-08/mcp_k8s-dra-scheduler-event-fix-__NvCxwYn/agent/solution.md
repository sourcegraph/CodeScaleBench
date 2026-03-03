# Bug Investigation: Missing ResourceSlice Event Handler in Kubernetes Scheduler

## Files Examined

- **pkg/scheduler/framework/types.go** — examined to find framework.GVK constant definitions
- **pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go** — examined for EventsToRegister() method that declares which cluster events should trigger pod re-queuing
- **pkg/scheduler/eventhandlers.go** — examined for addAllEventHandlers() which registers informer event handlers based on plugin-declared GVKs
- **pkg/scheduler/scheduler.go** — examined for the initialization path that connects event handlers to the scheduling queue
- **pkg/scheduler/framework/plugins/dynamicresources/structuredparameters.go** — examined to see how resourceSliceLister is used

## Dependency Chain

1. **Symptom observed in**: `pkg/scheduler/scheduler.go` (~line 358)
   - Entry point where event handlers are registered via `addAllEventHandlers()`

2. **Called from**: `addAllEventHandlers()` in `pkg/scheduler/eventhandlers.go` (line 287)
   - Function iterates over `gvkMap` and registers event handlers for each GVK
   - `gvkMap` is built from `unionedGVKs(queueingHintsPerProfile)`

3. **GVK map populated by**: `unionedGVKs()` in `pkg/scheduler/scheduler.go` (line 525)
   - Collects GVKs from all plugins' `EventsToRegister()` methods

4. **Plugin declares events via**: `EventsToRegister()` in `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go` (line 381)
   - Returns list of framework.ClusterEventWithHint that should trigger re-queuing
   - **BUG**: ResourceSlice is NOT in this list

5. **Plugin uses resourceSliceLister in**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go` (line 958)
   - Calls `newResourceModel(logger, pl.resourceSliceLister, ...)` to fetch available resources
   - `newResourceModel()` in `structuredparameters.go` (line 51) lists all ResourceSlices

6. **GVK constant missing from**: `pkg/scheduler/framework/types.go` (line 68-106)
   - Lists all framework.GVK constants but ResourceSlice is missing

## Root Cause

**There are TWO root causes that prevent ResourceSlice events from triggering pod re-queuing:**

### Root Cause #1: Missing GVK Constant Definition
- **File**: `pkg/scheduler/framework/types.go`
- **Location**: Lines 68-106 (const block for GVK definitions)
- **Line**: After line 96 (ResourceClassParameters constant)
- **Explanation**: The `framework.ResourceSlice` GVK constant is not defined, making it impossible to reference ResourceSlice in event registration code

### Root Cause #2: Missing Event Registration in DynamicResources Plugin
- **File**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go`
- **Function**: `EventsToRegister()`
- **Line**: ~412 (end of events slice definition)
- **Explanation**: The `EventsToRegister()` method returns a list of framework.ClusterEventWithHint that declare which events should trigger pod re-queuing. ResourceSlice events (Add/Update) are missing from this list, even though the plugin uses `resourceSliceLister` to fetch ResourceSlice data during the Filter phase (line 958).

## Why This Causes the Bug

When a pod requests DRA resources:

1. Pod arrives at scheduler before ResourceSlices exist
2. DynamicResources plugin's Filter/PreScore phase tries to allocate resources
3. `newResourceModel()` is called, which lists all ResourceSlices (line 51 of structuredparameters.go)
4. Since no ResourceSlices exist, the filter fails with "cannot allocate all claims"
5. Pod is added to the unschedulable queue
6. **Later, when the DRA driver starts and creates ResourceSlices:**
   - ResourceSlice Add/Update events are generated
   - BUT: ResourceSlice events are NOT registered in eventhandlers.go (because they're not in the GVK map)
   - Pod in unschedulable queue is **NEVER re-evaluated**
   - Pod stays stuck in Unschedulable state forever

The race condition: if the driver starts FIRST, ResourceSlices exist before the pod arrives, so scheduling succeeds immediately. If the pod arrives first, it gets stuck because resource availability changes don't trigger re-queuing.

## Proposed Fix

### Fix #1: Add ResourceSlice GVK Constant

**File**: `pkg/scheduler/framework/types.go`
**Lines**: After line 96 (ResourceClassParameters constant) and before line 97 (blank line)

```diff
 	ResourceClaim           GVK = "ResourceClaim"
 	ResourceClass           GVK = "ResourceClass"
 	ResourceClaimParameters GVK = "ResourceClaimParameters"
 	ResourceClassParameters GVK = "ResourceClassParameters"
+	ResourceSlice           GVK = "ResourceSlice"

 	// WildCard is a special GVK to match all resources.
```

### Fix #2: Register ResourceSlice Events in Plugin

**File**: `pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go`
**Function**: `EventsToRegister()`
**Lines**: After line 410 (ResourceClass event) and before line 411 (closing `]`)

```diff
 		// A pod might be waiting for a class to get created or modified.
 		{Event: framework.ClusterEvent{Resource: framework.ResourceClass, ActionType: framework.Add | framework.Update}},
+		// ResourceSlices provide information about available resources on nodes.
+		// Changes to ResourceSlices may make pods schedulable.
+		{Event: framework.ClusterEvent{Resource: framework.ResourceSlice, ActionType: framework.Add | framework.Update}},
 	}
 	return events
```

### Fix #3: Add Event Handler for ResourceSlice

**File**: `pkg/scheduler/eventhandlers.go`
**Function**: `addAllEventHandlers()`
**Location**: In the switch/case statement for gvkMap
**Lines**: After line 492 (end of ResourceClassParameters case) and before line 493 (StorageClass case)

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
```

**Why all three fixes are necessary:**
1. **GVK Constant** enables referencing ResourceSlice in code throughout the framework
2. **Event Registration in Plugin** declares to the scheduler that ResourceSlice events matter to the DynamicResources plugin
3. **Event Handler** connects the informer callback to the scheduling queue so unschedulable pods can be re-queued when ResourceSlices change

## Analysis: Detailed Trace from Symptom to Root Cause

### Phase 1: Scheduler Initialization

1. `Scheduler.New()` in `pkg/scheduler/scheduler.go` initializes the scheduler
2. It calls plugins to get their `EventsToRegister()` at line ~300s
3. `DynamicResourceAllocation` plugin's `EventsToRegister()` is called (dynamicresources.go:381)
4. The plugin returns a slice of ClusterEventWithHint that includes:
   - ResourceClaimParameters (Add, Update)
   - ResourceClassParameters (Add, Update)
   - ResourceClaim (Add, Update)
   - PodSchedulingContext (Add, Update)
   - Node (Add, UpdateNodeLabel, UpdateNodeTaint)
   - ResourceClass (Add, Update)
   - **MISSING: ResourceSlice (Add, Update)**

5. `unionedGVKs()` is called (scheduler.go:525) to collect all GVKs from all plugins
6. Since ResourceSlice is not in EventsToRegister(), it's not in the gvkMap
7. `addAllEventHandlers()` is called with this incomplete gvkMap
8. The function iterates over gvkMap and registers event handlers
9. **ResourceSlice case is never hit because ResourceSlice GVK is not in gvkMap**

### Phase 2: Pod Scheduling (Pod Arrives Before Driver)

1. Pod with DRA ResourceClaims arrives at scheduler
2. Pod is added to scheduling queue via `addPodToSchedulingQueue()` (line 125)
3. Scheduler attempts to schedule the pod
4. DynamicResources plugin's PreFilter phase initializes the state
5. DynamicResources plugin's Filter phase calls:
   - `newResourceModel()` (line 958) which lists all ResourceSlices
   - Since ResourceSlices don't exist yet, allocation fails
   - Filter returns Unschedulable

6. Pod is moved to unschedulable queue via SchedulingQueue.MoveAllToActiveOrBackoffQueue()
7. Pod waits for one of its registered events to occur

### Phase 3: Driver Starts and Creates ResourceSlices (BUG MANIFESTS)

1. DRA driver starts and creates ResourceSlice objects
2. Kubernetes API server generates ResourceSlice Add/Update events
3. Informer receives these events and calls registered event handlers
4. **BUT: No event handler is registered for ResourceSlice** (because it wasn't in gvkMap)
5. Events are silently dropped - never reach the scheduling queue
6. Scheduler never calls `SchedulingQueue.MoveAllToActiveOrBackoffQueue()` with a ResourceSlice event
7. Pod remains in unschedulable queue forever

### Phase 4: Why the Race Condition Works When Driver Starts First

If ResourceSlices exist before the pod is created:
1. Pod arrives at scheduler
2. DynamicResources plugin's Filter phase calls `newResourceModel()`
3. ResourceSlices are listed successfully
4. Allocation succeeds because resources are available
5. Pod is scheduled normally

The race condition occurs because:
- **Event-driven re-queuing is the ONLY mechanism** to move pods from unschedulable queue when their dependencies change
- ResourceSlice creation/update is a dependency for DRA pods
- But ResourceSlice events are not wired into the event-driven re-queuing system
- Therefore pods become permanently stuck when the timing is wrong

## Why Both Fixes Are Needed

1. **GVK Constant** (framework/types.go): Without this, ResourceSlice cannot be referenced in code
2. **Event Registration** (dynamicresources.go): Without this, the plugin doesn't declare that it needs ResourceSlice events
3. **Event Handler** (eventhandlers.go): Without this, the informer doesn't know to call the scheduling queue when ResourceSlices change

The combination ensures the full chain works:
- Plugin declares it needs ResourceSlice events
- unionedGVKs() includes ResourceSlice in the map
- addAllEventHandlers() registers an informer handler for ResourceSlice
- When ResourceSlices change, the scheduling queue is notified
- Unschedulable pods are re-queued and can be scheduled
