# big-code-flink-arch-001: Flink Checkpoint Coordination Architecture

This repository is large (~3.5M LOC, multi-module Maven project). Use comprehensive search strategies across multiple modules.

## Task Type: Architectural Understanding

Your goal is to map the complete checkpoint coordination flow in Apache Flink. Focus on:

1. **Trigger phase**: CheckpointCoordinator in flink-runtime/checkpoint/ — how checkpoints are initiated
2. **Barrier propagation**: CheckpointBarrier event and how it flows through the data channels
3. **Barrier handling**: CheckpointedInputGate, SingleCheckpointBarrierHandler in flink-streaming-java/
4. **State snapshot**: StreamTask and SubtaskCheckpointCoordinator handle operator state snapshots
5. **Acknowledgment**: AcknowledgeCheckpoint message flow back to JobManager, PendingCheckpoint tracking

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — role in the architecture

## Dependency Chain
1. path/to/core.ext (foundational types/interfaces)
2. path/to/impl.ext (implementation layer)
3. path/to/integration.ext (integration/wiring layer)

## Analysis
[Your architectural analysis]
```

## Search Strategy

- Start with `flink-runtime/src/main/java/org/apache/flink/runtime/checkpoint/CheckpointCoordinator.java` (main coordinator)
- Explore `flink-runtime/.../checkpoint/PendingCheckpoint.java` and `CompletedCheckpoint.java` for lifecycle
- Check `flink-runtime/.../io/network/api/CheckpointBarrier.java` for the barrier event
- Check `flink-streaming-java/.../io/checkpointing/` for barrier handlers (SingleCheckpointBarrierHandler, CheckpointBarrierTracker)
- Trace `StreamTask.performCheckpoint()` through `SubtaskCheckpointCoordinator` for state snapshot
- Use `find_references` to trace how triggerCheckpoint propagates through the system
- Use `go_to_definition` to understand interface implementations
