# big-code-kafka-refac-001: Rename RecordAccumulator to BatchAccumulator

This repository is large (~1.2M LOC). Use comprehensive search to find ALL references before making changes.

## Task Type: Cross-File Refactoring

Your goal is to rename the `RecordAccumulator` class to `BatchAccumulator` across the Kafka producer subsystem. Focus on:

1. **Complete identification**: Find ALL files that reference `RecordAccumulator` — the class definition, `KafkaProducer`, `Sender`, `BuiltInPartitioner`, inner class references (`ReadyCheckResult`, `RecordAppendResult`), all test files, and the JMH benchmark
2. **Dependency ordering**: Change the class definition first, then update `KafkaProducer` and `Sender` (direct users), then `BuiltInPartitioner`, then test files and benchmarks
3. **Inner class awareness**: `RecordAccumulator` contains inner classes `RecordAppendResult` and `ReadyCheckResult` — these are referenced as `RecordAccumulator.RecordAppendResult` throughout the codebase
4. **Consistency**: Ensure no stale references to `RecordAccumulator` remain after the refactoring
5. **Compilation**: Verify with `./gradlew clients:compileJava`

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — why this file needs changes

## Dependency Chain
1. path/to/definition.ext (original definition)
2. path/to/user1.ext (direct reference)
3. path/to/user2.ext (transitive dependency)

## Code Changes
### path/to/file1.ext
\`\`\`diff
- old code
+ new code
\`\`\`

## Analysis
[Refactoring strategy and verification approach]
```

## Search Strategy

- Start with `clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java` — the class definition
- Use `find_references` on `RecordAccumulator` to find ALL usages across the codebase
- Check `clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java` for the main producer entry point
- Check `clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java` for the network send loop
- Check `clients/src/main/java/org/apache/kafka/clients/producer/internals/BuiltInPartitioner.java` for partitioner references
- Search `clients/src/test/java/org/apache/kafka/clients/producer/` for all test files
- Check `jmh-benchmarks/src/main/java/org/apache/kafka/jmh/producer/` for performance benchmarks
- Search `clients/src/main/java/org/apache/kafka/common/Node.java` for comment references
- Search `connect/runtime/` for Kafka Connect references to RecordAccumulator
- After changes, grep for `RecordAccumulator` to verify no stale references remain
