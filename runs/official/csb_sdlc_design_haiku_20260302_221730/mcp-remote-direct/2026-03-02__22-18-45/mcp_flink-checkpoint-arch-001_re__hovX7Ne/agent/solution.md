# Flink Checkpoint Coordination Architecture Analysis

## Files Examined

### JobManager-Side Checkpoint Coordination
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java** — Central coordinator for distributed checkpoints. Manages checkpoint lifecycle, triggers barriers via RPC to task executors, collects acknowledgments, and coordinates two-phase commit
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/PendingCheckpoint.java** — Represents in-flight checkpoint state tracking. Maintains maps of awaited task acknowledgments, collects TaskStateSnapshot from tasks, and provides completion promise once all tasks acknowledge
- **flink-runtime/src/main/java/org/apache/flink/runtime/executiongraph/Execution.java** — Task execution wrapper. Dispatches checkpoint trigger RPC to TaskExecutor via TaskManagerGateway

### Barrier Event and Options
- **flink-runtime/src/main/java/org/apache/flink/runtime/io/network/api/CheckpointBarrier.java** — Immutable barrier event carrying checkpoint ID, timestamp, and CheckpointOptions. Injected into data stream by source/upstream tasks to mark checkpoint boundary

### Task-Side Barrier Handling
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/SingleCheckpointBarrierHandler.java** — Primary barrier handler for aligned and unaligned checkpoints. Tracks barrier arrival from input channels, triggers state snapshot when all barriers received, manages barrier alignment timeout state machine
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/CheckpointBarrierTracker.java** — Simpler barrier tracker for at-least-once semantics. Does not block channels; immediately marks checkpoint complete upon receiving all barriers. Used when exactly-once not required
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/io/checkpointing/BarrierHandlerState.java** — State machine interface for barrier alignment behavior (aligned, unaligned, alternating)

### Task State Checkpoint Coordination
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/SubtaskCheckpointCoordinator.java** — Coordinates checkpoint execution on task side. Responsible for: (1) initializing input checkpoint state, (2) snapshotting operator state asynchronously, (3) reporting snapshot to JobManager via CheckpointResponder
- **flink-runtime/src/main/java/org/apache/flink/streaming/runtime/tasks/StreamTask.java** — Streaming task execution wrapper. Implements CheckpointableTask interface. Receives barrier notification from CheckpointBarrierHandler, coordinates with SubtaskCheckpointCoordinator to perform snapshot
- **flink-runtime/src/main/java/org/apache/flink/runtime/state/TaskStateManagerImpl.java** — Manages state backend access and checkpoint responder callbacks for reporting acknowledgments

### Acknowledgment Path
- **flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinatorGateway.java** — RPC gateway interface defining acknowledgeCheckpoint() and reportCheckpointMetrics() methods
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskmanager/CheckpointResponder.java** — Interface for task-side to report checkpoint completion. Delegated to via RPC from TaskStateManager
- **flink-runtime/src/main/java/org/apache/flink/runtime/taskexecutor/rpc/RpcCheckpointResponder.java** — RPC implementation of CheckpointResponder. Routes acknowledgments back to CheckpointCoordinator via JobMasterGateway
- **flink-runtime/src/main/java/org/apache/flink/runtime/scheduler/ExecutionGraphHandler.java** — Handler receiving acknowledgeCheckpoint RPC calls. Delegates to CheckpointCoordinator.receiveAcknowledgeMessage()

---

## Dependency Chain

### 1. Checkpoint Trigger Initiation
**Entry point:** `CheckpointCoordinator.triggerCheckpoint(CheckpointProperties)`
**Location:** CheckpointCoordinator.java:600-800

Flow:
1. CheckpointCoordinator validates checkpoint preconditions and computes checkpoint plan
2. Allocates new checkpoint ID via CheckpointIDCounter (thread-safe, ZooKeeper-backed if HA-enabled)
3. Creates PendingCheckpoint with maps of awaited tasks and operator coordinators
4. Registers timeout handler via ScheduledExecutor to abort checkpoint after timeout
5. Asynchronously triggers OperatorCoordinator checkpoints (external sources, etc.)
6. Asynchronously snaps MasterTriggerRestoreHooks state
7. Upon coordinator/master completion, proceeds to triggerTasks()

### 2. Barrier Injection to Source Tasks
**Method:** `CheckpointCoordinator.triggerTasks()`
**Location:** CheckpointCoordinator.java:836-868

Flow:
1. Iterates over CheckpointPlan.getTasksToTrigger() (typically source vertices)
2. For each task Execution, calls `execution.triggerCheckpoint(checkpointId, timestamp, checkpointOptions)`
3. Execution.triggerCheckpointHelper() retrieves assigned LogicalSlot and TaskManagerGateway
4. Dispatches RPC to TaskExecutor: `taskManagerGateway.triggerCheckpoint(executionAttemptId, jobId, checkpointId, timestamp, checkpointOptions)`
5. TaskExecutor receives via RpcTaskManagerGateway, forwards to Task.triggerCheckpointAsync()
6. Task/StreamTask receives barrier trigger, delegates to CheckpointBarrierHandler (barrier handlers do NOT handle this RPC, instead barriers are sent in-band through network)

**Critical Design Note:** While CheckpointCoordinator triggers tasks via RPC, the actual CheckpointBarrier events are injected into the data stream **in-band** by source operators. Sources receive the trigger RPC and begin emitting barriers downstream in their regular data flow.

### 3. Barrier Propagation Through Task Graph
**Barrier Event Class:** CheckpointBarrier (immutable event carrying ID, timestamp, CheckpointOptions)

Flow for intermediate/sink tasks:
1. StreamInputProcessor reads from InputGate
2. When barrier event received, InputGate delivers to CheckpointBarrierHandler (not through RPC)
3. Barrier handler processes via one of two strategies:

   **Option A - SingleCheckpointBarrierHandler (Aligned):**
   - Tracks barrier arrival from each input channel
   - Blocks data processing on channels that haven't sent barrier (maintains alignment)
   - When all barriers received from all channels: calls notifyCheckpoint()
   - Notifies StreamTask to trigger state snapshot

   **Option B - CheckpointBarrierTracker (Unaligned/At-Least-Once):**
   - Does not block channels
   - Tracks barriers received per checkpoint ID
   - Immediately notifies checkpoint complete when all barriers seen
   - Task processes data out-of-order; in-flight data not part of checkpoint

### 4. State Snapshot at Operator
**Method:** `StreamTask.triggerCheckpointOnBarrier(CheckpointMetaData, CheckpointOptions, CheckpointMetricsBuilder)`
**Location:** StreamTask.java:1396-1422

Flow:
1. StreamTask.triggerCheckpointOnBarrier() called by barrier handler
2. Delegates to `subtaskCheckpointCoordinator.checkpointState()`
3. SubtaskCheckpointCoordinator (typically AsyncCheckpointRunnable-based):
   - Calls OperatorChain to snapshot all operators in the task
   - Passes StateBackend for state persistence (RocksDB, in-memory, etc.)
   - Collects TaskStateSnapshot with state handles for all operators
4. Snapshot performed asynchronously (does not block data processing)
5. Upon completion, reports via CheckpointResponder

### 5. Acknowledgment and Completion
**Method:** `CheckpointCoordinator.receiveAcknowledgeMessage(AcknowledgeCheckpoint, String)`
**Location:** CheckpointCoordinator.java:1210-1310

Flow:
1. Task completes state snapshot, calls `checkpointResponder.acknowledgeCheckpoint(jobId, executionAttemptId, checkpointId, checkpointMetrics, taskStateSnapshot)`
2. RpcCheckpointResponder routes RPC call to JobMaster: `jobMaster.acknowledgeCheckpoint(jobId, executionAttemptId, checkpointId, checkpointMetrics, taskStateSnapshot)`
3. JobMaster.acknowledgeCheckpoint() delegates to ExecutionGraphHandler
4. ExecutionGraphHandler.acknowledgeCheckpoint() calls `checkpointCoordinator.receiveAcknowledgeMessage()`
5. CheckpointCoordinator (lock-protected):
   - Looks up PendingCheckpoint by ID
   - Calls `pendingCheckpoint.acknowledgeTask(executionAttemptId, taskStateSnapshot, checkpointMetrics)`
   - PendingCheckpoint removes executionAttemptId from notYetAcknowledgedTasks map
   - Stores TaskStateSnapshot in OperatorState hierarchy
   - Updates statistics (alignment duration, bytes persisted, etc.)
6. If checkpoint now fully acknowledged (all tasks + coordinators + master states):
   - Calls `completePendingCheckpoint(checkpoint)`
   - Finalizes checkpoint: writes metadata to CheckpointStorage
   - Creates CompletedCheckpoint instance
   - Stores in CompletedCheckpointStore (e.g., Zookeeper for HA)
   - Completes onCompletionPromise future
   - Broadcasts CheckpointCompletedNotification to all operators

---

## Design Patterns and Component Relationships

### Two-Phase Commit Protocol
1. **Phase 1 (Commit Phase):** CheckpointCoordinator triggers barriers; barriers propagate through graph; tasks snapshot state
2. **Phase 2 (Commit Confirmation):** Tasks acknowledge with state; once all acknowledge, checkpoint atomically committed to durable storage
- Atomic commitment: CompletedCheckpoint only created after all acknowledges received
- Failure handling: Timeout aborts PendingCheckpoint; DeclineCheckpoint message also triggers abort
- Consistency: Shared state registration happens before checkpoint completion to handle rescaling

### Barrier Alignment State Machine (SingleCheckpointBarrierHandler)
States track checkpoint lifecycle at intermediate tasks:
- **WaitingForFirstBarrier:** Idle state, no checkpoint pending
- **AlignedCheckpointInProgress:** Collecting barriers from all channels, blocking data
- **UnalignedCheckpointInProgress:** Collecting barriers, not blocking (if unaligned enabled)
- **TimeoutAfterBarrierReceived:** Alignment timed out; switch to unaligned if enabled

Transitions triggered by:
- Barrier arrival: update barrier count, check alignment completion
- Alignment timeout: switch to unaligned (if alternating checkpoints enabled)
- CancelCheckpointMarker: abort pending checkpoint

### Input Channel Blocking and Data Ordering
**Aligned Checkpoint:** SingleCheckpointBarrierHandler blocks data on channels that sent barriers until all send. Preserves exactly-once semantics with ordered processing.

**Unaligned Checkpoint:** No blocking; processes data out-of-order. Faster checkpoint but relaxes ordering to at-least-once for in-flight data.

### Shared State Registration
During acknowledgeTask:
- TaskStateSnapshot extracted from AcknowledgeCheckpoint message
- Shared states registered to CompletedCheckpointStore.getSharedStateRegistry()
- Enables reference counting for state files (shared across subtasks/rescaling)
- State cleanup deferred until checkpoint subsumed by newer checkpoint

### PendingCheckpoint Lifecycle
1. **Created:** CheckpointCoordinator.createPendingCheckpoint()
2. **Timeout scheduled:** Timer set to abort if not completed within checkpointTimeout
3. **Task acknowledgments collected:** PendingCheckpoint.acknowledgeTask() removes from notYetAcknowledgedTasks
4. **Fully acknowledged:** All tasks, coordinators, master states acknowledged
5. **Finalized:** metadata written; CompletedCheckpoint created; stored in CompletedCheckpointStore
6. **Disposed:** Old checkpoints cleaned up; subsumed by newer checkpoint

---

## Architectural Insights

### Separation of Concerns
- **CheckpointCoordinator:** Global checkpoint orchestration, RPC dispatch, aggregation
- **PendingCheckpoint:** Per-checkpoint state tracking, ack collection, atomicity point
- **Execution:** RPC gateway to execute tasks
- **CheckpointBarrierHandler:** Local barrier alignment and ordering guarantee
- **SubtaskCheckpointCoordinator:** Local state snapshot and reporting

### Asynchronous Design
- Barrier trigger via RPC, but barrier events in-band (non-blocking RPC)
- State snapshot async (background executor thread)
- Ack collection async; completion future resolved when ready
- Master hooks and coordinator checkpoints async-first

### Lock Scoping
- CheckpointCoordinator holds single global lock for checkpoint state
- PendingCheckpoint has internal lock for ack collection
- Minimal lock contention; most work done outside locks (snapshot, RPC)

### Checkpoint Subsumption
- Newer checkpoints subsume older ones
- Older PendingCheckpoints aborted if newer checkpoint triggers first
- Shared state cleaned up only when subsumed (reference counting)

### Network Efficiency
- Barriers sent in-band within data stream, not as separate RPC messages
- Single barrier event per checkpoint ID per data partition
- Acknowledgments sent once per task (not per operator/subtask)

---

## Summary

Flink implements a **distributed two-phase commit protocol** for exactly-once checkpoint semantics:

1. **Trigger Phase:** JobManager's CheckpointCoordinator initiates checkpoint by creating PendingCheckpoint (awaiting acks) and triggering source tasks via RPC. Sources inject CheckpointBarrier into data stream.

2. **Propagation Phase:** Barriers flow in-band through task graph. Each intermediate task's SingleCheckpointBarrierHandler (or CheckpointBarrierTracker) receives barrier, aligns inputs (if exactly-once), and triggers state snapshot via SubtaskCheckpointCoordinator.

3. **Acknowledgment Phase:** Upon snapshot completion, tasks report state via CheckpointResponder RPC to JobMaster. CheckpointCoordinator collects acknowledgments in PendingCheckpoint, tracking awaited tasks.

4. **Completion Phase:** Once all tasks/coordinators acknowledge, PendingCheckpoint.finalizeCheckpoint() atomically writes metadata to durable storage and creates CompletedCheckpoint. All operators notified of completion.

The architecture achieves exactly-once semantics through in-band barrier ordering, upstream blocking (aligned barriers), and atomic commitment. Failure handling (timeout/decline) aborts PendingCheckpoint, rolling back to last completed checkpoint upon recovery.
