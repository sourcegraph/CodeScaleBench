# Detailed Refactoring Diffs - RecordAccumulator → BatchAccumulator

This document provides precise line-by-line diffs for each file modification required for the refactoring.

## File 1: RecordAccumulator.java → BatchAccumulator.java

### Key Changes:

**Line 68**: Class declaration
```diff
- public class RecordAccumulator {
+ public class BatchAccumulator {
```

**Line 128**: Logger initialization (constructor)
```diff
- this.log = logContext.logger(RecordAccumulator.class);
+ this.log = logContext.logger(BatchAccumulator.class);
```

**Lines 114-126**: First constructor signature
```diff
- public RecordAccumulator(LogContext logContext,
+ public BatchAccumulator(LogContext logContext,
                          int batchSize,
                          Compression compression,
                          int lingerMs,
                          long retryBackoffMs,
                          long retryBackoffMaxMs,
                          int deliveryTimeoutMs,
                          PartitionerConfig partitionerConfig,
                          Metrics metrics,
                          String metricGrpName,
                          Time time,
                          TransactionManager transactionManager,
                          BufferPool bufferPool) {
```

**Lines 171-182**: Second constructor signature
```diff
- public RecordAccumulator(LogContext logContext,
+ public BatchAccumulator(LogContext logContext,
                          int batchSize,
                          Compression compression,
                          int lingerMs,
                          long retryBackoffMs,
                          long retryBackoffMaxMs,
                          int deliveryTimeoutMs,
                          Metrics metrics,
                          String metricGrpName,
                          Time time,
                          TransactionManager transactionManager,
                          BufferPool bufferPool) {
```

**Inner Classes**: Names remain unchanged (RecordAppendResult, ReadyCheckResult, AppendCallbacks, PartitionerConfig, NodeLatencyStats)

---

## File 2: KafkaProducer.java

### Line 35: Import statement
```diff
- import org.apache.kafka.clients.producer.internals.RecordAccumulator;
+ import org.apache.kafka.clients.producer.internals.BatchAccumulator;
```

### Field declaration (line ~250-300 range, exact line varies)
```diff
- private final RecordAccumulator accumulator;
+ private final BatchAccumulator accumulator;
```

### Inner class reference - PartitionerConfig
```diff
- RecordAccumulator.PartitionerConfig partitionerConfig = new RecordAccumulator.PartitionerConfig(
+ BatchAccumulator.PartitionerConfig partitionerConfig = new BatchAccumulator.PartitionerConfig(
```

### Constructor instantiation
```diff
- this.accumulator = new RecordAccumulator(logContext,
+ this.accumulator = new BatchAccumulator(logContext,
```

### RecordAppendResult reference
```diff
- RecordAccumulator.RecordAppendResult result = accumulator.append(record.topic(), partition, timestamp, serializedKey,
+ BatchAccumulator.RecordAppendResult result = accumulator.append(record.topic(), partition, timestamp, serializedKey,
```

### Constructor parameter type
```diff
  private KafkaProducer(LogContext logContext,
                        Map<String, Object> configs,
                        Serializer<K> keySerializer,
                        Serializer<V> valueSerializer,
-                       RecordAccumulator accumulator,
+                       BatchAccumulator accumulator,
                        ProducerMetadata metadata,
                        ProducerInterceptors<K, V> interceptors,
```

### AppendCallbacks interface implementation (private inner class)
```diff
- private class AppendCallbacks implements RecordAccumulator.AppendCallbacks {
+ private class AppendCallbacks implements BatchAccumulator.AppendCallbacks {
```

### Comments (3 locations)
```diff
- //  - remember partition that is calculated in RecordAccumulator.append
+ //  - remember partition that is calculated in BatchAccumulator.append
```

```diff
- // which means that the RecordAccumulator would pick a partition using built-in logic (which may
+ // which means that the BatchAccumulator would pick a partition using built-in logic (which may
```

```diff
- * Callbacks that are called by the RecordAccumulator append functions:
+ * Callbacks that are called by the BatchAccumulator append functions:
```

---

## File 3: Sender.java

### Field declaration
```diff
- private final RecordAccumulator accumulator;
+ private final BatchAccumulator accumulator;
```

### Constructor parameter (lines 128-140)
```diff
  public Sender(LogContext logContext,
                KafkaClient client,
                ProducerMetadata metadata,
-               RecordAccumulator accumulator,
+               BatchAccumulator accumulator,
                boolean guaranteeMessageOrder,
```

### ReadyCheckResult reference
```diff
- RecordAccumulator.ReadyCheckResult result = this.accumulator.ready(metadataSnapshot, now);
+ BatchAccumulator.ReadyCheckResult result = this.accumulator.ready(metadataSnapshot, now);
```

---

## File 4: BuiltInPartitioner.java

### Comment reference in javadoc
```diff
- * RecordAccumulator, it does not implement the Partitioner interface.
+ * BatchAccumulator, it does not implement the Partitioner interface.
```

### Comment in method
```diff
- // See also RecordAccumulator#partitionReady where the queueSizes are built.
+ // See also BatchAccumulator#partitionReady where the queueSizes are built.
```

---

## File 5: ProducerBatch.java

### Comment update
```diff
- *        when aborting batches in {@link RecordAccumulator}).
+ *        when aborting batches in {@link BatchAccumulator}).
```

---

## File 6: Node.java

### Performance comment
```diff
- // Cache hashCode as it is called in performance sensitive parts of the code (e.g. RecordAccumulator.ready)
+ // Cache hashCode as it is called in performance sensitive parts of the code (e.g. BatchAccumulator.ready)
```

---

## File 7: RecordAccumulatorTest.java → BatchAccumulatorTest.java

### Class declaration rename
```diff
- public class RecordAccumulatorTest {
+ public class BatchAccumulatorTest {
```

### Sample field declaration (multiple in file)
```diff
- RecordAccumulator accum = createTestRecordAccumulator((int) batchSize, Integer.MAX_VALUE, Compression.NONE, 10);
+ BatchAccumulator accum = createTestRecordAccumulator((int) batchSize, Integer.MAX_VALUE, Compression.NONE, 10);
```

### Sample inner class reference - ReadyCheckResult
```diff
- RecordAccumulator.ReadyCheckResult result = accum.ready(metadataCache, time.milliseconds());
+ BatchAccumulator.ReadyCheckResult result = accum.ready(metadataCache, time.milliseconds());
```

### Sample inner class reference - AppendCallbacks
```diff
- class TestCallback implements RecordAccumulator.AppendCallbacks {
+ class TestCallback implements BatchAccumulator.AppendCallbacks {
```

### Sample inner class reference - PartitionerConfig
```diff
- RecordAccumulator.PartitionerConfig config = new RecordAccumulator.PartitionerConfig(true, 100);
+ BatchAccumulator.PartitionerConfig config = new BatchAccumulator.PartitionerConfig(true, 100);
```

### Sample helper method
```diff
- private RecordAccumulator createTestRecordAccumulator(int batchSize, long totalSize, Compression compression, int lingerMs) {
+ private BatchAccumulator createTestRecordAccumulator(int batchSize, long totalSize, Compression compression, int lingerMs) {
```

### Constructor instantiation
```diff
- return new RecordAccumulator(logContext, batchSize,
+ return new BatchAccumulator(logContext, batchSize,
```

**Note**: This file has approximately 50+ occurrences that need updating.

---

## File 8: SenderTest.java

### Field declaration
```diff
- private RecordAccumulator accumulator = null;
+ private BatchAccumulator accumulator = null;
```

### Sample AppendCallbacks reference
```diff
- RecordAccumulator.AppendCallbacks callbacks = new RecordAccumulator.AppendCallbacks() {
+ BatchAccumulator.AppendCallbacks callbacks = new BatchAccumulator.AppendCallbacks() {
```

### Sample PartitionerConfig reference
```diff
- RecordAccumulator.PartitionerConfig config = new RecordAccumulator.PartitionerConfig(false, 42);
+ BatchAccumulator.PartitionerConfig config = new BatchAccumulator.PartitionerConfig(false, 42);
```

### Sample constructor call
```diff
- accumulator = new RecordAccumulator(logContext, batchSize, Compression.NONE, 0, 0L, 0L,
+ accumulator = new BatchAccumulator(logContext, batchSize, Compression.NONE, 0, 0L, 0L,
```

### NodeLatencyStats reference
```diff
- RecordAccumulator.NodeLatencyStats stats = accumulator.getNodeLatencyStats(0);
+ BatchAccumulator.NodeLatencyStats stats = accumulator.getNodeLatencyStats(0);
```

---

## File 9: TransactionManagerTest.java

### Field declaration
```diff
- private RecordAccumulator accumulator = null;
+ private BatchAccumulator accumulator = null;
```

### Multiple constructor instantiations
```diff
- this.accumulator = new RecordAccumulator(logContext, batchSize, Compression.NONE, 0, 0L, 0L,
+ this.accumulator = new BatchAccumulator(logContext, batchSize, Compression.NONE, 0, 0L, 0L,
```

**Note**: Approximately 5 occurrences in this file.

---

## File 10: KafkaProducerTest.java

**Note**: This file may or may not have direct references to RecordAccumulator. If it does, they would appear as:

### Potential string reference (if testing via reflection)
```diff
- String className = "RecordAccumulator";
+ String className = "BatchAccumulator";
```

### Potential variable/field references in tests
```diff
- RecordAccumulator accum = producer.accumulator; // if exposed
+ BatchAccumulator accum = producer.accumulator; // if exposed
```

**Action**: Scan this file for any references and apply similar pattern changes.

---

## File 11: RecordAccumulatorFlushBenchmark.java → BatchAccumulatorFlushBenchmark.java

### Class declaration
```diff
- public class RecordAccumulatorFlushBenchmark {
+ public class BatchAccumulatorFlushBenchmark {
```

### Import statement
```diff
- import org.apache.kafka.clients.producer.internals.RecordAccumulator;
+ import org.apache.kafka.clients.producer.internals.BatchAccumulator;
```

### Field declaration
```diff
- private RecordAccumulator accum;
+ private BatchAccumulator accum;
```

### Method return type
```diff
- private RecordAccumulator createRecordAccumulator() {
+ private BatchAccumulator createRecordAccumulator() {
```

### Constructor call in method
```diff
- return new RecordAccumulator(
+ return new BatchAccumulator(
```

---

## Summary of Change Patterns

### Pattern 1: Type Declaration
```
- TypeName variableName;
+ NewTypeName variableName;
```
Affects: ~25 occurrences

### Pattern 2: Constructor Call
```
- new RecordAccumulator(
+ new BatchAccumulator(
```
Affects: ~15 occurrences

### Pattern 3: Inner Class Reference
```
- RecordAccumulator.InnerClass
+ BatchAccumulator.InnerClass
```
Affects: ~30 occurrences

### Pattern 4: Import Statement
```
- import ... RecordAccumulator;
+ import ... BatchAccumulator;
```
Affects: 2 occurrences

### Pattern 5: Documentation/Comments
```
- RecordAccumulator
+ BatchAccumulator
```
Affects: 8 occurrences

---

## Implementation Order

Recommend implementing changes in this order:

1. **Main file first**: `RecordAccumulator.java` → `BatchAccumulator.java`
2. **Core dependencies**: `KafkaProducer.java`, `Sender.java`
3. **Supporting files**: `BuiltInPartitioner.java`, `ProducerBatch.java`, `Node.java`
4. **Test files**: `RecordAccumulatorTest.java` (rename), `SenderTest.java`, `TransactionManagerTest.java`, `KafkaProducerTest.java`
5. **Benchmarks**: `RecordAccumulatorFlushBenchmark.java` (rename)
6. **Verification**: Run compilation and tests

This order ensures:
- Core implementation is renamed first
- Dependencies can then be updated
- Supporting and test files follow with consistent types
- Full verification completes the task

---

## Total Reference Count

- **Type declarations**: ~25
- **Constructor calls**: ~15
- **Inner class references**: ~30
- **Import statements**: 2
- **Comment updates**: 8
- **File renames**: 3
- **Class renames**: 1
- **Total changes**: ~84 changes across 11 files

Estimated effort: **2-3 hours** for manual implementation (if permissions allow)

