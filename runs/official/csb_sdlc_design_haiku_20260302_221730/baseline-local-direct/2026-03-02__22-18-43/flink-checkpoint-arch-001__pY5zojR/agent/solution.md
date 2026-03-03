# Flink Checkpoint Coordination Architecture Analysis

## Files Examined

### JobManager-Side Coordination
- **CheckpointCoordinator.java** (109KB) — Central coordinator that triggers checkpoints, maintains pending checkpoints, receives acknowledgments, and finalizes completed checkpoints. Implements the distributed two-phase commit protocol.
- **PendingCheckpoint.java** (27KB) — Represents a checkpoint in-flight; tracks task acknowledgments, operator state, and coordinates finalization into CompletedCheckpoint.
- **CompletedCheckpoint.java** — Represents a successfully completed checkpoint; stores metadata, operator states, and external storage pointers.
- **CheckpointPlan.java** — Interface defining which tasks to trigger, wait for acknowledgment from, and commit to upon completion.
- **CheckpointOptions.java** — Configuration for checkpoint semantics (aligned, unaligned, exactly-once, etc.)
- **PendingCheckpointStats.java** — Statistics tracking for in-flight checkpoints.
- **CompletedCheckpointStore.java** — Interface for persisting completed checkpoints and managing their lifecycle.

### RPC & Execution Layer
- **Execution.java** — Executes RPC calls to TaskManager to trigger checkpoints on individual tasks via `triggerCheckpoint()` method.
- **TaskManagerGateway** (referenced) — RPC gateway that dispatches checkpoint trigger messages to TaskExecutor.
- **AcknowledgeCheckpoint.java** — Message sent from TaskExecutor back to JobManager containing task ID, checkpoint ID, state snapshot, and metrics.
- **DeclineCheckpoint.java** — Message sent to decline/abort a checkpoint.

### Streaming-Side Barrier Handling
- **CheckpointBarrier.java** — Runtime event carrying checkpoint ID, timestamp, and checkpoint options; injected into data streams at sources and propagates downstream.
- **CheckpointedInputGate.java** — Wraps InputGate to intercept and process checkpoint barriers using CheckpointBarrierHandler.
- **CheckpointBarrierHandler.java** (abstract) — Base class for barrier handling strategies; notifies task when all barriers received.
- **SingleCheckpointBarrierHandler.java** (20KB) — Concrete handler implementing aligned/unaligned checkpoint logic; manages barrier state machine transitions.
- **CheckpointBarrierTracker.java** (15KB) — Alternative handler for at-least-once semantics (no blocking); tracks barriers without alignment.
- **BarrierHandlerState.java** (interface) — State machine pattern defining 4 base states: waiting for aligned/unaligned barriers, collecting aligned/unaligned barriers.
- **WaitingForFirstBarrier.java** — Initial state for aligned checkpoints; blocks channels until first barrier arrives.
- **AlternatingWaitingForFirstBarrier.java** — State for alternating aligned/unaligned checkpoints with adaptive timeout.
- **AlternatingWaitingForFirstBarrierUnaligned.java** — Unaligned variant with no channel blocking.
- **CollectingBarriers.java** — State for collecting barriers from multiple channels.
- **AlternatingCollectingBarriers.java** — Alternating variant of barrier collection.
- **ChannelState.java** — Tracks which channels have received barriers.

### Task-Side Coordination
- **SubtaskCheckpointCoordinator.java** (interface) — Task-side checkpoint orchestrator coordinating: barrier processing, state snapshot building, acknowledgment reporting, completion/abort notifications.
- **CheckpointableTask.java** (referenced) — Interface for tasks to implement checkpoint behavior; invoked via `triggerCheckpointOnBarrier()`.
- **TaskStateSnapshot.java** — Snapshot of operator state collected during checkpoint.
- **OperatorSubtaskState.java** — Persisted subtask state including operator state, keyed state, channel state.

### State Management
- **OperatorState.java** — Aggregated state for an operator across all subtasks.
- **TaskState.java** — Task-level aggregation of operator states.
- **CheckpointStorageLocation.java** — Handle to checkpoint storage location before finalization.
- **CompletedCheckpointStorageLocation.java** — Finalized checkpoint storage location with metadata handle and external pointer.
- **CheckpointMetadata.java** — Metadata containing checkpoint ID, timestamp, and all operator/master states.

---

## Dependency Chain

### Phase 1: Checkpoint Trigger (JobManager → Tasks)

1. **Entry Point**: `CheckpointCoordinator.triggerCheckpoint(CheckpointProperties)`
   - Decision: Scheduled trigger or manual request
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:619`

2. → **Create PendingCheckpoint**: `CheckpointCoordinator.triggerCheckpoint()` allocates:
   - New checkpoint ID from `CheckpointIDCounter`
   - New `PendingCheckpoint` object tracking notYetAcknowledgedTasks
   - `CheckpointStorageLocation` for temporary storage
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:700-750`

3. → **Dispatch Barriers to Tasks**: `CheckpointCoordinator.triggerTasks(CheckpointTriggerRequest, long, PendingCheckpoint)`
   - Iterates over `checkpointPlan.getTasksToTrigger()`
   - Calls `execution.triggerCheckpoint(checkpointId, timestamp, checkpointOptions)` per task
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:836-868`

4. → **RPC to TaskManager**: `Execution.triggerCheckpointHelper()`
   - Acquires `TaskManagerGateway` from assigned slot
   - Invokes `taskManagerGateway.triggerCheckpoint(attemptId, jobId, checkpointId, timestamp, checkpointOptions)`
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/executiongraph/Execution.java:1088-1102`

5. → **Inject Barrier into Stream**: TaskExecutor receives RPC message and injects `CheckpointBarrier` into task's input channels

### Phase 2: Barrier Propagation & Alignment (Streaming Tasks)

6. **Entry Point**: `CheckpointedInputGate.getNextBufferOrEvent()`
   - Pulls data from `InputGate`
   - Extracts `CheckpointBarrier` events
   - Delegates to `CheckpointBarrierHandler`
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointedInputGate.java`

7. → **Process Barrier**: `CheckpointBarrierHandler.processBarrier(CheckpointBarrier, InputChannelInfo, boolean)`
   - Abstract method implemented by handler variant (aligned, unaligned, or tracker)
   - For `SingleCheckpointBarrierHandler`: delegates to state machine via `BarrierHandlerState.barrierReceived()`
   - For `CheckpointBarrierTracker`: increments barrier count for checkpoint ID
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierHandler.java:94-96`

8. → **Aligned Checkpoint** (if enabled):
   - **Initial State**: `WaitingForFirstBarrier.barrierReceived()` blocks incoming channels
   - **Transition**: When first barrier arrives, switches to `CollectingBarriers` state
   - **Collection**: Waits for barriers from all input channels
   - **Trigger**: When all barriers collected, calls `notifyCheckpoint()`
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/SingleCheckpointBarrierHandler.java:200-320`

   OR

   **Unaligned Checkpoint** (if aligned timeout exceeded):
   - **Initial State**: `AlternatingWaitingForFirstBarrierUnaligned`
   - **Trigger Early**: Initiates checkpoint immediately upon first barrier without blocking
   - **Capture In-flight Data**: Channel state writer captures data in-flight during alignment
   - **Non-blocking**: Barriers bypass alignment, process immediately
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/SingleCheckpointBarrierHandler.java:125-145`

   OR

   **Barrier Tracking** (at-least-once):
   - `CheckpointBarrierTracker.processBarrier()` increments counter without blocking
   - No input channel blocking; data continues flowing
   - Notifies task completion when all barriers observed
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierTracker.java:94-161`

### Phase 3: State Snapshot (Task-Side)

9. **Entry Point**: `CheckpointBarrierHandler.notifyCheckpoint(CheckpointBarrier)`
   - Creates `CheckpointMetaData` from barrier
   - Invokes `toNotifyOnCheckpoint.triggerCheckpointOnBarrier()`
   - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierHandler.java:125-149`

10. → **Initialize Checkpoint**: `SubtaskCheckpointCoordinator.initInputsCheckpoint(checkpointId, checkpointOptions)`
    - Prepares channel state writer
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/SubtaskCheckpointCoordinator.java:47-48`

11. → **Snapshot State**: `SubtaskCheckpointCoordinator.checkpointState()`
    - Iterates operator chain
    - Calls `operator.snapshotState()` for each operator
    - Collects keyed state, operator state, channel state
    - Returns `TaskStateSnapshot` containing all `OperatorSubtaskState` instances
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/SubtaskCheckpointCoordinator.java:59-66`

12. → **Propagate Barrier Downstream**: After local checkpoint:
    - Emits `CheckpointBarrier` to all output channels
    - Allows barrier to propagate through operator DAG
    - Location: Streaming operator chains broadcast barriers

### Phase 4: Acknowledgment (Task → JobManager)

13. **Entry Point**: `SubtaskCheckpointCoordinator.reportCheckpointMetrics()`
    - Builds `AcknowledgeCheckpoint` message containing:
      - Task execution attempt ID
      - Checkpoint ID
      - `TaskStateSnapshot` with all operator states
      - `CheckpointMetrics` (alignment duration, bytes, etc.)
    - Sends via RPC to JobManager
    - Location: Task execution layer

14. → **Receive Ack**: `CheckpointCoordinator.receiveAcknowledgeMessage(AcknowledgeCheckpoint)`
    - Validates message belongs to current job
    - Looks up `PendingCheckpoint` by checkpoint ID
    - Calls `checkpoint.acknowledgeTask(executionAttemptId, subtaskState, metrics)`
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:1210-1295`

15. → **Track Acknowledgment**: `PendingCheckpoint.acknowledgeTask()`
    - Removes task from `notYetAcknowledgedTasks` set
    - Adds to `acknowledgedTasks` set
    - Merges `TaskStateSnapshot` into `operatorStates` map
    - Increments `numAcknowledgedTasks` counter
    - Returns `TaskAcknowledgeResult.SUCCESS` or DUPLICATE/UNKNOWN
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/PendingCheckpoint.java:385-462`

### Phase 5: Completion & Finalization (JobManager)

16. **Check Completion**: `CheckpointCoordinator.receiveAcknowledgeMessage()` after ack:
    - Checks if `checkpoint.isFullyAcknowledged()`
    - Condition: all tasks, operator coordinators, and master states acknowledged
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:1266-1268`

17. → **Complete Pending Checkpoint**: `CheckpointCoordinator.completePendingCheckpoint(PendingCheckpoint)`
    - Calls `checkpoint.finalizeCheckpoint()` to convert to `CompletedCheckpoint`
    - Writes checkpoint metadata to storage via `CheckpointMetadataOutputStream`
    - Adds to `CompletedCheckpointStore`
    - Subsumes older checkpoints
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:1365-1402`

18. → **Finalize Metadata**: `PendingCheckpoint.finalizeCheckpoint()`
    - Creates `CheckpointMetadata` containing all operator states and master states
    - Serializes metadata to checkpoint storage location
    - Creates `CompletedCheckpoint` object with storage location and external pointer
    - Marks pending checkpoint as disposed (keeps state)
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/PendingCheckpoint.java:317-365`

19. → **Create CompletedCheckpoint**: Constructor captures:
    - Checkpoint ID, timestamp, completion timestamp
    - All `OperatorState` objects from all tasks
    - Master states from hooks
    - `CompletedCheckpointStorageLocation` with metadata handle
    - External pointer for recovery
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CompletedCheckpoint.java:129-150`

20. → **Notify Tasks**: `CheckpointCoordinator.sendAcknowledgeMessages()`
    - Sends completion notification to all tasks in `checkpointPlan.getTasksToCommitTo()`
    - Allows tasks to clean up temporary state and commit side effects
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:1439-1443`

21. → **Task Completion**: `SubtaskCheckpointCoordinator.notifyCheckpointComplete()`
    - Calls `operator.notifyCheckpointComplete()` on all operators
    - Allows operators to release temporary buffers, commit external systems
    - Location: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/SubtaskCheckpointCoordinator.java:75-77`

---

## Analysis

### Design Patterns Identified

**1. Distributed Two-Phase Commit Protocol**
- **Phase 1 (Prepare)**: CheckpointCoordinator triggers barriers; tasks snapshot state without committing
- **Phase 2 (Commit)**: Once all tasks acknowledge, metadata finalized and completion notifications sent
- **Key Insight**: State is kept in serialized form until completion confirmation; no irreversible writes until all tasks acknowledge
- **Implementation**: PendingCheckpoint tracks in-flight state; CompletedCheckpoint represents committed state

**2. State Machine Pattern**
- **Barrier Handler States**: 4 base states (aligned waiting, aligned collecting, unaligned waiting, unaligned collecting)
- **Transitions**: Driven by barrier arrivals, announcements, timeouts, and end-of-partition events
- **Purpose**: Cleanly separate alignment logic from barrier processing; enables pluggable strategies
- **Implementation**: `BarrierHandlerState` interface with concrete state classes

**3. Observer Pattern**
- **Observers**: Task notifications via `toNotifyOnCheckpoint.triggerCheckpointOnBarrier()`
- **Events**: Barrier arrival triggers checkpoint on receiving task
- **Decoupling**: CheckpointBarrierHandler doesn't know about task implementation; calls abstract interface

**4. Builder Pattern**
- **Configuration**: `CheckpointOptions` encapsulates checkpoint semantics (aligned, unaligned, timeout, etc.)
- **Reuse**: Same options broadcast to all tasks via barriers
- **Customization**: Allows variants (exactly-once, at-least-once, savepoint, async, etc.)

**5. Template Method Pattern**
- **Abstract Handler**: `CheckpointBarrierHandler` defines `notifyCheckpoint()` template
- **Variants**: Subclasses implement `processBarrier()` differently (SingleCheckpointBarrierHandler vs CheckpointBarrierTracker)
- **Shared Behavior**: Metrics collection, timing, notification all shared

**6. Strategy Pattern**
- **Checkpoint Strategies**: Aligned (blocks input) vs Unaligned (captures in-flight) vs Tracking (no blocking)
- **Selection**: Chosen at CheckpointedInputGate creation based on configuration
- **Swappable**: Can switch strategies without changing core barrier propagation logic

### Component Responsibilities

**JobManager-Side:**
- **CheckpointCoordinator**: Orchestrator; maintains checkpoint lifecycle state machine (scheduled → triggered → pending → completed)
- **PendingCheckpoint**: Accumulator; collects task acknowledgments and state snapshots
- **CompletedCheckpoint**: Repository; immutable record of successful checkpoint with external storage reference
- **CheckpointPlan**: Query interface; identifies tasks to trigger/wait-for/commit based on job topology

**Task-Side:**
- **CheckpointedInputGate**: Barrier interceptor; multiplexes barriers from network into handler
- **CheckpointBarrierHandler**: Alignment orchestrator; decides when to trigger checkpoint based on barrier pattern
- **BarrierHandlerState**: Alignment policy; encodes decision logic for blocking/releasing channels
- **SubtaskCheckpointCoordinator**: Snapshot coordinator; synchronizes state capture, channel state writing, acknowledgment

**Streaming Data Flow:**
- **Sources**: Inject CheckpointBarrier upon JobManager trigger
- **Intermediate Operators**: Hold barriers at output until aligned at all inputs (if aligned mode); snapshot state when barriers pass
- **Sinks**: Forward barriers to downstream; perform sink-specific commits upon completion notification

### Data Flow Description

**1. Trigger Flow**:
```
JobManager (CheckpointCoordinator)
  ↓ Create PendingCheckpoint + CheckpointStorageLocation
  ↓ triggerTasks() for each task in CheckpointPlan.getTasksToTrigger()
  ↓ Execution.triggerCheckpoint() → TaskManagerGateway RPC
  ↓
TaskManager (Injector)
  ↓ Injects CheckpointBarrier(checkpointId, timestamp, options) into InputGate
```

**2. Barrier Propagation Flow**:
```
Source Output → [CheckpointBarrier] → InputGate
  ↓ (pulled by) CheckpointedInputGate.getNextBufferOrEvent()
  ↓ (extracted) CheckpointBarrier event
  ↓ (routed to) CheckpointBarrierHandler.processBarrier()
  ↓ (state machine) BarrierHandlerState transitions
  ↓ (if aligned) Blocks other channels until all barriers received
  ↓ (when ready) notifyCheckpoint() → SubtaskCheckpointCoordinator
  ↓
Operator Snapshot
  ↓ snapshotState() → TaskStateSnapshot (all operator states)
  ↓ Emits CheckpointBarrier downstream to all outputs
  ↓
Downstream Operators
  ↓ (repeat barrier propagation and state snapshot)
  ↓
Sinks
```

**3. Acknowledgment Flow**:
```
Task (SubtaskCheckpointCoordinator)
  ↓ checkpointState() → TaskStateSnapshot
  ↓ Builds AcknowledgeCheckpoint message with state snapshot
  ↓ Sends RPC to JobManager
  ↓
JobManager (CheckpointCoordinator)
  ↓ receiveAcknowledgeMessage()
  ↓ PendingCheckpoint.acknowledgeTask() → merge state
  ↓ Check if isFullyAcknowledged()
  ↓ (if yes) completePendingCheckpoint()
```

**4. Finalization Flow**:
```
PendingCheckpoint.finalizeCheckpoint()
  ↓ Validates all tasks acknowledged
  ↓ Creates CheckpointMetadata (operators + master states)
  ↓ Serializes metadata to CheckpointStorageLocation
  ↓ Returns CompletedCheckpoint with external pointer
  ↓
CompletedCheckpointStore.addCheckpointAndSubsumeOldest()
  ↓ Persists completed checkpoint
  ↓ Removes old checkpoints exceeding retention policy
  ↓
sendAcknowledgeMessages() to TaskManager
  ↓ TaskManager notifies all operators: notifyCheckpointComplete()
  ↓ Operators perform side effect commits (e.g., Kafka commit offsets)
```

### Interface Contracts Between Components

**Execution → TaskManagerGateway**:
- Method: `triggerCheckpoint(ExecutionAttemptID, JobID, long checkpointId, long timestamp, CheckpointOptions)`
- Semantics: Fire-and-forget; TaskManager injects barrier into task's input channels

**CheckpointedInputGate → CheckpointBarrierHandler**:
- Method: `processBarrier(CheckpointBarrier, InputChannelInfo, boolean isRpcTriggered)`
- Semantics: Handler decides when to block/unblock channels and trigger checkpoint

**CheckpointBarrierHandler → Task (CheckpointableTask)**:
- Method: `triggerCheckpointOnBarrier(CheckpointMetaData, CheckpointOptions, CheckpointMetricsBuilder)`
- Semantics: Task begins state snapshot immediately; must complete synchronously for aligned mode

**Task (SubtaskCheckpointCoordinator) → JobManager (CheckpointCoordinator)**:
- Message: `AcknowledgeCheckpoint(JobID, ExecutionAttemptID, long checkpointId, CheckpointMetrics, TaskStateSnapshot)`
- Semantics: RPC reply containing captured state; JobManager uses to assemble final checkpoint

**Barrier Handler State → Controller (SingleCheckpointBarrierHandler)**:
- Method: `triggerGlobalCheckpoint(CheckpointBarrier)`, `initInputsCheckpoint(CheckpointBarrier)`, `allBarriersReceived()`
- Semantics: State machine queries context and requests actions on handler

### Aligned vs Unaligned Checkpoint Handling

**Aligned Checkpoints** (SingleCheckpointBarrierHandler with WaitingForFirstBarrier/CollectingBarriers):
- **Blocking**: Channels that have received barrier are blocked; hold data until all barriers received
- **Guarantee**: Exactly-once semantics; no duplicates or loss of data between checkpoints
- **Latency**: Higher; must wait for slowest input channel
- **Implementation**: `SingleCheckpointBarrierHandler.aligned()` factory creates aligned variant
- **State Transitions**: WaitingForFirstBarrier → CollectingBarriers → trigger → WaitingForFirstBarrier (next checkpoint)

**Unaligned Checkpoints** (SingleCheckpointBarrierHandler with AlternatingWaitingForFirstBarrierUnaligned):
- **Non-blocking**: Channels not blocked; data continues flowing
- **Capture In-flight**: Channel state writer captures data in-flight during barrier propagation
- **Guarantee**: Exactly-once semantics with less blocking via state capture
- **Latency**: Lower; triggered immediately upon first barrier
- **Implementation**: `SingleCheckpointBarrierHandler.unaligned()` factory creates unaligned variant
- **Channel State**: ChannelStateWriter writes in-flight buffers to checkpoint storage

**Alternating Mode** (AlternatingWaitingForFirstBarrier):
- **Adaptive**: Starts aligned; switches to unaligned if alignment timeout exceeded
- **Configuration**: alignedCheckpointTimeout determines timeout duration
- **Benefit**: Best-of-both; low latency when fast but preserves alignment when data flows evenly
- **Implementation**: Transitions between aligned and unaligned states based on timeout
- **Location**: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/SingleCheckpointBarrierHandler.java:168-188`

**At-Least-Once Tracking** (CheckpointBarrierTracker):
- **No Blocking**: Barriers never block; data flows freely
- **Loose Tracking**: Tracks barrier arrivals per checkpoint; no alignment
- **Guarantee**: At-least-once semantics; data may be duplicated
- **Use Case**: When exactly-once overhead unacceptable; source can replay
- **Implementation**: Counts barriers per ID; triggers when all channels have sent barrier
- **Location**: `/workspace/flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierTracker.java:59-161`

### PendingCheckpoint Lifecycle

**States**:
1. **Created**: `new PendingCheckpoint()` with all tasks in `notYetAcknowledgedTasks`
2. **In-Flight**: Tasks snapshot state, send `AcknowledgeCheckpoint` messages
3. **Tracking**: `acknowledgeTask()` removes tasks from notYetAcknowledgedTasks; state accumulated in `operatorStates`
4. **Ready**: `isFullyAcknowledged()` returns true when all tasks, coordinators, master states acknowledged
5. **Finalizing**: `finalizeCheckpoint()` serializes metadata and creates `CompletedCheckpoint`
6. **Disposed**: Marked disposed after finalization; state references released

**Acknowledgment-Based Completion**:
- Each `acknowledgeTask()` call checks: `if (checkpoint.isFullyAcknowledged()) completePendingCheckpoint()`
- Completion triggered by last acknowledgment arrival, not by timer
- Timeout exists only for aborting stalled checkpoints; success driven by acknowledgments
- Early completion: If task fails/finishes after checkpoint triggered, checkpoint can complete without all original tasks

**State Ownership**:
- During `finalizeCheckpoint()`: All operator states from all tasks merged into `Map<OperatorID, OperatorState>`
- Metadata serialization preserves full state lineage
- No state lost between PendingCheckpoint and CompletedCheckpoint
- CompletedCheckpoint immutable; holds serialized state handles only (no payloads)

---

## Summary

Flink's checkpoint coordination implements a distributed two-phase commit protocol where the JobManager's CheckpointCoordinator orchestrates barrier injection, task-side state snapshot collection through barrier propagation, and acknowledgment-driven completion. The architecture uses a state machine pattern for barrier handling, supporting three strategies: aligned (blocking for exactly-once), unaligned (non-blocking with channel state capture), and at-least-once tracking. The PendingCheckpoint accumulates task acknowledgments and state snapshots; once all tasks acknowledge, it finalizes into a CompletedCheckpoint with persisted metadata and external storage pointers. This design decouples the trigger phase (broadcast barriers) from the snapshot phase (capture operator states) from the commit phase (finalize and notify), enabling asynchronous, scalable checkpoint collection across distributed task graphs.
