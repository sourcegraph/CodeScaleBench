# big-code-flink-arch-001: Flink Checkpoint Coordination Architecture

## Task

Map the Flink checkpoint coordination architecture: how the JobManager triggers a checkpoint, propagates barriers through the task graph, and coordinates acknowledgments. Trace the complete distributed two-phase commit from CheckpointCoordinator through barrier injection, barrier alignment/processing at downstream tasks, state snapshot, acknowledgment, to CompletedCheckpoint.

## Context

- **Repository**: apache/flink (Java, ~3.5M LOC)
- **Category**: Architectural Understanding
- **Difficulty**: hard
- **Subsystem Focus**: flink-runtime/checkpoint/ and flink-streaming-java/runtime/io/checkpointing/

## Requirements

1. Identify all relevant components in the checkpoint coordination flow (JobManager-side coordinator, RPC dispatch, barrier events, barrier handlers, state snapshot, acknowledgment)
2. Trace the dependency chain from CheckpointCoordinator.triggerCheckpoint() through barrier propagation to CompletedCheckpoint
3. Document the aligned vs unaligned checkpoint barrier handling (SingleCheckpointBarrierHandler vs CheckpointBarrierTracker)
4. Explain the PendingCheckpoint lifecycle and the ack-based completion protocol

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — role in architecture
- path/to/file2.ext — role in architecture
...

## Dependency Chain
1. Entry point: path/to/entry.ext
2. Calls: path/to/next.ext (via function/method name)
3. Delegates to: path/to/impl.ext
...

## Analysis
[Detailed architectural analysis including:
- Design patterns identified
- Component responsibilities
- Data flow description
- Interface contracts between components]

## Summary
[Concise 2-3 sentence summary answering the task question]
```

## Evaluation Criteria

- File recall: Did you find the correct set of architecturally relevant files?
- Dependency accuracy: Did you trace the correct dependency/call chain?
- Architectural coherence: Did you correctly identify the design patterns and component relationships?
