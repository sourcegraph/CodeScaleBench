# Flink Checkpoint Coordination Architecture Analysis

## Files Examined

### JobManager/Coordinator Layer
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java** — Central coordinator that initiates checkpoints, manages PendingCheckpoints, and processes acknowledgments. Implements distributed two-phase commit protocol.
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/PendingCheckpoint.java** — Represents a checkpoint in-flight from initiation until all tasks acknowledge. Tracks acknowledgments and collects state from all tasks.
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CompletedCheckpoint.java** — Final persistent checkpoint after all tasks acknowledge and state is finalized. Stored in CheckpointStore for recovery.
- **flink-runtime/src/main/java/org/apache/flink/runtime/executiongraph/Execution.java** — Execution plan vertex that sends checkpoint trigger messages to TaskManagers via RPC (triggerCheckpoint method).

### Barrier Propagation & Handler Layer (Streaming)
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierHandler.java** — Abstract base for barrier processing. Tracks alignment timing and barrier metrics.
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/SingleCheckpointBarrierHandler.java** — Aligned checkpoint handler. Blocks input channels on barrier receipt until all barriers arrive (exactly-once semantics). Also supports unaligned checkpoints with configurable timeout.
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierTracker.java** — Unaligned checkpoint tracker. Does not block channels; simply tracks barriers for at-least-once semantics. Used when alignment is not required.
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointedInputGate.java** — Wraps input gates to intercept and process CheckpointBarrier events.

### Task-Level Coordination
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/SubtaskCheckpointCoordinatorImpl.java** — Coordinates state snapshot at individual task. Receives checkpoint trigger, broadcasts barrier downstream, collects operator states, and sends acknowledgments.
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskexecutor/TaskExecutor.java** — Receives checkpoint trigger RPC, forwards to Task for barrier injection and state snapshot.
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/StreamTask.java** — Streaming task that integrates with SubtaskCheckpointCoordinator for checkpoint execution.

### Response Path
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskmanager/CheckpointResponder.java** — Interface for sending checkpoint acknowledgments back to coordinator.
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskexecutor/rpc/RpcCheckpointResponder.java** — RPC implementation of CheckpointResponder, sends AcknowledgeCheckpoint messages.
- **flink-runtime/src/main/java/org/apache/flink/runtime/messages/checkpoint/AcknowledgeCheckpoint.java** — Message containing task state snapshot and checkpoint metadata.

### Storage & Cleanup
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CompletedCheckpointStore.java** — Persists completed checkpoints and manages shared state registry for incremental checkpoints.
- **flink-runtime/src/main/java/org/apache/flink/runtime/state/CheckpointStorageLocation.java** — Manages checkpoint storage paths and metadata.
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointsCleaner.java** — Asynchronous cleanup of discarded/subsumed checkpoint artifacts.

---

## Dependency Chain

### 1. Checkpoint Initiation
**Entry Point:** `CheckpointCoordinator.triggerCheckpoint(CheckpointType)`

**Flow:**
```
SchedulerBase.triggerCheckpoint(CheckpointType)
  ↓
CheckpointCoordinator.triggerCheckpoint(CheckpointType)
  └─ Creates CompletableFuture<CompletedCheckpoint> for external callers
```

### 2. Trigger Request Queuing & Planning
```
CheckpointCoordinator.triggerCheckpoint()
  ↓
CheckpointCoordinator.snapshotMasterState(PendingCheckpoint)
  └─ Invokes master hooks asynchronously (e.g., external systems)
  ↓
CheckpointCoordinator.triggerTasks(CheckpointTriggerRequest, ...)
  └─ Iterates over CheckpointPlan.getTasksToTrigger()
```

### 3. Task Trigger via RPC
```
CheckpointCoordinator.triggerTasks()
  ↓
For each Execution in checkpoint plan:
  Execution.triggerCheckpoint(checkpointId, timestamp, CheckpointOptions)
    └─ Sends RPC to TaskExecutor
```

### 4. TaskExecutor Receives Barrier Trigger
```
TaskExecutor.triggerCheckpoint(ExecutionAttemptID, checkpointId, options)
  └─ RPC handler
  ↓
Task.triggerCheckpointBarrier(checkpointId, timestamp, checkpointOptions)
  └─ Main task thread executes barrier injection
```

### 5. Barrier Injection at Task
```
SubtaskCheckpointCoordinatorImpl.checkpointAsync(metadata)
  ├─ Step (0): Abort previously aborted checkpoint if needed
  ├─ Step (1): prepareSnapshotPreBarrier() — Operators pre-barrier setup
  ├─ Step (2): **broadcastEvent(CheckpointBarrier)** — Inject barrier to downstream
  │            └─ ALL downstream tasks receive this barrier in input stream
  ├─ Step (3): registerAlignmentTimer() — For aligned→unaligned timeout
  ├─ Step (4): finishOutput() — If needed for channel state
  └─ Step (5): takeSnapshotSync() + finishAndReportAsync()
              └─ Collect operator state asynchronously
```

### 6. Barrier Propagation Through Data Stream
```
Downstream Task Receives:
  CheckpointedInputGate.pollNext()
    └─ Extracts CheckpointBarrier from input channels
    ↓
  CheckpointBarrier Handler.processBarrier(barrier, channelInfo)
    ├─ SingleCheckpointBarrierHandler (ALIGNED):
    │   └─ Blocks channel input until all channels have barrier
    │   └─ When all aligned: calls notifyCheckpoint(barrier)
    │
    └─ CheckpointBarrierTracker (UNALIGNED):
        └─ Tracks barrier without blocking
        └─ When all barriers seen: notifyCheckpoint(barrier)
```

### 7. State Snapshot & Acknowledgment
```
Task receives checkpoint notification from barrier handler:
  CheckpointBarrierHandler.notifyCheckpoint(barrier)
    ↓
  SubtaskCheckpointCoordinatorImpl.checkpointAsync()
    ├─ takeSnapshotSync() — Synchronous preparation
    │   └─ Call operator.snapshotState() for operator state
    │
    └─ finishAndReportAsync()
        ├─ Wait for async snapshots (async operators, state backend)
        ├─ Collect all OperatorSnapshotFutures into TaskStateSnapshot
        │
        └─ CheckpointResponder.acknowledgeCheckpoint(taskStateSnapshot)
            └─ RPC call back to CheckpointCoordinator
```

### 8. Acknowledgment Processing at Coordinator
```
CheckpointCoordinator.receiveAcknowledgeMessage(AcknowledgeCheckpoint)
  ├─ Retrieve PendingCheckpoint by checkpointId
  ├─ Register shared states from subtask snapshot
  │   └─ Needed for incremental checkpoint deduplication
  ├─ Call PendingCheckpoint.acknowledgeTask(executionAttemptID, subtaskState)
  │   └─ Accumulates state from all tasks
  │
  └─ If **PendingCheckpoint.isFullyAcknowledged()**:
      └─ CheckpointCoordinator.completePendingCheckpoint(pendingCheckpoint)
          ├─ PendingCheckpoint.finalizeCheckpoint()
          │   └─ Creates CompletedCheckpoint with all collected state
          │
          ├─ Store to CheckpointStore (persistent)
          │
          └─ sendAcknowledgeMessages() [Second Phase Commit]
              ├─ Execution.notifyCheckpointOnComplete()
              │   └─ Sends "commit" message to each task
              │
              └─ OperatorCoordinator.notifyCheckpointComplete()
                  └─ External coordinators (e.g., Kafka offsets)
```

### 9. Task-Level Completion Notification
```
Task receives notifyCheckpointOnComplete(completedCheckpointId):
  ↓
SubtaskCheckpointCoordinatorImpl.notifyCheckpointComplete()
  ↓
OperatorChain.notifyCheckpointComplete()
  ↓
Operator.notifyCheckpointComplete()
  └─ Finalizes operator-specific state (e.g., commit external sinks)
```

---

## Analysis

### Design Patterns Identified

#### 1. **Two-Phase Commit Distributed Protocol**
- **Phase 1 (Trigger & Prepare):** CheckpointCoordinator initiates, sends barrier to all tasks. Tasks snapshot state asynchronously and acknowledge.
- **Phase 2 (Commit):** Upon all acknowledgments, coordinator finalizes checkpoint and notifies all tasks to commit. Tasks run post-commit hooks (e.g., flush sinks).
- **Key invariant:** No task commits until all have snapshotted, ensuring consistency across distributed system.

#### 2. **Barrier-Based Synchronization**
- Barriers flow through the data stream like regular records, creating a logical "snapshot line."
- Barriers ensure causal ordering: all data before barrier at a task is included in checkpoint, all data after is not.
- **Unaligned vs. Aligned:**
  - **Aligned:** Block inputs at barrier until all channels caught up. Ensures lower checkpoint latency but may stall fast inputs.
  - **Unaligned:** Proceed without blocking, capture in-flight data. Higher latency but better throughput.

#### 3. **Incremental Checkpoint & Shared State Registry**
- Tasks report state handles (file references) rather than state data.
- Shared state (e.g., RocksDB SST files) registered in global registry to avoid duplication.
- Old checkpoints subsume newer ones; shared state kept until no checkpoint references it.

#### 4. **Asynchronous Snapshot with Future Composition**
- `OperatorSnapshotFutures` chains multiple async operations (operator state, key/value state, input channel state).
- Coordinator waits on `FutureUtils.ConjunctFuture` combining all task snapshot futures.
- Allows progress to continue while snapshots complete on background threads.

#### 5. **RPC-Based Distributed Messaging**
- JobManager↔TaskExecutor communication via Akka RPC.
- `ExecutionGraphHandler` marshals coordinator calls to IO executor to avoid blocking main thread.
- `CheckpointResponder` abstracts RPC transport for testing.

#### 6. **Decay-and-Discard Strategy**
- `PendingCheckpoint` maintained only while waiting for acknowledgments.
- Expired checkpoints kept in `recentExpiredCheckpoints` queue (size 16) to distinguish "late" from "invalid" acks.
- Completed checkpoints moved to persistent store immediately.

### Component Responsibilities

| Component | Responsibility |
|-----------|-----------------|
| **CheckpointCoordinator** | Orchestrates checkpoint initiation, aggregates acks, finalizes, manages lifecycle. |
| **PendingCheckpoint** | Holds in-flight checkpoint state, counts acks, tracks per-task metadata. |
| **CompletedCheckpoint** | Immutable snapshot of job state, stored persistently, used for recovery. |
| **Execution / TaskExecutor** | Delivery layer; sends barrier trigger RPC to task nodes. |
| **SubtaskCheckpointCoordinatorImpl** | Executes snapshot at task: injects barrier, collects operator state, sends ack. |
| **SingleCheckpointBarrierHandler** | Enforces aligned barrier receipt; gates input until all channels ready. |
| **CheckpointBarrierTracker** | Tracks unaligned barriers; no blocking, lower latency. |
| **CheckpointResponder** | Transport abstraction for sending task→coordinator acks. |
| **CheckpointStore** | Persistent checkpoint metadata and state reference storage. |

### Data Flow Description

1. **Trigger Phase:**
   - User or scheduler calls `CheckpointCoordinator.triggerCheckpoint()`.
   - Coordinator creates `PendingCheckpoint`, allocates checkpoint ID, assigns to tasks.

2. **Barrier Injection Phase:**
   - RPC trigger reaches TaskExecutor, forwarded to StreamTask.
   - `SubtaskCheckpointCoordinatorImpl.checkpointAsync()` injects `CheckpointBarrier` into output stream.
   - Barrier flows to all downstream tasks in parallel (fast, non-blocking at source).

3. **Barrier Reception & Alignment Phase:**
   - Downstream tasks receive barrier via `CheckpointedInputGate`.
   - **Aligned Mode:** `SingleCheckpointBarrierHandler` blocks inputs, waits for all channels.
   - **Unaligned Mode:** `CheckpointBarrierTracker` lets flow continue, just tracks receipt.
   - When ready, task notified to snapshot.

4. **Snapshot Phase:**
   - `SubtaskCheckpointCoordinatorImpl.checkpointAsync()` called on notification.
   - Operators synchronously prepare state (minimal work).
   - State backend asynchronously snapshots (user state, keyed state, etc.).
   - Channel state writer captures in-flight buffers (unaligned only).

5. **Acknowledgment Phase:**
   - All async operations complete; `TaskStateSnapshot` assembled.
   - `CheckpointResponder.acknowledgeCheckpoint(taskStateSnapshot)` sent to coordinator.
   - Coordinator receives in `receiveAcknowledgeMessage()`, registers shared state, increments ack count.

6. **Completion Phase:**
   - When all tasks ack, `completePendingCheckpoint()` invoked.
   - `PendingCheckpoint.finalizeCheckpoint()` creates `CompletedCheckpoint`.
   - Checkpoint persisted to store.
   - Second-phase commit: `sendAcknowledgeMessages()` notifies all tasks.

7. **Finalization Phase:**
   - Tasks receive `notifyCheckpointOnComplete()`, run post-commit hooks.
   - External coordinators (e.g., Kafka source) advance committed offsets.
   - Old checkpoints subsumed, artifacts cleaned up asynchronously.

### Aligned vs. Unaligned Checkpoint Handling

**SingleCheckpointBarrierHandler (Aligned):**
- **Strategy:** Block input channels upon barrier receipt until all channels present barrier.
- **Benefits:** Minimal in-flight data captured; lower state size; simpler semantics.
- **Trade-off:** May back-pressure fast inputs; higher checkpoint latency if inputs unbalanced.
- **Flow:**
  - Barrier received on channel N → mark aligned.
  - If not all channels aligned → pause this channel.
  - When all aligned → notify checkpoint, resume all channels.
  - **State:** Includes only committed data before barrier at all channels.

**CheckpointBarrierTracker (Unaligned):**
- **Strategy:** Do not block; track barriers independently per channel.
- **Benefits:** No blocking, minimal impact on throughput; lower latency.
- **Trade-off:** In-flight data between barriers captured; larger state size.
- **Flow:**
  - Barrier received on any channel → increment counter for this checkpoint.
  - If counter == all channels → notify checkpoint.
  - **State:** Includes all data up to barrier at each channel independently (may be unaligned).

**Mixed Mode (Alternating with Timeout):**
- Start aligned (low latency).
- If timeout reached and all barriers not received, switch to unaligned (skip stragglers).
- Registered via `BarrierAlignmentUtil.registerTask()` with timer callback.

### PendingCheckpoint Lifecycle

1. **Created:** In `CheckpointCoordinator.createPendingCheckpoint()`.
2. **Initialized:** Timeout scheduled; added to `pendingCheckpoints` map.
3. **Acknowledged:** As `acknowledgeTask()` called per task. If duplicate, ignored.
4. **Fully Acknowledged:** When `isFullyAcknowledged()` returns true (all required tasks acked).
5. **Finalized:** `finalizeCheckpoint()` creates `CompletedCheckpoint`, writes metadata.
6. **Disposed:** After finalization or on timeout; removed from `pendingCheckpoints`.
7. **Subsumed:** New completed checkpoint subsumes older one; older one cleaned up asynchronously.

**Thread Safety:** PendingCheckpoint is **not** thread-safe. All accesses guarded by `CheckpointCoordinator.lock`.

### Interface Contracts

**Between Coordinator and Task:**
- **RPC Method:** `TaskExecutor.triggerCheckpoint(attemptId, checkpointId, options)`
- **Contract:** Task must inject barrier, snapshot state, and call `acknowledgeCheckpoint()` with result.
- **Timeout:** Coordinator cancels after `checkpointTimeout` ms.

**Between Task and Coordinator (Return Path):**
- **RPC Method:** `CheckpointCoordinatorGateway.acknowledgeCheckpoint(jobId, attemptId, checkpointId, subtaskState)`
- **Contract:** Task must include all state handles and metrics (alignment time, size, etc.).
- **Semantics:** Acknowledgment is **idempotent**; duplicates ignored by PendingCheckpoint.

**Between Coordinator and External Store:**
- **Interface:** `CompletedCheckpointStore`
- **Methods:** `addCheckpointAndSubsumeOldestOne(checkpoint, cleaner)`, `getLatestCheckpoint()`, `getLatestCheckpointId()`
- **Semantics:** Checkpoints are persisted; queries must handle consistency (e.g., HDFS eventual consistency).

**Between Operator and Coordinator:**
- **Interface:** `OperatorCoordinator.checkpointCoordinator(checkpointId, resultFuture)`
- **Contract:** Coordinator-side operators snapshot state into resultFuture. Called during trigger phase (Phase 1).
- **Lifecycle:** `resetToCheckpoint()` called on recovery; `notifyCheckpointComplete()` on commit (Phase 2).

---

## Summary

Flink's checkpoint coordination implements a **barrier-based distributed two-phase commit protocol** at scale:

1. **Trigger Phase:** CheckpointCoordinator injects barrier via RPC. Barriers flow through data stream, synchronizing snapshot across all tasks without centralized blocking.

2. **Snapshot & Alignment:** StreamTasks handle barriers through pluggable handlers (aligned vs. unaligned), allowing trade-offs between latency and throughput. State is snapshotted asynchronously while data continues flowing.

3. **Acknowledgment & Completion:** Tasks return state snapshots; coordinator waits for all acks in PendingCheckpoint. Upon completion, checkpoint is finalized, persisted, and all tasks notified to commit hooks.

4. **Design Elegance:** By embedding synchronization in the data stream itself (barriers), Flink avoids centralized coordination bottlenecks. Asynchronous snapshot collection and RPC-based two-phase commit enable fault tolerance without stalling computation. Incremental snapshots and shared state registry minimize storage overhead.

This architecture scales to thousands of parallel tasks, supporting both low-latency (aligned) and high-throughput (unaligned) checkpoint modes in the same framework.
