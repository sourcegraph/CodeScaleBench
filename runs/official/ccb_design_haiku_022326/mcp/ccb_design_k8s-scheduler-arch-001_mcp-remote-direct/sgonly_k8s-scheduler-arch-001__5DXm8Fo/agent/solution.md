# Kubernetes Scheduler Architecture: Pod Scheduling Pipeline Analysis

## Files Examined

### Core Scheduler Components
- **pkg/scheduler/scheduler.go** — Main Scheduler struct, initialization, and event handler setup. Contains the Scheduler struct with Cache, SchedulingQueue, Profiles, and SchedulePod function. The Run() method starts the main scheduling loop.
- **pkg/scheduler/schedule_one.go** — Main scheduling pipeline orchestration. Contains ScheduleOne() which calls schedulingCycle() and bindingCycle(). Implements schedulePod(), findNodesThatFitPod(), and the two-phase scheduling design.

### Plugin Framework
- **pkg/scheduler/framework/interface.go** — Plugin interfaces for all extension points: PreEnqueuePlugin, PreFilterPlugin, FilterPlugin, PostFilterPlugin, PreScorePlugin, ScorePlugin, ReservePlugin, PreBindPlugin, BindPlugin, PostBindPlugin, PermitPlugin. Defines Framework interface and Status codes.
- **pkg/scheduler/framework/cycle_state.go** — CycleState struct for storing plugin state during a scheduling cycle using sync.Map for thread-safe "write once, read many" access.
- **pkg/scheduler/framework/runtime/framework.go** — frameworkImpl implementation managing plugin registration, initialization, and execution. Contains Run* methods for each extension point. Implements plugin discovery, validation, and orchestration.
- **pkg/scheduler/framework/runtime/registry.go** — Plugin registry for factory functions, allows both in-tree and out-of-tree plugin registration.

### Scheduling Queue & Cache
- **pkg/scheduler/internal/queue/scheduling_queue.go** — SchedulingQueue interface and PriorityQueue implementation with three sub-queues: activeQ (pods being scheduled), backoffQ (backoff waiting), unschedulablePods (unschedulable pods). Implements pod nomination and in-flight tracking.
- **pkg/scheduler/internal/cache/interface.go** — Cache interface for pod and node state management. Implements state machine: Initial → Assumed → Added/Expired → Deleted. Tracks assumed pods for optimistic scheduling.

### Built-in Plugins & Utilities
- **pkg/scheduler/framework/plugins/** — In-tree plugin implementations (NodeResourcesFit, NodeAffinity, PodAffinity, Taint, etc.)
- **pkg/scheduler/profile/profile.go** — Scheduler profile management for multi-scheduler support
- **pkg/scheduler/framework/parallelize/parallelize.go** — Parallel execution utilities for filter and score operations

## Dependency Chain

### 1. Entry Point: Main Scheduling Loop
**scheduler.go:435 Run()** → Starts SchedulingQueue and launches main scheduling loop
- Calls `sched.SchedulingQueue.Run()` to start queue processing
- Calls `wait.UntilWithContext(ctx, sched.ScheduleOne, 0)` - runs ScheduleOne repeatedly until context done

### 2. Pod Retrieval & Framework Selection
**schedule_one.go:66 ScheduleOne()** → Processes one pod per invocation
- Calls `sched.NextPod()` (which is `podQueue.Pop()`) to get next pod from queue (line 68)
- Calls `sched.frameworkForPod(pod)` to select the appropriate framework/profile (line 86)
- Checks `sched.skipPodSchedule()` - skips if pod is deleted or already assumed (line 93)
- Creates `framework.CycleState` for storing plugin state (line 101)

### 3. Scheduling Cycle (Phase 1: Find & Reserve)
**schedule_one.go:139 schedulingCycle()** → Main scheduling algorithm
- Calls `sched.SchedulePod()` which is `sched.schedulePod()` (line 149)
  - **schedule_one.go:390 schedulePod()** → Filters and scores nodes
    - Calls `sched.Cache.UpdateSnapshot()` to get current node state snapshot (line 393)
    - Calls `sched.findNodesThatFitPod()` - performs filtering (line 402)
      - **schedule_one.go:442 findNodesThatFitPod()** → Filters nodes via PreFilter, Filter, and extenders
        - Calls `fwk.RunPreFilterPlugins()` - extension point: PreFilter (line 453)
        - Evaluates nominated node if present (line 475)
        - Calls `sched.findNodesThatPassFilters()` - parallel Filter plugin execution (line 498)
          - **schedule_one.go:573 findNodesThatPassFilters()** → Parallel filter execution
            - Calls `fwk.RunFilterPluginsWithNominatedPods()` in parallel for each node (line 611)
            - Uses `fwk.Parallelizer().Until()` to parallelize node evaluation
        - Calls `findNodesThatPassExtenders()` - runs extender filters sequentially (line 507)
    - Calls `prioritizeNodes()` - performs scoring (line 425)
      - **schedule_one.go:745 prioritizeNodes()** → Scores feasible nodes
        - Calls `fwk.RunPreScorePlugins()` - extension point: PreScore (line 768)
        - Calls `fwk.RunScorePlugins()` - extension point: Score (line 774)
        - Calls extender Prioritize methods in parallel (line 806)
    - Calls `selectHost()` - selects best node via reservoir sampling (line 430)

- **Back in schedulingCycle():** If scheduling successful:
  - Calls `sched.assume()` - optimistically updates cache (line 198)
    - Updates pod.Spec.NodeName
    - Calls `sched.Cache.AssumePod()` to mark pod as assumed in cache
    - Calls `sched.SchedulingQueue.DeleteNominatedPodIfExists()` if applicable
  - Calls `fwk.RunReservePluginsReserve()` - extension point: Reserve (line 209)
    - If failed: calls `fwk.RunReservePluginsUnreserve()` and `sched.Cache.ForgetPod()`
  - Calls `fwk.RunPermitPlugins()` - extension point: Permit (line 231)
    - Returns Success, Wait, or rejection status

### 4. Binding Cycle (Phase 2: Bind - Async Goroutine)
**schedule_one.go:118 Launches bindingCycle() in goroutine**

**schedule_one.go:265 bindingCycle()** → Asynchronously binds pod to node
- Calls `fwk.WaitOnPermit()` - waits for Permit plugins to allow binding (line 278)
- Calls `fwk.RunPreBindPlugins()` - extension point: PreBind (line 294)
- Calls `sched.bind()` - performs actual binding (line 299)
  - **schedule_one.go:958 bind()** → Executes binding
    - Tries `sched.extendersBinding()` - extender binding if available (line 964)
    - Calls `fwk.RunBindPlugins()` - extension point: Bind (line 968)
- Calls `fwk.RunPostBindPlugins()` - extension point: PostBind (line 312)
- Calls `sched.SchedulingQueue.Done()` to mark pod processing complete (line 132)

### 5. Failure Handling
**schedule_one.go:113 FailureHandler()** → Called if scheduling or binding fails
- **schedule_one.go:1013 handleSchedulingFailure()** → Handles scheduling failures
  - Runs `fwk.RunPostFilterPlugins()` - extension point: PostFilter for preemption (line 176)
  - Adds pod to unschedulable queue or backoff queue
  - Updates pod condition and nominated node information

**schedule_one.go:324 handleBindingCycleError()** → Handles binding failures
- Calls `fwk.RunReservePluginsUnreserve()` to release reservations
- Calls `sched.Cache.ForgetPod()` to remove assumed pod
- Calls `sched.SchedulingQueue.MoveAllToActiveOrBackoffQueue()` to requeue affected pods

## Architecture Analysis

### Design Patterns

#### 1. **Two-Phase Scheduling with Optimistic Assumptions**
The scheduler separates scheduling into two independent phases running asynchronously:
- **Scheduling Cycle (Synchronous)**: Finds node and reserves resources without blocking
- **Binding Cycle (Asynchronous)**: Actually binds pod to API server in background

The key innovation is the **assume** operation: after scheduling decides a node, it optimistically assumes the pod is bound (`Cache.AssumePod()`) and updates the in-memory cache. This allows subsequent pods to be scheduled based on this assumption, without waiting for the API server to confirm binding. If binding later fails, the cache is rolled back via `Cache.ForgetPod()`.

#### 2. **Plugin Framework with Extension Points**
The scheduler uses a sophisticated plugin architecture with **11 extension points** executed in this order:

**Scheduling Cycle:**
1. **PreEnqueue** - Filter pods before adding to queue (in queue processing)
2. **PreFilter** - Early filtering, can reduce node set to evaluate
3. **Filter** - Main feasibility checking (parallel)
4. **PostFilter** - Preemption/remediation (runs if no nodes pass Filter)
5. **PreScore** - Prepare for scoring
6. **Score** - Rank nodes (parallel)
7. **Reserve** - Update plugin state after selection

**Binding Cycle:**
8. **Permit** - Final approval gate, can delay binding
9. **PreBind** - Pre-binding setup
10. **Bind** - Actual binding to API server
11. **PostBind** - Cleanup/notification after successful binding

#### 3. **Concurrent Execution**
- **Filter plugins run in parallel** across nodes using `fwk.Parallelizer().Until()`
- **Score plugins run in parallel** for selected nodes
- **Binding happens asynchronously** in a separate goroutine
- **Multiple pods schedule concurrently** - each pod is independent, but all share the same cache

#### 4. **Smart Queueing with Priority**
The **SchedulingQueue** manages pods with intelligent prioritization:
- **activeQ** (heap): Primary queue of schedulable pods, ordered by QueueSort plugin
- **backoffQ** (heap): Failed pods with exponential backoff, waiting to retry
- **unschedulablePods**: Pods that failed scheduling, stay here until cluster state changes
- **In-flight tracking**: Maps UID → in-flight pod entries to track which pods are currently being scheduled

#### 5. **Event-Driven Requeueing with Queueing Hints**
When a cluster event occurs (node added, pod updated, etc.), the scheduler uses **EnqueueExtensions** to efficiently requeue only affected pods:
- Plugins register which events can make them pass/fail
- On each event, only pods rejected by interested plugins are requeued
- Reduces unnecessary retries and improves scheduling latency

#### 6. **State Machine for Pod Lifecycle in Cache**
The cache implements a pod state machine:
```
Initial → Assumed → Added → Deleted
          ↘ Expired ↗
```
- **Initial**: Pod not in cache
- **Assumed**: Optimistically scheduled, in cache but not API-confirmed
- **Added**: Pod confirmed by API server
- **Expired**: Assumed pod timed out waiting for Add confirmation
- **Deleted**: Pod removed from cache

### Component Responsibilities

#### **Scheduler (scheduler.go)**
- Orchestrates the overall scheduling loop
- Holds Cache, SchedulingQueue, Profiles
- Manages event handlers for pod/node updates
- Delegates scheduling to framework profiles

#### **Framework (framework/runtime/framework.go)**
- Manages plugin lifecycle (initialization, execution, cleanup)
- Provides Run* methods for each extension point
- Coordinates plugin execution order and error handling
- Maintains plugin state (pluginsMap, extensions point slices)
- Implements Handle interface for plugin callbacks

#### **Cache (internal/cache/interface.go)**
- Maintains in-memory pod and node state
- Implements assume/forget/add/remove operations
- Provides node info snapshots for scheduling
- Tracks assumed pods and their expiration

#### **SchedulingQueue (internal/queue/scheduling_queue.go)**
- Manages three sub-queues of pods at different stages
- Implements pod nomination for preemption
- Tracks in-flight pods being processed
- Handles backoff logic for failed pods
- Processes cluster events to requeue pods

### Data Flow During Scheduling Cycle

```
1. Pod enters queue (via pod watcher event handler)
   ↓
2. ScheduleOne() pops pod from queue
   ↓
3. Create fresh CycleState for this pod
   ↓
4. Scheduling Cycle:
   4a. PreFilter plugins → optional node reduction
   4b. Filter plugins (parallel) → feasible nodes
   4c. PostFilter plugins (if needed) → preemption
   4d. PreScore plugins
   4e. Score plugins (parallel) → ranked nodes
   4f. Reserve plugins → reserve resources
   4g. Permit plugins → final approval
   ↓
5. Assume pod in cache (optimistic scheduling)
   ↓
6. Launch Binding Cycle asynchronously:
   6a. WaitOnPermit → wait for gate
   6b. PreBind plugins
   6c. Bind plugins → API server binding
   6d. PostBind plugins
   6e. Mark pod Done in queue
   ↓
7. On failure: Unreserve, Forget, and requeue
```

### Interface Contracts

#### **Plugin Interface (framework/interface.go)**
Each plugin implements `Plugin` base interface with `Name()` method, plus one or more extension point interfaces:
- `PreEnqueuePlugin.PreEnqueue(ctx, pod) Status`
- `PreFilterPlugin.PreFilter(ctx, state, pod) (PreFilterResult, Status)`
- `FilterPlugin.Filter(ctx, state, pod, nodeInfo) Status`
- `ScorePlugin.Score(ctx, state, pod, nodeName) (int64, Status)`
- `ReservePlugin.Reserve(ctx, state, pod, nodeName) Status`
- `PermitPlugin.Permit(ctx, state, pod, nodeName) (Status, time.Duration)`
- `BindPlugin.Bind(ctx, state, pod, nodeName) Status`

#### **CycleState (framework/cycle_state.go)**
Thread-safe map for storing plugin-specific state:
- `Write(key StateKey, data StateData)` - store state
- `Read(key StateKey) (StateData, error)` - retrieve state
- `Clone() CycleState` - create copy for preemption scenarios

#### **PodNominator (framework/interface.go)**
Manages nominated pods for preemption:
- `AddNominatedPod(pod, nominatingInfo)` - mark pod as nominated
- `DeleteNominatedPodIfExists(pod)` - remove nomination
- `NominatedPodsForNode(nodeName) []PodInfo` - get nominated pods on node

## Summary

The Kubernetes scheduler uses a **two-phase pipeline (scheduling + binding) with an 11-point plugin framework** to schedule pods to nodes. Pods flow from the queue through a filtering phase (PreFilter → Filter → optional PostFilter), then a scoring phase (PreScore → Score), then reservation and permission gates. Once a node is selected, the pod is **optimistically assumed** in the cache (allowing subsequent pods to consider it), and binding happens asynchronously in a separate phase with PreBind → Bind → PostBind plugins. The architecture enables **concurrent scheduling of multiple pods** while maintaining consistency through intelligent cache management, event-driven requeueing, and transactional semantics where binding failures trigger rollback of assumptions.
