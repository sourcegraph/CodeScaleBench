# Apache Kafka Contributor Guide

This guide is designed to help new contributors understand the Kafka development workflow, including how to build the project, run tests, understand the CI pipeline, and submit code for review.

## 1. Build Prerequisites

### Java Requirements

Kafka requires **Java 8 or higher** and builds/tests against multiple Java versions:
- **Java 8, 11, 17, and 21** are officially tested
- Java 8 support is deprecated (planned for removal in Kafka 4.0)
- Java 11 support for the broker and tools is deprecated (planned for removal in Kafka 4.0)
- When building, the `release` parameter is set to `8` to ensure binaries are compatible with Java 8+

**Recommendation**: Use Java 11 or 17 for development. Java 21 may have issues with some build tools (e.g., Spotless).

### Scala Requirements

Kafka supports multiple Scala versions:
- **Scala 2.13.x** (default)
- **Scala 2.12.x** (deprecated, planned for removal in Kafka 4.0)

### Build Tool

Apache Kafka uses **Gradle** as its build system. You'll interact with it via:
- `./gradlew` — Gradle wrapper (uses a specific Gradle version)
- `./gradlewAll` — Runs tasks for all supported Scala versions

### System Dependencies

- **Docker** (for running system tests)
- **Git** (for version control)
- **Maven** (for some specialized tasks like Streams Quickstart archetype publication)

## 2. Gradle Build System

### Overview

Kafka is a multi-module project with the following key modules:

- `clients` — Kafka client libraries (Producer, Consumer, Admin)
- `core` — Kafka broker
- `connect` — Kafka Connect framework and connectors
- `streams` — Kafka Streams library
- `server`, `server-common` — Server utilities
- `group-coordinator`, `transaction-coordinator` — Coordination components
- `storage`, `raft` — Storage and Raft consensus
- `tools`, `trogdor` — CLI tools and testing utilities
- `tests` — System integration tests

### Key Gradle Commands

#### Building

```bash
# Build all JAR files
./gradlew jar

# Build for a specific Scala version
./gradlew -PscalaVersion=2.12 jar

# Build for all Scala versions (2.12 and 2.13)
./gradlewAll jar

# Build a specific module
./gradlew core:jar
./gradlew clients:jar

# Build source JAR
./gradlew srcJar

# Build aggregated Javadoc
./gradlew aggregatedJavadoc

# Build Javadoc per module
./gradlew javadoc
./gradlew javadocJar

# Build Scaladoc
./gradlew scaladoc
./gradlew scaladocJar

# Clean build artifacts
./gradlew clean

# Create a release tarball
./gradlew clean releaseTarGz
```

#### IDE Integration

```bash
# Generate IntelliJ IDEA project files
./gradlew idea

# Generate Eclipse project files
./gradlew eclipse
```

#### Dependency Management

```bash
# List all dependencies for the root project
./gradlew allDeps

# Show dependency insights for a specific library
./gradlew allDepInsight --configuration runtimeClasspath --dependency com.fasterxml.jackson.core:jackson-databind

# Check for available dependency updates
./gradlew dependencyUpdates
```

### Build Configuration

Key build properties can be set via `-P` flags:

```bash
./gradlew test -PmaxParallelForks=2        # Limit parallel test processes
./gradlew test -PscalaVersion=2.13         # Specify Scala version
./gradlew -PskipSigning=true jar            # Skip artifact signing
./gradlew test -Dorg.gradle.parallel=false # Disable parallel builds
```

### Auto-generated Messages

The Kafka protocol defines request/response messages that are auto-generated. When switching branches or if code generation fails:

```bash
./gradlew processMessages processTestMessages
```

### Module-Specific Building

For `Streams`, which has multiple sub-projects:

```bash
# Run all Streams tests
./gradlew :streams:testAll

# Build examples
./gradlew streams:examples:jar
```

## 3. Running Tests

Kafka has three types of tests:

### Unit Tests

Run using Gradle's `test` task. These test individual components in isolation.

```bash
# Run all unit tests
./gradlew test

# Run tests for a specific module
./gradlew clients:test
./gradlew core:test

# Run a specific test class
./gradlew clients:test --tests RequestResponseTest

# Run a specific test method
./gradlew core:test --tests kafka.api.ProducerFailureHandlingTest.testCannotSendToInternalTopic
./gradlew clients:test --tests org.apache.kafka.clients.MetadataTest.testTimeToNextUpdate

# Force re-running tests without code changes
./gradlew test --rerun
./gradlew unitTest --rerun

# Run tests with specific JVM flags for debugging
./gradlew clients:test --tests RequestResponseTest -PshowStandardStreams=true
```

### Integration Tests

```bash
# Run integration tests
./gradlew integrationTest

# Run integration tests for a module
./gradlew core:integrationTest
```

### System/Distributed Tests

These tests validate Kafka behavior in a distributed environment using **ducktape**:

```bash
# Build system test dependencies
./gradlew systemTestLibs

# Run all system tests via Docker
bash tests/docker/run_tests.sh

# Run a specific test file
TC_PATHS="tests/kafkatest/tests/client/pluggable_test.py" bash tests/docker/run_tests.sh

# Run a specific test class
TC_PATHS="tests/kafkatest/tests/client/pluggable_test.py::PluggableConsumerTest" bash tests/docker/run_tests.sh

# Run a specific test method
TC_PATHS="tests/kafkatest/tests/client/pluggable_test.py::PluggableConsumerTest.test_start_stop" bash tests/docker/run_tests.sh

# Run with debug output
_DUCKTAPE_OPTIONS="--debug" bash tests/docker/run_tests.sh

# Rebuild and run tests
REBUILD="t" bash tests/docker/run_tests.sh
```

### Test Frameworks

- **Unit tests** use **JUnit 5** and **Mockito**
- **System tests** use **ducktape** (a distributed testing framework)

### Test Configuration

```bash
# Run tests with coverage reporting
./gradlew reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false

# Specify test retries (default: 1 retry, max 5)
./gradlew test -PmaxTestRetries=1 -PmaxTestRetryFailures=5

# Show test logs in console
./gradlew test -PshowStandardStreams=true

# Specify test logging events
./gradlew test -PtestLoggingEvents=started,passed,skipped,failed
```

### Log Configuration

By default, test logs are minimal. To see more logs during testing:

1. Edit `module/src/test/resources/log4j.properties` to adjust log levels (e.g., change to `log4j.logger.org.apache.kafka=INFO`)
2. Re-run the tests:
   ```bash
   ./gradlew cleanTest clients:test --tests NetworkClientTest
   ```
3. View results in `clients/build/test-results/test` directory

## 4. CI Pipeline

### Jenkins

Kafka uses **Apache Jenkins** as the primary CI system. The configuration is defined in the `Jenkinsfile` at the repository root.

#### Jenkins Pipeline Stages

The pipeline runs in parallel for different Java and Scala combinations:

1. **JDK 8 and Scala 2.12**
   - Runs validation checks (checkstyle, spotbugs)
   - Runs all tests
   - Builds Kafka Streams archetype
   - Timeout: 8 hours

2. **JDK 11 and Scala 2.13**
   - Runs validation checks
   - Runs tests only on development branches (not on pull requests)
   - Timeout: 8 hours

3. **JDK 17 and Scala 2.13**
   - Runs validation checks
   - Runs tests only on development branches
   - Timeout: 8 hours

4. **JDK 21 and Scala 2.13**
   - Runs validation checks
   - Runs all tests
   - Timeout: 8 hours

#### What Jenkins Validates

The `doValidation()` function runs all checks except tests (tests are run separately):

```bash
./retry_zinc ./gradlew -PscalaVersion=$SCALA_VERSION clean check -x test \
    --profile --continue -PxmlSpotBugsReport=true -PkeepAliveMode="session"
```

This includes:
- **Checkstyle** — Code style validation
- **Spotbugs** — Bug detection via static analysis
- **SpotlessCheck** — Import order and formatting validation
- **RAT** — License header validation

#### Test Execution in Jenkins

Jenkins runs tests with these settings:
```bash
./gradlew -PscalaVersion=$SCALA_VERSION test \
    --profile --continue -PkeepAliveMode="session" \
    -PtestLoggingEvents=started,passed,skipped,failed \
    -PignoreFailures=true -PmaxParallelForks=2 \
    -PmaxTestRetries=1 -PmaxTestRetryFailures=10
```

- Max 2 parallel test forks
- Up to 1 retry per failed test (max 10 retry failures total)
- Test results are published as JUnit XML

### GitHub Actions

GitHub Actions workflows are primarily used for Docker image building and security scanning:

- Docker image builds
- Docker Official Image operations
- CVE scanning (Trivy)

The main CI pipeline **runs on Jenkins**, not GitHub Actions.

### Build Caching

Kafka uses Gradle Build Scans for visibility into build performance:
- Remote cache is disabled
- Local caching is disabled in CI environments
- Build scans are published to `https://ge.apache.org`

## 5. Code Review Process

### Overview

Kafka follows the Apache Way for code contribution and review. The process involves JIRA for issue tracking and Apache GitHub for pull requests.

### Finding and Claiming Issues

1. Browse open issues on [Apache JIRA - Kafka](https://issues.apache.org/jira/browse/KAFKA)
2. Look for issues marked as:
   - **Unresolved** status
   - **Beginner-friendly** labels (if applicable)
   - **No assignee** (not claimed by another contributor)
3. Comment on the issue to claim it (e.g., "I'd like to work on this issue")
4. Create a JIRA account if you don't have one (Apache JIRA)

### Branch Naming

While not strictly enforced, the convention is:

```
KAFKA-<issue-number>
```

Example: `KAFKA-15123` for a branch fixing KAFKA-15123

You can also use descriptive names:
```
bugfix/consumer-lag-calculation
feature/kraft-rebalance
```

### Preparing Your Code

Before submitting a pull request, ensure:

1. **Code Quality Checks**:
   ```bash
   # Run all validation checks
   ./gradlew checkstyleMain checkstyleTest spotlessCheck

   # Auto-fix import ordering (requires JDK 11+, not JDK 21)
   ./gradlew spotlessApply

   # Check for potential bugs
   ./gradlew spotbugsMain spotbugsTest -x test
   ```

2. **Testing**:
   ```bash
   # Run tests relevant to your changes
   ./gradlew <module>:test

   # Run full test suite if making core changes
   ./gradlew test
   ```

3. **Documentation**:
   - Update Javadoc/Scaladoc for public APIs
   - Update relevant documentation in `docs/` directory
   - Include upgrade notes if behavior changes

### Creating a Pull Request

1. Fork the repository on GitHub (if not a committer)
2. Push your branch to your fork or the main repository
3. Create a PR against the `main` branch:
   - **Title**: Start with the JIRA issue number
     ```
     KAFKA-15123: Fix consumer lag calculation in edge cases
     ```
   - **Description**: Follow the PR template in `PULL_REQUEST_TEMPLATE.md`:
     - **Summary**: 2-3 sentences describing the change
     - **Testing Strategy**: Explain how you tested (unit tests, integration tests, etc.)
     - **Risk Assessment**: Note any areas that could be affected

4. Example PR description:
   ```markdown
   ## Summary
   Fixes consumer lag calculation when offset resets occur. Previously,
   lag would spike during offset resets, now it remains stable.

   ## Testing
   - Added 2 unit tests for offset reset scenarios
   - Existing test suite passes
   - Manual testing in KRaft mode confirms stable lag

   ## Risk Assessment
   Low risk - changes only the lag calculation logic, existing tests
   validate behavior. No API changes.
   ```

### Code Review

The PR will be reviewed by Kafka committers and contributors:

1. **Reviewers** are assigned automatically or added by the PR author
2. **Checks run on Jenkins** (all combinations of Java/Scala versions):
   - Build must succeed
   - All tests must pass
   - Code quality checks must pass
3. **Feedback**: Reviewers may request changes
4. **Approval**: At least one committer must approve
5. **Merge**: A committer will merge the PR once approved

### Expectations for Reviewers

- Code must be reviewed before merging
- All CI checks must pass
- Code must follow Kafka's style guidelines
- New public APIs require careful review
- Changes to core protocols need KIP (Kafka Improvement Proposal) discussion

### Getting Help

- **Mailing List**: `dev@kafka.apache.org` for discussion
- **JIRA Comments**: Use the JIRA issue to discuss design
- **Slack**: Join the Apache Kafka Slack workspace (if available)
- **Confluence**: See [Contributing Code Changes](https://cwiki.apache.org/confluence/display/KAFKA/Contributing+Code+Changes) wiki

## 6. Developer Workflow Example

Here's a complete example workflow for a contributor fixing a bug:

### Step 1: Find and Claim an Issue

```bash
# Navigate to JIRA
# Find issue: KAFKA-15123 "Consumer lag calculation is inaccurate"
# Comment: "I'd like to work on this issue"
```

### Step 2: Set Up Your Environment

```bash
# Clone the repository
git clone https://github.com/apache/kafka.git
cd kafka

# Create a branch from main (or master)
git checkout main
git pull origin main
git checkout -b KAFKA-15123
```

### Step 3: Make Code Changes

```bash
# Edit the relevant files (e.g., consumer lag calculation)
# Files might be in: clients/src/main/java/org/apache/kafka/clients/

# Add unit tests for your changes
# File: clients/src/test/java/org/apache/kafka/clients/...

# Verify your changes compile
./gradlew clients:compileJava clients:compileTestJava
```

### Step 4: Run Tests

```bash
# Run tests for the affected module
./gradlew clients:test

# Run a specific test class to verify your fix
./gradlew clients:test --tests ConsumerLagTest

# Run the full test suite (optional but recommended for core changes)
./gradlew test
```

### Step 5: Code Quality Checks

```bash
# Fix import ordering and formatting
./gradlew spotlessApply

# Run checkstyle and spotbugs
./gradlew checkstyleMain checkstyleTest spotlessCheck
./gradlew spotbugsMain spotbugsTest -x test

# Address any warnings or errors reported
```

### Step 6: Commit Your Changes

```bash
# Stage files
git add clients/src/main/java/...
git add clients/src/test/java/...

# Create a meaningful commit message
git commit -m "KAFKA-15123: Fix consumer lag calculation in offset reset scenarios

- Modified ConsumerLagCalculator to handle offset resets correctly
- Added unit tests for edge cases
- Verified with integration tests

Testing: Unit tests added, all existing tests pass, manual testing
confirms lag remains stable during offset resets."
```

### Step 7: Push Your Branch

```bash
git push origin KAFKA-15123
```

### Step 8: Create a Pull Request

1. Go to https://github.com/apache/kafka
2. Click "New Pull Request"
3. Select your branch `KAFKA-15123` against `main`
4. Fill in the PR template:

```markdown
## Summary
Fixes consumer lag calculation when offset resets occur. Previously,
lag would spike temporarily, now it remains stable.

## Testing
- Added ConsumerLagCalculatorTest with 3 new test methods for offset resets
- Ran full client test suite: ./gradlew clients:test
- All tests pass

## Risk Assessment
Low - Changes are isolated to lag calculation logic. No protocol or
API changes. All existing tests validate behavior.
```

5. Click "Create Pull Request"

### Step 9: Monitor CI and Respond to Feedback

```bash
# Wait for Jenkins CI to run (15-30 minutes typical)
# Jenkins will run on multiple Java/Scala combinations

# If tests fail:
# - Review the Jenkins logs
# - Make fixes locally
# - Test again: ./gradlew clients:test
# - Push updated changes: git push origin KAFKA-15123

# If reviewers request changes:
# - Make the requested changes
# - Push again: git push origin KAFKA-15123
# - Comment on PR confirming changes have been made
```

### Step 10: Address Review Comments

Example review feedback and response:

```
Reviewer: "The test case for offset reset seems incomplete.
Can you also test the case where the offset resets to a future value?"

Response:
- Add another test method: testLagCalculationOffsetResetToFuture()
- Push the change
- Comment: "Added test for future offset reset scenario"
```

### Step 11: Final Approval and Merge

Once CI passes and a committer approves:

```
Committer: "Looks good! Merging now."
[PR is merged by committer]

# Delete your local branch
git checkout main
git pull origin main
git branch -d KAFKA-15123
```

### Step 12: Celebrate!

Your contribution is now part of Apache Kafka!

The issue will be closed and your commit will appear in:
- The git history
- Release notes for the next version
- Your GitHub profile

## Additional Resources

### Documentation
- **Build Instructions**: [README.md](https://github.com/apache/kafka/blob/trunk/README.md)
- **Contributing Guide**: https://kafka.apache.org/contributing.html
- **Contributing Code Changes**: https://cwiki.apache.org/confluence/display/KAFKA/Contributing+Code+Changes
- **Development Documentation**: [CONTRIBUTING.md](https://github.com/apache/kafka/blob/trunk/CONTRIBUTING.md)

### Tools and Commands

**Gradle Wrapper**: Always use `./gradlew` instead of `gradle` to ensure the correct version is used.

**gradlewAll Script**: Use this to test with all Scala versions:
```bash
./gradlewAll test
./gradlewAll jar
```

**Retry Zinc**: Jenkins uses `./retry_zinc` which retries the Scala incremental compiler if transient failures occur.

### Performance Tips

- Use `-Dorg.gradle.parallel=false` to disable parallel builds when debugging
- Use `-PmaxParallelForks=1` to run tests serially (slower but more deterministic)
- Use `--profile` flag with Gradle to identify slow tasks
- Build only the modules you changed for faster feedback
- Use IDE integration (IntelliJ IDEA has excellent Gradle support)

### Common Issues

**Java Version Issues**:
- Spotless has issues with Java 21; use JDK 11 or 17
- Make sure `release` parameter is set to ensure Java 8 compatibility

**Import Order Issues**:
- Run `./gradlew spotlessApply` to auto-fix
- Requires JDK 11+ (not JDK 21)

**Flaky Tests**:
- Re-run with `--rerun` flag: `./gradlew test --rerun`
- If still failing, file an issue in JIRA

**Slow Builds**:
- Disable parallel compilation: `-Dorg.gradle.parallel=false`
- Use build scan insights: Check build logs for bottlenecks
- Consider just building the module you changed

---

**Last Updated**: February 2024 | **Kafka Version**: 3.9.0 | **Contributing**: See the official contributing guidelines at https://kafka.apache.org/contributing.html
