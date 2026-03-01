# RecordAccumulator → BatchAccumulator Refactoring - Execution Checklist

Use this checklist to track progress through the refactoring.

## Pre-Execution (Planning Phase)

- [ ] Read README.md for overview
- [ ] Read SUMMARY.md for scope and effort estimation
- [ ] Review solution.md dependency chain section
- [ ] Review solution.md risk assessment
- [ ] Make go/no-go decision
- [ ] Gather team if needed
- [ ] Prepare testing environment
- [ ] Ensure git is working (`git status`, `git log`)

## File Renames

- [ ] Rename `RecordAccumulator.java` → `BatchAccumulator.java`
  - Location: `clients/src/main/java/org/apache/kafka/clients/producer/internals/`

- [ ] Rename `RecordAccumulatorTest.java` → `BatchAccumulatorTest.java`
  - Location: `clients/src/test/java/org/apache/kafka/clients/producer/internals/`

- [ ] Rename `RecordAccumulatorFlushBenchmark.java` → `BatchAccumulatorFlushBenchmark.java`
  - Location: `jmh-benchmarks/src/main/java/org/apache/kafka/jmh/producer/`

## Implementation (Choose One Path)

### Path A: Automated Implementation

- [ ] Open REFACTORING_IMPLEMENTATION_GUIDE.md, Part 8
- [ ] Copy the bash script to a file: `refactor.sh`
- [ ] Make it executable: `chmod +x refactor.sh`
- [ ] Run from repository root: `./refactor.sh`
- [ ] Review changes: `git diff clients/src/main/java/`
- [ ] Review changes: `git diff clients/src/test/java/`
- [ ] Review changes: `git diff jmh-benchmarks/`
- [ ] Review changes: `git diff checkstyle/`
- [ ] Spot-check specific files manually:
  - [ ] `BatchAccumulator.java` - Class declaration on line 68
  - [ ] `KafkaProducer.java` - Import on line 35
  - [ ] `Sender.java` - Import on line 35
  - [ ] `BatchAccumulatorTest.java` - Class name on line 88

### Path B: Manual Implementation

#### Phase 1: Main Class File (BatchAccumulator.java)
- [ ] Open `BatchAccumulator.java`
- [ ] Update class declaration (line 68): `public class BatchAccumulator {`
- [ ] Update constructor #1 (line 114): `public BatchAccumulator(`
- [ ] Update constructor #2 (line 171): `public BatchAccumulator(`
- [ ] Update logger init (line 128): `logContext.logger(BatchAccumulator.class)`
- [ ] Update inner class (line ~1558): `implements BatchAccumulator.AppendCallbacks`

#### Phase 2: KafkaProducer.java
- [ ] Update import (line 35): `BatchAccumulator` (not RecordAccumulator)
- [ ] Update field (line 256): `private final BatchAccumulator accumulator;`
- [ ] Update PartitionerConfig (line 419): `BatchAccumulator.PartitionerConfig`
- [ ] Find and update AppendCallbacks inner class: `implements BatchAccumulator.AppendCallbacks`

#### Phase 3: Sender.java
- [ ] Update import (line 35): `BatchAccumulator`
- [ ] Update field comment & declaration (line 87): `private final BatchAccumulator accumulator;`
- [ ] Update constructor param (line 131): `BatchAccumulator accumulator`
- [ ] Update return type (line 360): `BatchAccumulator.ReadyCheckResult result`

#### Phase 4: Test File - RecordAccumulatorTest.java → BatchAccumulatorTest.java
- [ ] Update class name (line 88): `public class BatchAccumulatorTest {`
- [ ] Find and update all helper methods: `createTestBatchAccumulator`
- [ ] Find and update all `new RecordAccumulator(` → `new BatchAccumulator(`
- [ ] Find and update all helper method calls to use new names

#### Phase 5: Test File - SenderTest.java
- [ ] Update import: `BatchAccumulator`
- [ ] Update field (line ~176): `private BatchAccumulator accumulator = null;`
- [ ] Find and update all: `new RecordAccumulator(` → `new BatchAccumulator(`
- [ ] Find and update: `RecordAccumulator.PartitionerConfig` → `BatchAccumulator.PartitionerConfig`
- [ ] Find and update: `RecordAccumulator.AppendCallbacks` → `BatchAccumulator.AppendCallbacks`

#### Phase 6: Test File - KafkaProducerTest.java
- [ ] Update import: `BatchAccumulator`
- [ ] Find line with `any(RecordAccumulator.AppendCallbacks.class)` and update to `BatchAccumulator`
- [ ] Find mock setup and update `RecordAccumulator.AppendCallbacks` references to `BatchAccumulator.AppendCallbacks`
- [ ] Find `new RecordAccumulator.RecordAppendResult(` and update to `BatchAccumulator`

#### Phase 7: Test File - TransactionManagerTest.java
- [ ] Update import: `BatchAccumulator`
- [ ] Update field (line ~155): `private BatchAccumulator accumulator = null;`
- [ ] Find and update: `new RecordAccumulator(` → `new BatchAccumulator(` (2 occurrences)

#### Phase 8: RecordAccumulatorFlushBenchmark.java → BatchAccumulatorFlushBenchmark.java
- [ ] Update class name (line ~68): `public class BatchAccumulatorFlushBenchmark {`
- [ ] Update import: `BatchAccumulator`
- [ ] Update helper method name: `createBatchAccumulator()`
- [ ] Update: `new RecordAccumulator(` → `new BatchAccumulator(`

#### Phase 9: Comment Updates (Non-functional, but maintain consistency)
- [ ] **Node.java** (line 35): Update comment from `RecordAccumulator.ready` to `BatchAccumulator.ready`
- [ ] **ProducerBatch.java** (line 530): Update comment from `RecordAccumulator` to `BatchAccumulator`
- [ ] **BuiltInPartitioner.java** (line 34): Update comment from `RecordAccumulator` to `BatchAccumulator`
- [ ] **BuiltInPartitioner.java** (line 256): Update comment from `RecordAccumulator#partitionReady` to `BatchAccumulator#partitionReady`

#### Phase 10: Configuration Files
- [ ] **checkstyle/suppressions.xml** (line 79): Update regex pattern from `RecordAccumulator` to `BatchAccumulator`

## Verification

### Compile-Time Checks
- [ ] Run: `mvn clean compile -f clients/pom.xml -DskipTests -q`
- [ ] Result: **BUILD SUCCESS** (or document any compilation errors)

### No Stale References
- [ ] Run: `grep -r "RecordAccumulator" clients/src/main/java/ --include="*.java" | grep -v "// "`
- [ ] Result: Should be **empty** (0 lines)
- [ ] Run: `grep -r "RecordAccumulator" clients/src/test/java/ --include="*.java"`
- [ ] Result: Should be **empty** (0 lines)

### Unit Tests - Batch Accumulator
- [ ] Run: `mvn test -f clients/pom.xml -Dtest=BatchAccumulatorTest -q`
- [ ] Result: **BUILD SUCCESS** (all tests pass)
- [ ] Note any failures: ___________________________________

### Unit Tests - Sender
- [ ] Run: `mvn test -f clients/pom.xml -Dtest=SenderTest -q`
- [ ] Result: **BUILD SUCCESS** (all tests pass)
- [ ] Note any failures: ___________________________________

### Unit Tests - KafkaProducer
- [ ] Run: `mvn test -f clients/pom.xml -Dtest=KafkaProducerTest -q`
- [ ] Result: **BUILD SUCCESS** (all tests pass)
- [ ] Note any failures: ___________________________________

### Unit Tests - TransactionManager
- [ ] Run: `mvn test -f clients/pom.xml -Dtest=TransactionManagerTest -q`
- [ ] Result: **BUILD SUCCESS** (all tests pass)
- [ ] Note any failures: ___________________________________

### Full Test Suite
- [ ] Run: `mvn test -f clients/pom.xml -q`
- [ ] Result: **BUILD SUCCESS** (all tests pass)
- [ ] Total tests passed: ___________
- [ ] Any failures: ___________________________________

### File Structure Verification
- [ ] Verify file exists: `clients/src/main/java/org/apache/kafka/clients/producer/internals/BatchAccumulator.java`
- [ ] Verify file exists: `clients/src/test/java/org/apache/kafka/clients/producer/internals/BatchAccumulatorTest.java`
- [ ] Verify file exists: `jmh-benchmarks/src/main/java/org/apache/kafka/jmh/producer/BatchAccumulatorFlushBenchmark.java`
- [ ] Verify old files deleted: `RecordAccumulator.java` (should NOT exist)
- [ ] Verify old files deleted: `RecordAccumulatorTest.java` (should NOT exist)
- [ ] Verify old files deleted: `RecordAccumulatorFlushBenchmark.java` (should NOT exist)

### Code Quality Checks (Optional but Recommended)
- [ ] Run checkstyle: `mvn checkstyle:check -f clients/pom.xml -q`
- [ ] Result: **BUILD SUCCESS**
- [ ] Run findbugs: `mvn findbugs:check -f clients/pom.xml -q` (if configured)
- [ ] Result: **BUILD SUCCESS**

## Post-Implementation

### Documentation
- [ ] Update project CHANGELOG (if applicable)
- [ ] Update any relevant ADRs (Architecture Decision Records)
- [ ] Add commit message explaining the refactoring
- [ ] Update any affected documentation

### Git Commit
- [ ] Stage all changes: `git add clients/ jmh-benchmarks/ checkstyle/`
- [ ] Create commit:
  ```bash
  git commit -m "Refactor: Rename RecordAccumulator to BatchAccumulator

  The RecordAccumulator class manages batches of records
  (ConcurrentMap<TopicPartition, Deque<ProducerBatch>>), not
  individual records. Renaming to BatchAccumulator better describes
  its actual responsibility.

  - Rename RecordAccumulator.java to BatchAccumulator.java
  - Rename RecordAccumulatorTest.java to BatchAccumulatorTest.java
  - Rename RecordAccumulatorFlushBenchmark.java to BatchAccumulatorFlushBenchmark.java
  - Update all imports, field types, and references in 12 files
  - Update comment references in 3 documentation files
  - Update checkstyle configuration

  All tests passing. No functional changes."
  ```

### Push (if using git)
- [ ] Push commit: `git push origin <branch-name>`
- [ ] Create pull request on GitHub/GitLab (if applicable)
- [ ] Request code review from team lead
- [ ] Merge after approval

## Rollback Plan (If Needed)

If issues arise and rollback is needed:

- [ ] Revert git commit: `git revert <commit-hash>`
- [ ] Or reset to previous commit: `git reset --hard <previous-commit>`
- [ ] Delete newly created files
- [ ] Restore old file names if manual undo needed

## Final Sign-Off

- [ ] All tests passing
- [ ] Code review completed
- [ ] No compilation errors
- [ ] No FindBugs/Checkstyle violations
- [ ] Commit pushed and merged
- [ ] Documentation updated
- [ ] Team notified of changes

**Refactoring Status**: ✅ COMPLETE

**Date Completed**: _______________
**Completed By**: _______________
**Reviewed By**: _______________

---

## Notes & Issues

### Issues Encountered
1. ___________________________________________________________________
2. ___________________________________________________________________
3. ___________________________________________________________________

### Resolutions
1. ___________________________________________________________________
2. ___________________________________________________________________
3. ___________________________________________________________________

### Time Spent
- Planning: _______ minutes
- File renames: _______ minutes
- Code changes: _______ minutes
- Testing/Verification: _______ minutes
- **Total**: _______ minutes

### Lessons Learned
- ___________________________________________________________________
- ___________________________________________________________________
- ___________________________________________________________________
