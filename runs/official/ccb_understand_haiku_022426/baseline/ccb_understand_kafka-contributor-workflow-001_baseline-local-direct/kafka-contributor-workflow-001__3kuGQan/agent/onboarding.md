# Apache Kafka Contributor Guide

## 1. Build Prerequisites

### Java Version Requirements
Apache Kafka supports multiple Java versions:
- **Java 8**: Supported but deprecated project-wide since Kafka 3.0 (planned removal in Kafka 4.0)
- **Java 11**: Supported but deprecated for broker and tools since Kafka 3.7 (planned removal in Kafka 4.0)
- **Java 17**: Fully supported (recommended)
- **Java 21**: Fully supported

The build generates binaries compatible with Java 8+ by setting the `release` parameter in javac and scalac to `8`.

### Scala Version Requirements
- **Scala 2.12.x**: Supported but deprecated since Kafka 3.0 (removal planned in Kafka 4.0)
- **Scala 2.13.x**: Default (currently 2.13.14)

### Required Tools
- **Gradle**: Uses Gradle Wrapper (`./gradlew`) - no separate installation needed
- **Maven**: Required for Kafka Streams quickstart archetype tests (Maven 3.x latest)
- **Git**: For version control (installed and set up)

### Optional Tools for System Tests
- **Docker**: 1.12.3 or higher (for running system integration tests)
- **VirtualBox** and **Vagrant**: For local system testing with virtual machines
- **Python 3**: For system tests using the ducktape framework

### Verification
Check Java installation:
```bash
java -version
```

---

## 2. Gradle Build System

### Overview
Kafka uses Gradle as its primary build system with a multi-module project structure. The build includes:
- Multiple sub-projects/modules (clients, core, streams, connect, etc.)
- Support for both Java and Scala
- Code quality checks (checkstyle, spotbugs)
- Test coverage and reporting

### Key Build Files
- **`build.gradle`**: Root build configuration (112KB, defines common tasks and configuration)
- **`settings.gradle`**: Declares all sub-projects and modules
- **`gradle.properties`**: Version (3.9.0), Scala version (2.13.14), and JVM args
- **`gradle/`**: Directory containing dependency definitions and build scripts

### Module Structure
Main modules include:
- `clients`: Kafka client library
- `core`: Core broker implementation
- `streams`: Kafka Streams library
- `connect`: Kafka Connect framework
- `server`: Broker server components
- `storage`: Storage layer
- `raft`: RAFT consensus implementation
- `tools`: CLI tools and utilities
- `examples`: Example applications
- `jmh-benchmarks`: Microbenchmark suite

For a complete list, see `settings.gradle`.

### Essential Gradle Tasks

**Build Tasks:**
- `./gradlew jar` - Build production JARs
- `./gradlew srcJar` - Build source JARs
- `./gradlew javadoc` - Generate Javadoc
- `./gradlew scaladoc` - Generate Scaladoc
- `./gradlew aggregatedJavadoc` - Generate aggregated Javadoc across all modules

**Module-Specific Tasks:**
- `./gradlew <module>:jar` - Build specific module JAR (e.g., `./gradlew core:jar`)
- `./gradlew <module>:test` - Run tests for specific module (e.g., `./gradlew clients:test`)
- `./gradlew :streams:testAll` - Run all Streams sub-project tests

**Code Quality Tasks:**
- `./gradlew checkstyleMain checkstyleTest spotlessCheck` - Run code style checks
- `./gradlew spotlessApply` - Auto-fix code formatting (requires JDK 11+, has issues with Java 21)
- `./gradlew spotbugsMain spotbugsTest -x test` - Run static analysis

**Other Useful Tasks:**
- `./gradlew clean` - Clean all build artifacts
- `./gradlew tasks` - List all available tasks
- `./gradlew allDeps` - Show all dependencies recursively
- `./gradlew dependencyUpdates` - Check for dependency updates
- `./gradlew processMessages processTestMessages` - Regenerate auto-generated message data

### Gradle Command-Line Options

**For Testing:**
- `-PmaxParallelForks=N` - Set number of parallel test processes (default: number of CPU cores)
- `-PmaxTestRetries=N` - Set max retries per failed test (default: 1)
- `-PmaxTestRetryFailures=N` - Set max total test retries (default: 5)
- `-PignoreFailures=true` - Ignore test failures (continue build)
- `-PshowStandardStreams=true` - Show test stdout/stderr on console
- `-PtestLoggingEvents=started,passed,skipped,failed` - Configure test logging

**For Scala Version:**
- `-PscalaVersion=2.12` or `-PscalaVersion=2.13` - Build with specific Scala version
- `./gradlewAll` command builds/tests with all supported Scala versions

**For Code Quality:**
- `-PxmlSpotBugsReport=true` - Generate XML instead of HTML spotbugs reports
- `-PenableTestCoverage=true` - Enable code coverage tracking (adds ~15-20% overhead)

**For Build Configuration:**
- `-PskipSigning=true` - Skip artifact signing
- `-PkeepAliveMode=session` - Keep Scala compiler daemon alive for session (speeds up builds)
- `--profile` - Show build timing profile
- `--continue` - Continue build even if tasks fail

### Release Build
```bash
./gradlew clean releaseTarGz
```
Output location: `./core/build/distributions/`

### Maven Publishing
```bash
./gradlew publishToMavenLocal              # Install to local Maven repo
./gradlewAll publishToMavenLocal           # Install all Scala versions
./gradlew publish                          # Publish to configured Maven repo
```

Requires `~/.gradle/gradle.properties`:
```properties
mavenUrl=https://...
mavenUsername=...
mavenPassword=...
signing.keyId=...
signing.password=...
signing.secretKeyRingFile=...
```

---

## 3. Running Tests

### Test Framework
Kafka uses **JUnit 5 (Jupiter)** for unit and integration tests. Tests are organized by module.

### Test Types

**Unit Tests** (pure Java/Scala, no external services):
```bash
./gradlew unitTest                        # All unit tests
./gradlew <module>:unitTest              # Specific module unit tests
```

**Integration Tests** (may require Zookeeper, Kafka broker, etc.):
```bash
./gradlew integrationTest                # All integration tests
./gradlew <module>:integrationTest       # Specific module integration tests
```

**Both Unit + Integration Tests:**
```bash
./gradlew test                           # Default - runs both types
./gradlew <module>:test                  # Specific module
```

### Running Specific Tests

**By Test Class:**
```bash
./gradlew clients:test --tests RequestResponseTest
./gradlew core:test --tests kafka.api.ProducerFailureHandlingTest
```

**By Test Method:**
```bash
./gradlew core:test --tests kafka.api.ProducerFailureHandlingTest.testCannotSendToInternalTopic
./gradlew clients:test --tests org.apache.kafka.clients.MetadataTest.testTimeToNextUpdate
```

**Run Test Multiple Times:**
```bash
I=0; while ./gradlew clients:test --tests RequestResponseTest --rerun --fail-fast; do (( I=$I+1 )); echo "Completed run: $I"; sleep 1; done
```

**With Increased Logging:**
1. Modify `log4j.properties` in the test module's `src/test/resources/` directory
2. Change log level from `WARN` to `INFO` for desired logger
3. Run test:
   ```bash
   ./gradlew cleanTest <module>:test --tests <TestClassName>
   ```
4. View logs in: `<module>/build/test-results/test/`

### Test Retries
Default: Each failed test retries once, max 5 retries per test run.

Customize:
```bash
./gradlew test -PmaxTestRetries=3 -PmaxTestRetryFailures=10
```

### Test Coverage Reports
```bash
./gradlew reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false
./gradlew <module>:reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false
```

### System/Integration Tests
Located in: `tests/` directory

Uses **ducktape** framework for distributed testing. Can be run:
1. **Docker-based** (recommended for local development):
   ```bash
   ./gradlew clean systemTestLibs
   bash tests/docker/run_tests.sh
   ```

2. **Vagrant-based** (requires ~10GB RAM):
   ```bash
   tests/bootstrap-test-env.sh
   vagrant/vagrant-up.sh
   ./gradlew systemTestLibs
   ducktape tests/kafkatest/tests
   ```

See `tests/README.md` for comprehensive system test documentation.

### Test Output
Failed test output is saved to: `<module>/build/reports/testOutput/<TestClass>.test.stdout`

---

## 4. CI Pipeline

### CI System
**Apache Jenkins** - The primary CI system for Kafka

Configuration file: `Jenkinsfile` (declarative pipeline)

### CI Jobs

The Jenkins pipeline runs **4 parallel build jobs** on pull requests and commits:

1. **JDK 8 + Scala 2.12** (8-hour timeout)
   - Tools: JDK 1.8, Maven 3.x
   - Runs: Validation + Full Tests + Streams Archetype Test

2. **JDK 11 + Scala 2.13** (8-hour timeout)
   - Tools: JDK 11
   - Runs: Validation + Tests (dev branch only)

3. **JDK 17 + Scala 2.13** (8-hour timeout)
   - Tools: JDK 17
   - Runs: Validation + Tests (dev branch only)

4. **JDK 21 + Scala 2.13** (8-hour timeout)
   - Tools: JDK 21
   - Runs: Validation + Full Tests

### CI Checks Performed

**Code Validation (`doValidation`):**
```bash
./gradlew -PscalaVersion=$SCALA_VERSION clean check -x test \
    --profile --continue -PxmlSpotBugsReport=true -PkeepAliveMode="session"
```

Includes:
- Checkstyle (code style enforcement)
- Spotbugs (static analysis for bugs)
- Spotless (import organization)
- RAT (license header verification)
- Dependency checks

**Test Execution (`doTest`):**
```bash
./gradlew -PscalaVersion=$SCALA_VERSION test \
    --profile --continue -PkeepAliveMode="session" \
    -PtestLoggingEvents=started,passed,skipped,failed \
    -PignoreFailures=true -PmaxParallelForks=2 \
    -PmaxTestRetries=1 -PmaxTestRetryFailures=10
```

**Streams Archetype Test** (JDK 8 only):
- Builds Kafka Streams JAR and publishes locally
- Tests Streams quickstart Maven archetype generation
- Compiles archetype-generated project

### GitHub Actions
Secondary CI system for Docker-related tasks:
- `docker_build_and_test.yml` - Build and test Docker images
- `docker_official_image_build_and_test.yml` - Official image builds
- `docker_rc_release.yml` - Release candidate builds
- `docker_scan.yml` - Container scanning
- `stale.yml` - Stale issue/PR management

Location: `.github/workflows/`

### CI Failure Handling
- **On Main/Dev Branch**: Failures notify `dev@kafka.apache.org`
- **On Pull Request**: Failures appear in PR checks with links to full test results
- **Aborts**: Previous builds are aborted if a new build is queued for same PR

---

## 5. Code Review Process

### Step 1: Find or Create a JIRA Ticket

**Finding Existing Tickets:**
1. Go to [JIRA](https://issues.apache.org/jira/browse/KAFKA)
2. Search for existing tickets related to your change
3. Use the `KAFKA-XXXX` format (e.g., KAFKA-15932)

**Creating New Tickets:**
- For non-trivial changes, create a new JIRA ticket with:
  - Descriptive title summarizing the problem/feature
  - Detailed description of the issue and proposed solution
  - Appropriate type (Bug, Feature, Improvement, etc.)
  - Priority
  - Component(s) affected
- Assign ticket to yourself to avoid duplicated effort

### Step 2: Set Up Your Branch

```bash
git clone https://github.com/apache/kafka.git
cd kafka
git checkout -b kafka-XXXX/description
```

**Branch Naming Convention:**
- Format: `kafka-XXXX/short-description` (kebab-case)
- Example: `kafka-15932/improve-consumer-group-rebalancing`

### Step 3: Make Code Changes

**Code Quality Requirements:**

Before submitting:
1. **Run code formatting:**
   ```bash
   ./gradlew spotlessApply  # Fix imports and formatting (JDK 11+, not Java 21)
   ```

2. **Run code style checks:**
   ```bash
   ./gradlew checkstyleMain checkstyleTest spotlessCheck
   ```

3. **Run static analysis:**
   ```bash
   ./gradlew spotbugsMain spotbugsTest -x test
   ```

4. **Write tests** for any behavior changes:
   - Unit tests required
   - Integration tests recommended
   - System tests recommended for larger changes

5. **Run tests locally:**
   ```bash
   ./gradlew test                    # Full test suite
   ./gradlew <module>:test          # Module-specific tests
   ./gradlew <module>:test --tests ClassName  # Specific test
   ```

### Step 4: Create a Pull Request

**PR Title Format:**
```
KAFKA-XXXX: Brief description of change (under 70 chars)
```

Examples:
- `KAFKA-15932: Improve consumer group rebalancing algorithm`
- `KAFKA-16001: Fix race condition in metadata update`
- `[WIP] KAFKA-15950: Add support for KRaft clusters` (for work-in-progress)

**PR Description Template:**
Include the following sections:

```markdown
## Summary
Brief 1-3 sentence summary of the change

## Motivation and Context
Why is this change needed? What problem does it solve?

## Testing Strategy
- Unit tests added for: [list specific test cases]
- Integration tests added for: [list specific test cases]
- System tests considered: [yes/no and rationale]
- Manual testing: [describe if applicable]

## Checklist
- [ ] Code follows style guidelines
- [ ] Tests added/modified as needed
- [ ] Documentation updated if applicable
- [ ] Change is backwards compatible OR marked as breaking

## License
I agree to license this work under the terms of the Apache License, Version 2.0.
```

**Submitting the PR:**
1. Push your branch to your forked repository
2. Create PR against `apache/kafka` main branch
3. PR title will become the commit message, PR body becomes detailed commit message

### Step 5: Code Review and CI

**Automatic Checks:**
- Jenkins CI runs automatically on all PRs
- Four parallel jobs (JDK 8/11/17/21 + Scala combinations)
- Results appear in PR checks section with links to logs

**Code Review Process:**
1. **Request Reviewers:**
   - Tag relevant maintainers/experts as reviewers
   - Add @mentions in comments to request specific reviews
   - Example: `@someuser could you review the metrics changes?`

2. **Address Feedback:**
   - Reviewers will comment on changes
   - Address feedback by making additional commits (don't amend)
   - Add comments explaining your changes
   - Request re-review when ready

3. **Approval:**
   - Reviewers use GitHub's "Approve" button to indicate acceptance
   - Approval indicates the reviewer takes ownership of the patch
   - At least one approval required before merging

### Step 6: Merge

**Automatic Merge:**
- Project uses squash-and-merge strategy
- PR title + description become the squashed commit message
- Once approved and all checks pass, committer can merge

**After Merge:**
- PR automatically closes
- Associated JIRA ticket automatically closes
- Credit assigned to primary contributor

### Review Expectations

**Code Review Standards:**
- All code changes must be reviewed by at least one committer
- Large changes may require multiple reviewers
- Design review before implementation for significant features
- Tests must be included for behavior changes

**Review Timeline:**
- Active community - typically 1-3 days for feedback
- Be patient and responsive to feedback
- Consider contributing to other PRs while waiting for reviews

**Common Review Comments:**
- Missing or inadequate tests
- Inconsistent code style
- Incomplete documentation
- Backwards compatibility concerns
- Performance impact analysis needed
- Missing error handling

---

## 6. Developer Workflow Example

### Scenario
As a new contributor, you want to fix a bug that causes Kafka consumers to incorrectly handle rebalancing when members join/leave the group.

### Step-by-Step Workflow

#### 1. Prepare Development Environment
```bash
# Clone repository
git clone https://github.com/apache/kafka.git
cd kafka

# Create feature branch
git checkout -b kafka-15932/fix-consumer-rebalancing

# Build the project to ensure setup works
./gradlew build
```

#### 2. Find and Examine Existing Tests
```bash
# Search for related tests
find . -name "*Test.java" | xargs grep -l "rebalance\|consumer.*group"

# Run existing consumer tests
./gradlew clients:test --tests org.apache.kafka.clients.consumer.*
```

#### 3. Locate Relevant Code
```bash
# Understand module structure
./gradlew tasks | grep -i client

# Find consumer coordinator/rebalancing code
find ./clients -name "*.java" | xargs grep -l "Rebalance\|GroupCoordinator"
```

#### 4. Make Changes

Example: Fix bug in `clients/src/main/java/org/apache/kafka/clients/consumer/internals/AbstractCoordinator.java`

```java
// Before: Incorrect rebalance logic
public void handleRebalance() {
  // buggy implementation
}

// After: Fixed rebalance logic
public void handleRebalance() {
  // correct implementation
  validateMemberState();
  syncGroupMetadata();
}
```

#### 5. Write Tests

Create test file: `clients/src/test/java/org/apache/kafka/clients/consumer/internals/AbstractCoordinatorTest.java`

```java
@Test
public void testRebalanceOnMemberJoin() {
  // Arrange
  ConsumerGroupMetadata group = createTestGroup();

  // Act
  coordinator.handleMemberJoin(group, newMember);

  // Assert
  assertEquals(expectedState, coordinator.getState());
}

@Test
public void testRebalanceOnMemberLeave() {
  // Arrange & Act & Assert
  // Similar test for member leaving
}
```

#### 6. Run Tests Locally
```bash
# Run your new tests
./gradlew clients:test --tests AbstractCoordinatorTest

# Run all consumer tests to ensure no regression
./gradlew clients:test --tests org.apache.kafka.clients.consumer.*

# Run full test suite (recommended before PR)
./gradlew test

# Check code quality
./gradlew spotlessApply
./gradlew checkstyleMain checkstyleTest spotlessCheck
./gradlew spotbugsMain spotbugsTest -x test
```

#### 7. Commit Changes
```bash
git add -A
git commit -m "KAFKA-15932: Fix consumer rebalancing on member join/leave

- Validate member state before rebalancing
- Sync group metadata after state changes
- Add comprehensive tests for edge cases

Fixes #15932"
```

#### 8. Create Pull Request
```bash
git push -u origin kafka-15932/fix-consumer-rebalancing
```

Visit GitHub and create PR with:
- **Title:** `KAFKA-15932: Fix consumer rebalancing on member join/leave`
- **Description:** Detailed explanation with testing strategy
- **Request Reviewers:** @ mention consumer group experts

#### 9. Monitor CI
- Check that all 4 Jenkins jobs pass (JDK 8/11/17/21)
- Review any checkstyle or spotbugs warnings
- Look for test failures and debug locally

#### 10. Address Review Feedback
```bash
# Reviewer suggests improvement
git add -A
git commit -m "Address review feedback: improve error handling

- Add additional validation
- Update test coverage for edge cases"

git push origin kafka-15932/fix-consumer-rebalancing
```

#### 11. Get Approval and Merge
- Reviewer approves the changes
- All CI checks pass
- Maintainer/committer merges the PR (squash-and-merge)
- PR and JIRA ticket automatically close

#### 12. Celebrate! 🎉
Your fix is now part of Apache Kafka and will be included in the next release!

### Tips for Success

1. **Start Small:** Begin with small bug fixes or documentation improvements to learn the process
2. **Engage Early:** Discuss major features on the mailing list before implementing
3. **Read Existing Code:** Study similar code to understand patterns and conventions
4. **Test Thoroughly:** Test more than you think necessary - edge cases matter
5. **Be Patient:** Reviews take time; be responsive and respectful
6. **Follow Style:** Run spotlessApply and checkstyle before submitting
7. **Keep PRs Focused:** Each PR should address one issue - don't combine unrelated changes
8. **Document Changes:** Update relevant documentation, especially for user-facing changes
9. **Check Backwards Compatibility:** Ensure changes don't break existing APIs
10. **Participate in Community:** Answer questions, review others' PRs, engage on mailing lists

### Useful Resources

- **JIRA:** https://issues.apache.org/jira/browse/KAFKA
- **Mailing Lists:** https://kafka.apache.org/contact.html
- **Wiki:** https://cwiki.apache.org/confluence/display/KAFKA/
- **Contributing Guide:** https://kafka.apache.org/contributing.html
- **Code Changes Guide:** https://cwiki.apache.org/confluence/display/KAFKA/Contributing+Code+Changes
- **Design Docs:** https://cwiki.apache.org/confluence/display/KAFKA/KIPs (Kafka Improvement Proposals)

---

## Quick Reference

### Common Commands
```bash
# Build
./gradlew build                        # Full build
./gradlew jar                         # Build JARs only
./gradlew <module>:jar               # Build specific module

# Test
./gradlew test                        # Run all tests
./gradlew <module>:test              # Test specific module
./gradlew <module>:test --tests ClassName  # Specific test class

# Code Quality
./gradlew spotlessApply              # Fix formatting
./gradlew checkstyleMain checkstyleTest spotlessCheck  # Check style
./gradlew spotbugsMain spotbugsTest -x test  # Static analysis

# Clean
./gradlew clean                       # Clean build artifacts

# Documentation
./gradlew tasks                       # List available tasks
./gradlew aggregatedJavadoc          # Build API documentation
```

### Troubleshooting

**Build hangs or takes too long:**
```bash
# Reduce parallelism
./gradlew -PmaxParallelForks=1 test
```

**Java 21 Spotless issues:**
```bash
# Use Java 11 or 17 for spotlessApply
# Either switch Java versions or skip the spotless task
```

**Out of memory errors:**
```bash
# Increase heap size in GRADLE_OPTS
export GRADLE_OPTS="-Xmx4g"
```

**Test failures in CI but not locally:**
```bash
# Try with CI-like settings
./gradlew test -PmaxParallelForks=2 -PmaxTestRetries=1
```
