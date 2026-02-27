# Flink Checkpoint Coordination Architecture

## Files Examined

### Core Checkpoint Coordination (JobManager-side)
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java** — JobManager-side coordinator that orchestrates the entire checkpoint lifecycle, including triggering checkpoints, dispatching RPC messages to task executors, receiving acknowledgments, and finalizing completed checkpoints.
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/PendingCheckpoint.java** — Represents a checkpoint in-flight (started but not yet acknowledged by all tasks). Tracks task acknowledgments and holds operator state handles until completion.
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CompletedCheckpoint.java** — Represents a successfully completed checkpoint with all operator state metadata persisted. Immutable once created and stored in the checkpoint store.

### Checkpoint Barrier Definition
- **flink-runtime/src/main/java/org/apache/flink/runtime/io/network/api/CheckpointBarrier.java** — Event class that represents the checkpoint barrier. Travels with data through the stream, marking the boundary between pre-checkpoint and post-checkpoint data.

### RPC Dispatch and Task Triggering
- **flink-runtime/src/main/java/org/apache/flink/runtime/executiongraph/Execution.java** — Execution vertex wrapper that provides RPC gateway to task managers. `triggerCheckpoint()` sends checkpoint messages to remote task executors.
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskexecutor/TaskExecutor.java** — Remote task manager that receives checkpoint RPC calls and invokes local task trigger methods.
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskmanager/Task.java** — Local task instance that receives checkpoint barrier triggers and delegates to the invokable (streaming task).

### Barrier Handler Implementations (Task-side)
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierHandler.java** — Abstract base class for barrier processing. Defines common interface for handling checkpoint barriers, including barrier reception, alignment tracking, and checkpoint notification.
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/SingleCheckpointBarrierHandler.java** — Handles aligned checkpoints (default mode). Blocks input channels when barriers arrive until all barriers are received for a checkpoint, ensuring strict alignment.
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierTracker.java** — Handles unaligned checkpoints (at-least-once mode). Does not block channels; instead tracks barrier arrivals and triggers checkpoints once all barriers from all input channels have been observed.

### Acknowledgment and Completion
- **flink-runtime/src/main/java/org/apache/flink/runtime/messages/checkpoint/AcknowledgeCheckpoint.java** — RPC message sent from task executors back to job manager acknowledging checkpoint completion with operator state.
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskmanager/CheckpointResponder.java** — Task-side interface for sending checkpoint acknowledgments and decline messages back to the coordinator.
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskexecutor/rpc/RpcCheckpointResponder.java** — RPC implementation of CheckpointResponder that sends acknowledgments to the CheckpointCoordinator.

## Dependency Chain

### Phase 1: Checkpoint Trigger (CheckpointCoordinator → Task Executors)

```
1. Entry point: CheckpointCoordinator.triggerCheckpoint(CheckpointType)
   └─ flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:619

2. Initiates async state preparation:
   └─ startTriggeringCheckpoint()
      └─ Calculates CheckpointPlan
      └─ Creates PendingCheckpoint
      └─ Triggers OperatorCoordinator checkpoints
      └─ Snapshots master state
      └─ Calls triggerCheckpointRequest()

3. Dispatches to task executors:
   └─ triggerTasks()  [line 836]
      └─ For each Execution in CheckpointPlan.getTasksToTrigger():
         └─ execution.triggerCheckpoint(checkpointId, timestamp, checkpointOptions)
            └─ flink-runtime/src/main/java/org/apache/flink/runtime/executiongraph/Execution.java:1070

4. RPC dispatch to remote task executor:
   └─ Execution.triggerCheckpointHelper()  [line 1088]
      └─ taskManagerGateway.triggerCheckpoint(attemptId, jobId, checkpointId, timestamp, checkpointOptions)
         └─ Serializes and sends RPC message to TaskExecutor

5. Remote task executor receives trigger:
   └─ TaskExecutor.triggerCheckpoint()
      └─ flink-runtime/src/main/java/org/apache/flink/runtime/taskexecutor/TaskExecutor.java:1082
      └─ Locates local Task instance
      └─ Calls task.triggerCheckpointBarrier()

6. Local task receives trigger:
   └─ Task.triggerCheckpointBarrier()
      └─ flink-runtime/src/main/java/org/apache/flink/runtime/taskmanager/Task.java:1360
      └─ Creates CheckpointMetaData from parameters
      └─ Verifies task is in RUNNING state
      └─ Calls invokable.triggerCheckpointAsync()  [invokable is CheckpointableTask]
```

### Phase 2: Barrier Injection and Flow Through Stream

```
7. Task invokable (typically StreamTask/SourceTask) receives async trigger:
   └─ CheckpointableTask.triggerCheckpointAsync()
      └─ For sources: Creates CheckpointBarrier and injects into output data stream
      └─ For non-sources: Queued for processing when barrier arrives

8. Barrier propagates through network:
   └─ CheckpointBarrier travels through:
      └─ Task's output buffers
      └─ Network channels
      └─ Input queues of downstream tasks

9. Downstream task receives barrier from input channel:
   └─ CheckpointBarrierHandler.processBarrier()
      └─ flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierHandler.java:94
      └─ Input: CheckpointBarrier, InputChannelInfo, isRpcTriggered flag
```

### Phase 3a: Aligned Checkpoint Processing (Default)

```
10. SingleCheckpointBarrierHandler processes barrier:
    └─ SingleCheckpointBarrierHandler.processBarrier()
       └─ flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/SingleCheckpointBarrierHandler.java:213
       └─ Checks if barrier is newer than current checkpoint
       └─ If first barrier for checkpoint ID:
          └─ Blocks the input channel that sent this barrier
          └─ Pauses consumption from that channel
       └─ Waits for barriers from ALL input channels
       └─ Once all barriers received:
          └─ Calls triggerCheckpoint()  [line 281]
             └─ Calls notifyCheckpoint(barrier)

11. Notifies task of checkpoint:
    └─ CheckpointBarrierHandler.notifyCheckpoint()
       └─ flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierHandler.java:125
       └─ Creates CheckpointMetaData
       └─ Collects alignment metrics (duration, bytes processed)
       └─ Calls toNotifyOnCheckpoint.triggerCheckpointOnBarrier()
          └─ toNotifyOnCheckpoint is the StreamTask
```

### Phase 3b: Unaligned Checkpoint Processing (Optional)

```
10. CheckpointBarrierTracker processes barrier:
    └─ CheckpointBarrierTracker.processBarrier()
       └─ flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierTracker.java:94
       └─ Does NOT block input channels
       └─ Tracks barrier arrival count per checkpoint ID
       └─ Once barriers received from all channels for a checkpoint:
          └─ Calls triggerCheckpointOnAligned()
             └─ Calls notifyCheckpoint(barrier)
             └─ Same as aligned case from here on
```

### Phase 4: State Snapshot at Task

```
12. StreamTask.triggerCheckpointOnBarrier():
    └─ flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/StreamTask.java:1395
    └─ Delegates to SubtaskCheckpointCoordinator.checkpointState()
       └─ Asynchronously calls snapshotState() on all operators in chain
       └─ Captures operator state (keyed state, operator state)
       └─ Returns TaskStateSnapshot with all state handles

13. Operator state is snapshotted:
    └─ Each operator's snapshotState() is called by the checkpoint coordinator thread
    └─ State is persisted to checkpoint storage location
    └─ State handles (references to persisted state) are returned to PendingCheckpoint
```

### Phase 5: Acknowledgment Flow (Task → JobManager)

```
14. After state snapshot completes, task acknowledges:
    └─ Environment.acknowledgeCheckpoint()
       └─ flink-runtime/src/main/java/org/apache/flink/runtime/execution/Environment.java:341
       └─ Calls checkpointResponder.acknowledgeCheckpoint()
          └─ flink-runtime/src/main/java/org/apache/flink/runtime/taskmanager/CheckpointResponder.java:42

15. CheckpointResponder sends RPC acknowledgment:
    └─ RpcCheckpointResponder.acknowledgeCheckpoint()
       └─ flink-runtime/src/main/java/org/apache/flink/runtime/taskexecutor/rpc/RpcCheckpointResponder.java:44
       └─ Creates AcknowledgeCheckpoint message with:
          └─ JobID, ExecutionAttemptID, checkpointId
          └─ TaskStateSnapshot (operator states)
          └─ CheckpointMetrics (alignment duration, bytes)
       └─ Sends RPC message to CheckpointCoordinator

16. JobManager receives acknowledgment:
    └─ CheckpointCoordinator.receiveAcknowledgeMessage()
       └─ flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:1210
       └─ Retrieves PendingCheckpoint by ID
       └─ Calls checkpoint.acknowledgeTask()
          └─ flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/PendingCheckpoint.java
          └─ Registers task in acknowledged set
          └─ Stores TaskStateSnapshot in operatorStates
          └─ Returns TaskAcknowledgeResult (SUCCESS, DUPLICATE, UNKNOWN, DISCARDED)
```

### Phase 6: Checkpoint Completion (Two-Phase Commit)

```
17. CheckpointCoordinator checks if fully acknowledged:
    └─ checkpoint.isFullyAcknowledged()
       └─ flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/PendingCheckpoint.java:238
       └─ Returns: areTasksFullyAcknowledged() AND
                   areCoordinatorsFullyAcknowledged() AND
                   areMasterStatesFullyAcknowledged()

18. If fully acknowledged, complete pending checkpoint:
    └─ CheckpointCoordinator.completePendingCheckpoint()
       └─ flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:1365
       └─ Calls checkpoint.finalizeCheckpoint()
          └─ flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/PendingCheckpoint.java:317
          └─ Combines all operator states into checkpoint metadata
          └─ Writes CheckpointMetadata to persistent storage
          └─ Obtains CompletedCheckpointStorageLocation
          └─ Returns CompletedCheckpoint object

19. Add completed checkpoint to store:
    └─ addCompletedCheckpointToStoreAndSubsumeOldest()
       └─ flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:1510
       └─ Adds CompletedCheckpoint to CompletedCheckpointStore
       └─ Subsumes/removes older checkpoints
       └─ Registers shared states in SharedStateRegistry

20. Notify all tasks of checkpoint completion:
    └─ sendAcknowledgeMessages()
       └─ flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java:1439
       └─ Sends NotifyCheckpointComplete RPC to all tasks
       └─ Tasks receive and call notifyCheckpointComplete()
       └─ Allows tasks to clean up temporary state (unaligned checkpoint buffers, etc.)
```

## Analysis

### Architecture Overview

The Flink checkpoint coordination system implements a **distributed two-phase commit protocol**:
- **Phase 1 (Checkpoint Trigger)**: JobManager initiates checkpoint by broadcasting trigger messages to all tasks
- **Phase 2 (Acknowledge & Finalize)**: Tasks snapshot state and acknowledge, JobManager collects acknowledgments and finalizes when all received

The architecture separates concerns into distinct layers:

### 1. **Coordinator Layer (JobManager)**
`CheckpointCoordinator` is the single point of orchestration. It:
- **Triggers**: Uses `CheckpointPlan` to identify which tasks must participate
- **Dispatches**: Sends RPC messages via `Execution` objects to `TaskExecutor` instances
- **Aggregates**: Collects acknowledgments in `PendingCheckpoint`
- **Finalizes**: Converts `PendingCheckpoint` to `CompletedCheckpoint` once all acknowledgments arrive
- **Persists**: Stores completed checkpoint metadata to external storage

Key design patterns:
- **Asynchronous execution**: Checkpoint triggering is non-blocking; coordinator continues while tasks snapshot
- **Locking**: Coordinator uses `synchronized(lock)` to guard checkpoint collection access
- **Futures**: Asynchronous operations tracked with `CompletableFuture` chains

### 2. **Barrier Injection Layer (Source Tasks)**
Source tasks (e.g., `SourceTask`, `KafkaSourceTask`) are **special**: they must:
- Receive the async `triggerCheckpointAsync()` call from the coordinator
- Inject a `CheckpointBarrier` into the output stream **in order** with data
- This ensures data sent before the barrier is checkpoint N and data after is checkpoint N+1

For non-source tasks, barriers arrive naturally from upstream, so no explicit injection is needed.

### 3. **Barrier Propagation Layer (Network & Streaming)**
`CheckpointBarrier` objects flow through:
- Task output buffers (serialized as part of the network data)
- Network channels and queues
- Task input gates and channels

The barrier travels **in-order** with data, maintaining strict causality: all data that was produced before the barrier is considered "in the checkpoint", and all data after is "in the next checkpoint".

### 4. **Barrier Handling Layer (Task-side Checkpoint Coordination)**
Two implementations of `CheckpointBarrierHandler` provide different semantics:

#### **SingleCheckpointBarrierHandler (Aligned Checkpoints)**
- **Semantics**: Exactly-once processing guarantees
- **Mechanism**:
  1. Upon receiving a barrier from channel i, **block** (pause consumption from) that channel
  2. **Wait** for barriers from all other input channels
  3. Once barriers received from all channels, **resume** all channels
  4. Trigger the checkpoint
- **Cost**: Higher latency (blocked channels wait for slowest upstream task)
- **Benefit**: Ensures all tasks see a consistent global checkpoint point across all input edges

#### **CheckpointBarrierTracker (Unaligned Checkpoints)**
- **Semantics**: At-least-once processing (with backup state in buffers)
- **Mechanism**:
  1. Do **not** block channels
  2. **Track** which channels have sent a barrier for each checkpoint ID
  3. When all channels have sent barriers for checkpoint ID X, trigger checkpoint X
- **Cost**: Tasks may process data from multiple logical checkpoints concurrently; state buffers must be persisted
- **Benefit**: Lower latency (channels never blocked, checkpoint triggered sooner)

The **state machine** within barrier handlers tracks:
- Current checkpoint ID
- Which channels have sent barriers
- Whether alignment is complete
- Timeout handling (if barrier doesn't arrive quickly, escalate to unaligned checkpoint)

### 5. **State Snapshot Layer (Operator Coordination)**
When a barrier reaches a task:
1. The `CheckpointBarrierHandler.notifyCheckpoint()` calls `task.triggerCheckpointOnBarrier()`
2. The task's `SubtaskCheckpointCoordinator` asynchronously calls each **operator's `snapshotState()`**
3. Operators capture their internal state:
   - **Keyed state**: Via `StateBackend.snapshotPartitionedState()`
   - **Operator state**: Via operator's `snapshotState(CheckpointedSnapshotScope)`
4. State is written to temporary storage locations
5. State handles (references) are returned as `OperatorSubtaskState`
6. After all operators complete, task **acknowledges** back to the coordinator

Key coordination: **State snapshot happens in order** because operators process barriers in order, maintaining causality.

### 6. **Acknowledgment & Completion Layer (RPC & Aggregation)**
- **Task acknowledges**: Each task sends `AcknowledgeCheckpoint` RPC with its operator state snapshots
- **Coordinator aggregates**: `PendingCheckpoint.acknowledgeTask()` records the acknowledgment
- **Two-phase commit completion**:
  - **Phase 1**: Task state snapshot (asynchronous, decoupled from coordinator)
  - **Phase 2**: Coordinator finalization (synchronous point when all acks received)
    - Merges all operator states into `CheckpointMetadata`
    - Writes metadata to persistent storage
    - Creates `CompletedCheckpoint` (immutable, recoverable)
    - Notifies all tasks: checkpoint committed

### 7. **Exactly-Once vs At-Least-Once Trade-off**

**Exactly-Once (Aligned Checkpoints)**:
- Requires all barriers to align (all input channels have sent the barrier before continuing)
- Guarantees: All data in checkpoint N comes from the same logical "instant"
- Cost: Latency spike when one upstream is slow
- Implementation: `SingleCheckpointBarrierHandler.processBarrier()` blocks channels

**At-Least-Once (Unaligned Checkpoints)**:
- Allows barriers to arrive at different times; continues processing
- Guarantees: Checkpoint includes at least all data up to the first barrier; may include data from next checkpoint
- To recover correctly: State buffer (unaligned state) stored with checkpoint records pre-barrier data that was processed post-barrier
- Benefit: Lower latency, no blocking
- Implementation: `CheckpointBarrierTracker.processBarrier()` does not block; triggers when all have arrived

### 8. **Key Interfaces & Contracts**

**CheckpointableTask** (implemented by `StreamTask`):
- `triggerCheckpointAsync(CheckpointMetaData, CheckpointOptions)`: Async trigger for sources
- `triggerCheckpointOnBarrier(CheckpointMetaData, CheckpointOptions, CheckpointMetricsBuilder)`: Barrier-triggered checkpoint for non-sources
- `abortCheckpointOnBarrier(long checkpointId, CheckpointException)`: Abort signal

**CheckpointResponder** (implemented by tasks to send acks):
- `acknowledgeCheckpoint(JobID, ExecutionAttemptID, long checkpointId, CheckpointMetrics, TaskStateSnapshot)`

**CheckpointCoordinatorGateway** (implemented by `CheckpointCoordinator`):
- `acknowledgeCheckpoint(JobID, ExecutionAttemptID, long checkpointId, CheckpointMetrics, TaskStateSnapshot)`: Receive ack
- `declineCheckpoint(JobID, ExecutionAttemptID, long checkpointId, CheckpointException)`: Receive decline

### 9. **Failure Handling**

**Task Declines Checkpoint**:
- Task calls `CheckpointResponder.declineCheckpoint()`
- Coordinator receives `DeclineCheckpoint` message
- Coordinator calls `abortPendingCheckpoint()`
- Clears state, increments failure counter
- Failure manager decides whether to trigger next checkpoint or abort job

**Timeout Handling**:
- `PendingCheckpoint` is scheduled with a cancellation timer (default 10min)
- If checkpoint not acknowledged by timeout, automatically aborted
- Prevents resource leaks (pending state handles)

**Coordinator Failure**:
- All persistent state in `CompletedCheckpointStore` (e.g., HDFS, file system)
- On restart, `CheckpointCoordinator` loads latest completed checkpoints
- Tasks can restore from last completed checkpoint
- In-flight `PendingCheckpoint` objects are lost but re-triggered

## Summary

Flink's checkpoint coordination implements a **distributed asynchronous snapshot mechanism** using checkpoint barriers as logical markers of snapshot boundaries. The `CheckpointCoordinator` on the JobManager orchestrates the distributed two-phase commit: it triggers barriers to be injected at sources, waits for barriers to flow through the task graph, collects acknowledgments with state snapshots from all tasks, and finalizes the checkpoint by writing persistent metadata. Two modes—aligned (exactly-once) and unaligned (at-least-once)—balance between consistency guarantees and latency, with `SingleCheckpointBarrierHandler` blocking channels for alignment and `CheckpointBarrierTracker` tracking arrivals without blocking. Upon full acknowledgment, `PendingCheckpoint` is converted to `CompletedCheckpoint`, metadata is persisted, and tasks are notified of completion, implementing a robust exactly-once or at-least-once processing guarantee depending on configuration.
