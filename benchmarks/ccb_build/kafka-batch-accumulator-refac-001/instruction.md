# big-code-kafka-refac-001: Rename RecordAccumulator to BatchAccumulator in Apache Kafka

## Task

Rename the `RecordAccumulator` class to `BatchAccumulator` throughout the Apache Kafka producer subsystem. The `RecordAccumulator` in `clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java` manages per-partition queues of `ProducerBatch` objects, not individual records. Its core data structure is a `ConcurrentMap<TopicPartition, Deque<ProducerBatch>>`, and its key methods (`ready()`, `drain()`, `append()`) all operate at batch granularity. Renaming to `BatchAccumulator` better describes the class's true responsibility.

The refactoring includes:
1. Rename the class `RecordAccumulator` to `BatchAccumulator` (including the file itself)
2. Rename the inner classes: `RecordAccumulator.RecordAppendResult` → `BatchAccumulator.RecordAppendResult`, `RecordAccumulator.ReadyCheckResult` → `BatchAccumulator.ReadyCheckResult`
3. Update `KafkaProducer.java` — field type, constructor, and all usages
4. Update `Sender.java` — field type, constructor parameter, and all usages
5. Update `BuiltInPartitioner.java` — RecordAccumulator references
6. Update all test files: `RecordAccumulatorTest`, `SenderTest`, `TransactionManagerTest`, `KafkaProducerTest`
7. Update the JMH benchmark: `RecordAccumulatorFlushBenchmark`
8. Update comment references in `Node.java` and `WorkerSourceTask.java`

## Context

- **Repository**: apache/kafka (Java, ~1.2M LOC)
- **Category**: Cross-File Refactoring
- **Difficulty**: hard
- **Subsystem Focus**: clients/src/main/java/org/apache/kafka/clients/producer/ — the Kafka producer internals

## Requirements

1. Identify ALL files that need modification for this refactoring
2. Document the complete dependency chain showing why each file is affected
3. Implement the changes (or describe them precisely if the scope is too large)
4. Verify that no references to the old API/name remain

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — why this file needs changes
- path/to/file2.ext — why this file needs changes
...

## Dependency Chain
1. Definition: path/to/definition.ext (original definition)
2. Direct usage: path/to/user1.ext (imports/references the symbol)
3. Transitive: path/to/user2.ext (uses a type that depends on the symbol)
...

## Code Changes
### path/to/file1.ext
```diff
- old code
+ new code
```

### path/to/file2.ext
```diff
- old code
+ new code
```

## Analysis
[Explanation of the refactoring strategy, affected areas, and verification approach]
```

## Evaluation Criteria

- File coverage: Did you identify ALL files that need modification?
- Completeness: Were all references updated (no stale references)?
- Compilation: Does the code still compile after changes?
- Correctness: Do the changes preserve the intended behavior?
