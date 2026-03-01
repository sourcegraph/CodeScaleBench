# RecordAccumulator → BatchAccumulator Refactoring Implementation Guide

This guide provides the exact steps and patterns needed to execute the complete refactoring across all 12 files.

## Part 1: File Rename Operations

### Step 1.1: Rename Main Class File
```bash
cd clients/src/main/java/org/apache/kafka/clients/producer/internals/
mv RecordAccumulator.java BatchAccumulator.java
```

### Step 1.2: Rename Test Class File
```bash
cd clients/src/test/java/org/apache/kafka/clients/producer/internals/
mv RecordAccumulatorTest.java BatchAccumulatorTest.java
```

### Step 1.3: Rename Benchmark Class File
```bash
cd jmh-benchmarks/src/main/java/org/apache/kafka/jmh/producer/
mv RecordAccumulatorFlushBenchmark.java BatchAccumulatorFlushBenchmark.java
```

## Part 2: Content Changes - Main Class (BatchAccumulator.java)

All changes are **direct string replacements** of `RecordAccumulator` → `BatchAccumulator` in specific contexts:

### Change 2.1: Class Declaration (Line 68)
```diff
- public class RecordAccumulator {
+ public class BatchAccumulator {
```

**Pattern:** In class definition, replace the class name

### Change 2.2: Constructors (Lines 114, 171)
```diff
- public RecordAccumulator(LogContext logContext,
+ public BatchAccumulator(LogContext logContext,

- public RecordAccumulator(LogContext logContext,
+ public BatchAccumulator(LogContext logContext,
```

**Pattern:** In both constructor signatures, replace class name

### Change 2.3: Logger Initialization (Line 128)
```diff
- this.log = logContext.logger(RecordAccumulator.class);
+ this.log = logContext.logger(BatchAccumulator.class);
```

**Pattern:** In constructor body, update class reference

### Change 2.4: Inner Class Reference (Line ~1558)
Located in KafkaProducer.java's AppendCallbacks inner class:
```diff
- private class AppendCallbacks implements RecordAccumulator.AppendCallbacks {
+ private class AppendCallbacks implements BatchAccumulator.AppendCallbacks {
```

**Pattern:** In implements clause, update parent class name

---

## Part 3: Content Changes - KafkaProducer.java

### Change 3.1: Import Statement (Line 35)
```diff
- import org.apache.kafka.clients.producer.internals.RecordAccumulator;
+ import org.apache.kafka.clients.producer.internals.BatchAccumulator;
```

**Pattern:** Update import statement to reference new class name

### Change 3.2: Field Declaration (Line 256)
```diff
- private final RecordAccumulator accumulator;
+ private final BatchAccumulator accumulator;
```

**Pattern:** Update field type declaration

### Change 3.3: PartitionerConfig Reference (Line 419)
```diff
- RecordAccumulator.PartitionerConfig partitionerConfig = new RecordAccumulator.PartitionerConfig(
+ BatchAccumulator.PartitionerConfig partitionerConfig = new BatchAccumulator.PartitionerConfig(
```

**Pattern:** Update fully-qualified inner class references (2 occurrences per line)

### Change 3.4: AppendCallbacks Inner Class Implementation
Locate the inner `AppendCallbacks` class in KafkaProducer.java and update:
```diff
- private class AppendCallbacks implements RecordAccumulator.AppendCallbacks {
+ private class AppendCallbacks implements BatchAccumulator.AppendCallbacks {
```

---

## Part 4: Content Changes - Sender.java

### Change 4.1: Import Statement (Line 35)
```diff
- import org.apache.kafka.clients.producer.internals.RecordAccumulator;
+ import org.apache.kafka.clients.producer.internals.BatchAccumulator;
```

### Change 4.2: Field Declaration (Line 87)
```diff
  /* the record accumulator that batches records */
- private final RecordAccumulator accumulator;
+ private final BatchAccumulator accumulator;
```

### Change 4.3: Constructor Parameter (Line 131)
```diff
  public Sender(LogContext logContext,
                Client client,
                ProducerMetadata metadata,
-               RecordAccumulator accumulator,
+               BatchAccumulator accumulator,
                boolean guaranteeMessageOrder,
```

### Change 4.4: Return Type in ready() Method (Line 360)
```diff
-         RecordAccumulator.ReadyCheckResult result = this.accumulator.ready(metadataSnapshot, now);
+         BatchAccumulator.ReadyCheckResult result = this.accumulator.ready(metadataSnapshot, now);
```

---

## Part 5: Content Changes - Test Files

### Change 5.1: RecordAccumulatorTest.java → BatchAccumulatorTest.java

**Content updates needed:**
```diff
- public class RecordAccumulatorTest {
+ public class BatchAccumulatorTest {

- private RecordAccumulator createTestRecordAccumulator(int batchSize, long totalSize, Compression compression, int lingerMs) {
+ private BatchAccumulator createTestBatchAccumulator(int batchSize, long totalSize, Compression compression, int lingerMs) {
      int deliveryTimeoutMs = 3200;
-     return createTestRecordAccumulator(deliveryTimeoutMs, batchSize, totalSize, compression, lingerMs);
+     return createTestBatchAccumulator(deliveryTimeoutMs, batchSize, totalSize, compression, lingerMs);
  }

- private RecordAccumulator createTestRecordAccumulator(int deliveryTimeoutMs, int batchSize, long totalSize, Compression compression, int lingerMs) {
-     return createTestRecordAccumulator(null, deliveryTimeoutMs, batchSize, totalSize, compression, lingerMs);
+ private BatchAccumulator createTestBatchAccumulator(int deliveryTimeoutMs, int batchSize, long totalSize, Compression compression, int lingerMs) {
+     return createTestBatchAccumulator(null, deliveryTimeoutMs, batchSize, totalSize, compression, lingerMs);
  }

- private RecordAccumulator createTestRecordAccumulator(String bootstrapServers, ...
+ private BatchAccumulator createTestBatchAccumulator(String bootstrapServers, ...
-     return new RecordAccumulator(logContext, batchSize, compression, lingerMs, ...
+     return new BatchAccumulator(logContext, batchSize, compression, lingerMs, ...
```

**Search pattern in test methods:**
- Replace all `createTestRecordAccumulator(` → `createTestBatchAccumulator(`
- Replace all `new RecordAccumulator(` → `new BatchAccumulator(`

### Change 5.2: SenderTest.java

**Key updates:**
```diff
- import org.apache.kafka.clients.producer.internals.RecordAccumulator;
+ import org.apache.kafka.clients.producer.internals.BatchAccumulator;

  ...

- private RecordAccumulator accumulator = null;
+ private BatchAccumulator accumulator = null;

  ...

- accumulator = new RecordAccumulator(logContext, batchSize, Compression.NONE, 0, 0L, 0L,
+ accumulator = new BatchAccumulator(logContext, batchSize, Compression.NONE, 0, 0L, 0L,
      DELIVERY_TIMEOUT_MS, config, m, "producer-metrics", time, null,

- RecordAccumulator.PartitionerConfig config = new RecordAccumulator.PartitionerConfig(false, 42);
+ BatchAccumulator.PartitionerConfig config = new BatchAccumulator.PartitionerConfig(false, 42);

- RecordAccumulator.AppendCallbacks callbacks = new RecordAccumulator.AppendCallbacks() {
+ BatchAccumulator.AppendCallbacks callbacks = new BatchAccumulator.AppendCallbacks() {
```

### Change 5.3: KafkaProducerTest.java

**Key updates:**
```diff
- import org.apache.kafka.clients.producer.internals.RecordAccumulator;
+ import org.apache.kafka.clients.producer.internals.BatchAccumulator;

  ...

- any(RecordAccumulator.AppendCallbacks.class),    // 6 <--
+ any(BatchAccumulator.AppendCallbacks.class),    // 6 <--

- RecordAccumulator.AppendCallbacks callbacks =
-     (RecordAccumulator.AppendCallbacks) invocation.getArguments()[6];
+ BatchAccumulator.AppendCallbacks callbacks =
+     (BatchAccumulator.AppendCallbacks) invocation.getArguments()[6];

- return new RecordAccumulator.RecordAppendResult(
+ return new BatchAccumulator.RecordAppendResult(
```

### Change 5.4: TransactionManagerTest.java

**Key updates:**
```diff
- import org.apache.kafka.clients.producer.internals.RecordAccumulator;
+ import org.apache.kafka.clients.producer.internals.BatchAccumulator;

  ...

- private RecordAccumulator accumulator = null;
+ private BatchAccumulator accumulator = null;

  ...

- this.accumulator = new RecordAccumulator(logContext, batchSize, Compression.NONE, 0, 0L, 0L,
+ this.accumulator = new BatchAccumulator(logContext, batchSize, Compression.NONE, 0, 0L, 0L,

- RecordAccumulator accumulator = new RecordAccumulator(logContext, 16 * 1024, Compression.NONE, 0, 0L, 0L,
+ BatchAccumulator accumulator = new BatchAccumulator(logContext, 16 * 1024, Compression.NONE, 0, 0L, 0L,
```

---

## Part 6: Content Changes - Benchmark File

### Change 6.1: RecordAccumulatorFlushBenchmark.java → BatchAccumulatorFlushBenchmark.java

**Key updates:**
```diff
- public class RecordAccumulatorFlushBenchmark {
+ public class BatchAccumulatorFlushBenchmark {

- import org.apache.kafka.clients.producer.internals.RecordAccumulator;
+ import org.apache.kafka.clients.producer.internals.BatchAccumulator;

  ...

- private RecordAccumulator createRecordAccumulator() {
-     return new RecordAccumulator(
+ private BatchAccumulator createBatchAccumulator() {
+     return new BatchAccumulator(
```

---

## Part 7: Comment/Documentation Updates

These changes are **non-functional** but maintain internal consistency. No behavior changes.

### Change 7.1: Node.java (Line 35)
```diff
- // Cache hashCode as it is called in performance sensitive parts of the code (e.g. RecordAccumulator.ready)
+ // Cache hashCode as it is called in performance sensitive parts of the code (e.g. BatchAccumulator.ready)
```

### Change 7.2: ProducerBatch.java (Line 530)
```diff
- // when aborting batches in {@link RecordAccumulator}).
+ // when aborting batches in {@link BatchAccumulator}).
```

### Change 7.3: BuiltInPartitioner.java (Lines 34, 256)
```diff
  * Built-in default partitioner.  Note, that this is just a utility class that is used directly from
- * RecordAccumulator, it does not implement the Partitioner interface.
+ * BatchAccumulator, it does not implement the Partitioner interface.

  ...

- // See also RecordAccumulator#partitionReady where the queueSizes are built.
+ // See also BatchAccumulator#partitionReady where the queueSizes are built.
```

---

## Part 8: Configuration File Updates

### Change 8.1: checkstyle/suppressions.xml (Line 79)
```diff
  <suppress checks="ParameterNumber"
-           files="(RecordAccumulator|Sender).java"/>
+           files="(BatchAccumulator|Sender).java"/>
```

**Note:** This is a regex pattern. Replace only within the `files` attribute value.

---

## Automated Refactoring Script (sed/perl based)

For teams wanting to automate this, here's a series of `sed` commands that will handle most of the refactoring:

```bash
#!/bin/bash

# Define the files to process
FILES=(
    "clients/src/main/java/org/apache/kafka/clients/producer/internals/BatchAccumulator.java"
    "clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java"
    "clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java"
    "clients/src/test/java/org/apache/kafka/clients/producer/internals/BatchAccumulatorTest.java"
    "clients/src/test/java/org/apache/kafka/clients/producer/KafkaProducerTest.java"
    "clients/src/test/java/org/apache/kafka/clients/producer/internals/SenderTest.java"
    "clients/src/test/java/org/apache/kafka/clients/producer/internals/TransactionManagerTest.java"
    "jmh-benchmarks/src/main/java/org/apache/kafka/jmh/producer/BatchAccumulatorFlushBenchmark.java"
    "clients/src/main/java/org/apache/kafka/common/Node.java"
    "clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java"
    "clients/src/main/java/org/apache/kafka/clients/producer/internals/BuiltInPartitioner.java"
    "checkstyle/suppressions.xml"
)

for file in "${FILES[@]}"; do
    if [ -f "$file" ]; then
        # Main class name replacements
        sed -i 's/public class RecordAccumulator {/public class BatchAccumulator {/g' "$file"
        sed -i 's/public RecordAccumulator(/public BatchAccumulator(/g' "$file"
        sed -i 's/import.*RecordAccumulator;/import org.apache.kafka.clients.producer.internals.BatchAccumulator;/g' "$file"

        # Field and variable type replacements
        sed -i 's/RecordAccumulator accumulator/BatchAccumulator accumulator/g' "$file"
        sed -i 's/new RecordAccumulator(/new BatchAccumulator(/g' "$file"

        # Inner type references
        sed -i 's/RecordAccumulator\.PartitionerConfig/BatchAccumulator.PartitionerConfig/g' "$file"
        sed -i 's/RecordAccumulator\.AppendCallbacks/BatchAccumulator.AppendCallbacks/g' "$file"
        sed -i 's/RecordAccumulator\.ReadyCheckResult/BatchAccumulator.ReadyCheckResult/g' "$file"
        sed -i 's/RecordAccumulator\.RecordAppendResult/BatchAccumulator.RecordAppendResult/g' "$file"

        # Logger initialization
        sed -i 's/logContext\.logger(RecordAccumulator\.class)/logContext.logger(BatchAccumulator.class)/g' "$file"

        # Javadoc/comment references
        sed -i 's/RecordAccumulator\.ready/BatchAccumulator.ready/g' "$file"
        sed -i 's/{@link RecordAccumulator}/{@link BatchAccumulator}/g' "$file"
        sed -i 's/RecordAccumulator#/{BatchAccumulator#/g' "$file"
        sed -i 's/RecordAccumulator,/BatchAccumulator,/g' "$file"
        sed -i 's/RecordAccumulator\./<see>BatchAccumulator./g' "$file"

        # Test-specific replacements
        sed -i 's/createTestRecordAccumulator/createTestBatchAccumulator/g' "$file"
        sed -i 's/createRecordAccumulator/createBatchAccumulator/g' "$file"
        sed -i 's/public class RecordAccumulatorTest/public class BatchAccumulatorTest/g' "$file"
        sed -i 's/public class RecordAccumulatorFlushBenchmark/public class BatchAccumulatorFlushBenchmark/g' "$file"

        echo "✓ Updated $file"
    else
        echo "✗ File not found: $file"
    fi
done

echo "Refactoring complete!"
```

---

## Compilation & Verification Steps

### Step 1: Compile the Producer Module
```bash
mvn clean compile -f clients/pom.xml -DskipTests -q
```

Expected output: **BUILD SUCCESS** (or see compilation errors)

### Step 2: Run Producer Tests
```bash
mvn test -f clients/pom.xml -Dtest=BatchAccumulatorTest -q
mvn test -f clients/pom.xml -Dtest=SenderTest -q
mvn test -f clients/pom.xml -Dtest=KafkaProducerTest -q
mvn test -f clients/pom.xml -Dtest=TransactionManagerTest -q
```

### Step 3: Verify No Old References Exist
```bash
# Should return ONLY comments or specific context matches:
grep -r "RecordAccumulator" clients/src/main/java/ --include="*.java" 2>/dev/null | grep -v "// " | wc -l

# Should be 0 or only in comments
```

### Step 4: Run All Producer Tests
```bash
mvn test -f clients/pom.xml -q
```

---

## Common Pitfalls & How to Avoid Them

### Pitfall 1: Incomplete Inner Class References
**Problem:** Missing updates to `RecordAccumulator.ReadyCheckResult` etc.
**Solution:** Use grep to find all instances: `grep -r "RecordAccumulator\." clients/src/`

### Pitfall 2: Comment References
**Problem:** Leaving old names in Javadoc and inline comments
**Solution:** Use: `grep -r "RecordAccumulator" clients/src/ --include="*.java"` to find all

### Pitfall 3: Test Method Names
**Problem:** Forgetting to rename helper methods like `createTestRecordAccumulator()`
**Solution:** Update all occurrences systematically per the patterns shown

### Pitfall 4: Checkstyle Configuration
**Problem:** Forgetting to update regex patterns in suppressions.xml
**Solution:** Check regex patterns that include the class name

---

## Rollback Instructions (if needed)

If issues arise, you can rollback by:

```bash
# Rename files back
mv BatchAccumulator.java RecordAccumulator.java
mv BatchAccumulatorTest.java RecordAccumulatorTest.java
mv BatchAccumulatorFlushBenchmark.java RecordAccumulatorFlushBenchmark.java

# Revert file changes
git checkout -- clients/src/main/java/org/apache/kafka/clients/producer/
git checkout -- clients/src/test/java/org/apache/kafka/clients/producer/
git checkout -- jmh-benchmarks/src/
git checkout -- clients/src/main/java/org/apache/kafka/common/Node.java
git checkout -- clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java
git checkout -- checkstyle/suppressions.xml
```

---

## Verification Checklist

- [ ] All 3 files renamed (RecordAccumulator.java → BatchAccumulator.java, etc.)
- [ ] All imports updated (RecordAccumulator → BatchAccumulator)
- [ ] All class declarations updated
- [ ] All field type declarations updated
- [ ] All constructor signatures updated (both public constructors)
- [ ] All method parameter types updated
- [ ] All return type references updated
- [ ] All inner type references updated (PartitionerConfig, AppendCallbacks, etc.)
- [ ] All `new RecordAccumulator(` → `new BatchAccumulator(`
- [ ] All test class references updated
- [ ] All helper method names updated
- [ ] All comment/Javadoc references updated
- [ ] checkstyle/suppressions.xml regex pattern updated
- [ ] No "RecordAccumulator" appears in source code (except comments)
- [ ] Compilation succeeds
- [ ] All tests pass
