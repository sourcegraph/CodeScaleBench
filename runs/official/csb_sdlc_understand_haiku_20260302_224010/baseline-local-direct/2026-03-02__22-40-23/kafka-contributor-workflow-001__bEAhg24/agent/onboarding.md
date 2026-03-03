# Apache Kafka Contributor Guide

This guide provides new contributors with actionable steps to build, test, and submit code to the Apache Kafka project.

## 1. Build Prerequisites

### Required Tools
- **Java**: Kafka supports Java 8, 11, 17, and 21. The build targets Java 8 compatibility.
  - Recommended: Java 11 or 17 for development (Java 21 has known issues with some tools like Spotless)
  - Install from: [Oracle JDK](http://www.oracle.com/technetwork/java/javase/downloads/index.html)

- **Scala**: Two versions are supported:
  - Scala 2.12 (deprecated, being removed in 4.0)
  - Scala 2.13 (default) - currently recommended
  - The build uses Scala 2.13.14 by default

- **Gradle**: Uses Gradle wrapper (included in repo)
  - Requires no separate installation; use `./gradlew` or `./gradlewAll`

- **Git**: For cloning and managing the repository

### Optional Tools
- **Maven**: Required only for building Kafka Streams quickstart archetype
- **Python 3.10+**: For Docker testing and some system tests
- **Vagrant**: For running system tests in isolated environments

### Verification
To verify prerequisites are installed, run:
```bash
java -version
./gradlew --version
git --version
```

---

## 2. Gradle Build System

### Project Structure
Kafka uses a multi-module Gradle build. Key modules include:

```
clients/              - Java and Scala client libraries
core/                 - Broker implementation (historical, now split)
connect/              - Kafka Connect runtime and plugins
streams/              - Kafka Streams library and examples
server/               - Broker server code
group-coordinator/    - Broker group coordination
metadata/             - Metadata handling
raft/                 - RAFT consensus implementation
storage/              - Storage layer
tools/                - CLI tools
trogdor/              - System testing framework
```

### Module Configuration
The `settings.gradle` file defines all modules. Gradle treats each module as a sub-project that can be built independently.

### Core Build Commands

#### Entire Project
```bash
./gradlew jar                    # Build all JARs for the project
./gradlew clean                  # Clean all build artifacts
./gradlew tasks                  # List all available Gradle tasks
./gradlew buildEnvironment       # Show Gradle configuration
```

#### Specific Modules
```bash
./gradlew clients:jar            # Build only the clients module
./gradlew core:jar               # Build only the core module
./gradlew :streams:jar           # Build streams (note the colon)
./gradlew connect:runtime:jar    # Build a nested module
```

#### Documentation & Artifacts
```bash
./gradlew aggregatedJavadoc      # Build aggregated Javadoc for all modules
./gradlew javadoc                # Build Javadoc for each module
./gradlew scaladoc               # Build Scaladoc
./gradlew srcJar                 # Build source JARs
./gradlew releaseTarGz           # Build complete release tarball
```

### Scala Version Variations
The build supports multiple Scala versions. By default, Scala 2.13 is used.

```bash
# Build with Scala 2.12
./gradlew -PscalaVersion=2.12 jar

# Build with specific Scala version
./gradlew -PscalaVersion=2.12.19 jar

# Build all supported Scala versions
./gradlewAll jar
./gradlewAll test
```

### Build Options (Gradle Properties)
Pass options with `-P` flag:

```bash
# Parallel test execution
./gradlew test -PmaxParallelForks=4

# Test retries
./gradlew test -PmaxTestRetries=2 -PmaxTestRetryFailures=10

# Ignore test failures (CI use)
./gradlew test -PignoreFailures=true

# Show test output
./gradlew test -PshowStandardStreams=true

# Specific test logging
./gradlew test -PtestLoggingEvents=started,passed,skipped,failed

# Code signing (for publishing)
./gradlew -PskipSigning=true publishToMavenLocal
```

### Advanced Build Configuration

#### Build Performance
```bash
# Optimize scalac performance (default: inline-kafka)
./gradlew test -PscalaOptimizerMode=inline-kafka
# Options: none, method, inline-kafka, inline-scala

# Scala compiler threads (default: min(8, CPU count))
./gradlew test -PmaxScalacThreads=8

# JVM keep-alive (improves recompilation speed)
./gradlew test -PkeepAliveMode=daemon  # or session
```

#### Dependency Analysis
```bash
./gradlew allDeps                        # List all dependencies
./gradlew allDepInsight --dependency com.fasterxml.jackson.core:jackson-databind
./gradlew dependencyUpdates              # Check for available updates
```

#### IDE Integration
```bash
./gradlew eclipse                        # Generate Eclipse project files
./gradlew idea                           # Generate IntelliJ IDEA project files
```

---

## 3. Running Tests

### Test Framework
Kafka uses **JUnit 5 (JUnit Jupiter)** with JUnit Platform. Tests are tagged with `@org.junit.jupiter.api.Test` and can be marked with categories like `@Tag("integration")`.

### Running All Tests
```bash
# Run all tests (unit + integration)
./gradlew test

# Equivalent to:
./gradlew unitTest integrationTest

# Force re-run without recompiling
./gradlew test --rerun
```

### Test Categories

#### Unit Tests (no external resources)
```bash
./gradlew unitTest                       # All unit tests
./gradlew clients:unitTest               # Unit tests for clients module
./gradlew core:unitTest                  # Unit tests for core module
```

#### Integration Tests (require resources like ZooKeeper, Brokers)
```bash
./gradlew integrationTest                # All integration tests
./gradlew core:integrationTest           # Integration tests for core module
```

### Running Specific Tests

#### By Test Class
```bash
# Run a single test class
./gradlew clients:test --tests RequestResponseTest

# Run from any module
./gradlew :clients:test --tests RequestResponseTest
```

#### By Test Method
```bash
# Run a specific test method
./gradlew core:test --tests kafka.api.ProducerFailureHandlingTest.testCannotSendToInternalTopic
./gradlew clients:test --tests org.apache.kafka.clients.MetadataTest.testTimeToNextUpdate
```

#### Repeatedly Running Tests
```bash
# Re-run until test passes
I=0; while ./gradlew clients:test --tests RequestResponseTest --rerun --fail-fast; do
  (( I=$I+1 ));
  echo "Completed run: $I";
  sleep 1;
done
```

#### With Debug Logging
```bash
# Show more log output during test
# 1. Edit the module's src/test/resources/log4j.properties
#    Change: log4j.logger.org.apache.kafka=DEBUG

# 2. Run the test
./gradlew cleanTest clients:test --tests NetworkClientTest

# View logs in: clients/build/test-results/test/
```

### Test Configuration

#### Test Retries
```bash
# Set maximum retries per test and total failures
./gradlew test -PmaxTestRetries=2 -PmaxTestRetryFailures=5

# Disable retries
./gradlew test -PmaxTestRetries=0
```

#### Parallel Test Execution
```bash
# Control number of parallel test processes
./gradlew test -PmaxParallelForks=2

# Run sequentially (useful for debugging)
./gradlew test -PmaxParallelForks=1
```

#### Coverage Reports
```bash
# Generate coverage for entire project
./gradlew reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false

# Coverage for a single module
./gradlew clients:reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false
```

### Test Organization
- **Unit Tests**: `src/test/java/` and `src/test/scala/` - test single components, no external resources
- **Integration Tests**: Same directories, marked with `@Tag("integration")` - test component interactions
- **System Tests**: `tests/` directory - full end-to-end tests using Python (see `tests/README.md`)

---

## 4. CI Pipeline

### CI Systems Used

#### GitHub Actions (Primary for PR checks)
- Configured in `.github/workflows/`
- Runs on every commit to main and on PRs
- Handles:
  - Docker image builds and testing
  - Official Docker image builds
  - Repository scanning
  - Stale issue management

#### Jenkins (Main CI - See Jenkinsfile)
- Configuration: `/workspace/Jenkinsfile`
- Runs comprehensive checks on all branches
- Primary validation system for pull requests

### CI Configuration Files

#### Root Level
- `Jenkinsfile` - Jenkins pipeline configuration (primary CI)
- `.github/workflows/*.yml` - GitHub Actions workflows
- `.asf.yaml` - Apache Software Foundation specific configuration

#### Build Configuration
- `build.gradle` - Main build configuration with check tasks
- `gradle/dependencies.gradle` - All dependency versions
- `settings.gradle` - Module definitions
- `gradle.properties` - Build version and Scala version

### Checks Run on CI

The CI pipeline executes the `check` task which includes:

```bash
# The check task runs:
./gradlew check -x test  # All checks except tests
```

This includes:
1. **Checkstyle** - Code style enforcement
   ```bash
   ./gradlew checkstyleMain checkstyleTest spotlessCheck
   ```
   - Reports: `reports/checkstyle/reports/main.html` and `test.html`

2. **Spotless** - Import order and code formatting
   ```bash
   ./gradlew spotlessApply   # Fix issues automatically
   ./gradlew spotlessCheck   # Check without fixing
   ```
   - Note: Has issues with Java 21, use with Java 11 or 17

3. **Spotbugs** - Static analysis for bugs
   ```bash
   ./gradlew spotbugsMain spotbugsTest -x test
   ```
   - Reports: `reports/spotbugs/main.html` and `test.html`

4. **Apache RAT** - License header validation
   - Ensures all files have proper Apache license headers

5. **Dependency Check** - CVE vulnerability scanning
   - Identified in `build.gradle` with OWASP plugin

6. **Unit and Integration Tests**
   ```bash
   ./gradlew unitTest integrationTest
   ```

### Local CI Simulation
To run the same checks locally before pushing:

```bash
# Full validation (similar to Jenkins)
./gradlew clean check -x test
./gradlew unitTest integrationTest

# Code quality checks
./gradlew spotlessApply         # Fix imports
./gradlew checkstyleMain checkstyleTest spotlessCheck
./gradlew spotbugsMain spotbugsTest -x test

# Test coverage
./gradlew reportCoverage -PenableTestCoverage=true
```

### Jenkins Build Details
From `Jenkinsfile`:

```groovy
// Validation stage (check task)
./retry_zinc ./gradlew -PscalaVersion=$SCALA_VERSION clean check -x test \
    --profile --continue -PxmlSpotBugsReport=true -PkeepAliveMode="session"

// Testing stage
./gradlew -PscalaVersion=$SCALA_VERSION test \
    --profile --continue -PkeepAliveMode="session" \
    -PtestLoggingEvents=started,passed,skipped,failed \
    -PignoreFailures=true -PmaxParallelForks=2 -PmaxTestRetries=1
```

---

## 5. Code Review Process

### Finding JIRA Tickets

1. **JIRA Project**: https://issues.apache.org/jira/browse/KAFKA
2. **Finding Work**:
   - Filter by open issues without assignees
   - Look for "good first issue" or "help wanted" labels
   - Browse by component (broker, clients, streams, etc.)
3. **Claiming a Ticket**:
   - Create a free Apache JIRA account if you don't have one
   - Click "Assign to me" on the JIRA issue
   - Add a comment to indicate you're working on it

### Branch Naming Conventions

There is no strict enforced branch naming convention in Kafka, but the project recommends:
- Use descriptive names based on the JIRA ticket
- Examples: `KAFKA-12345-short-description`, `feature/my-feature`, `bugfix/issue-name`

### Creating a Pull Request

#### Step 1: Fork and Clone
```bash
# Fork the Apache Kafka repository on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/kafka.git
cd kafka

# Add upstream remote
git remote add upstream https://github.com/apache/kafka.git
```

#### Step 2: Create Feature Branch
```bash
# Sync with main
git fetch upstream
git checkout main
git reset --hard upstream/main

# Create feature branch (reference JIRA ticket if applicable)
git checkout -b KAFKA-12345-description
```

#### Step 3: Make Changes
```bash
# Edit files
# Run tests locally
./gradlew unitTest
./gradlew integrationTest

# Check code style
./gradlew spotlessApply
./gradlew checkstyleMain checkstyleTest
```

#### Step 4: Commit with Clear Messages
```bash
# Good commit message format:
# <JIRA-ID>: Brief description
#
# More detailed explanation of the change and rationale
# Lines describing the test strategy

git add <files>
git commit -m "KAFKA-12345: Fix XYZ issue

Detailed description of the change and why it's necessary.
This includes testing strategy and validation approach."
```

#### Step 5: Push and Create PR
```bash
# Push to your fork
git push origin KAFKA-12345-description

# Create PR on GitHub
# - Title: Match commit message first line
# - Body: Reference JIRA ticket (e.g., "Fixes KAFKA-12345")
# - Include testing strategy
# - Add reviewers (for major changes)
```

### Code Review Expectations

#### PR Requirements
1. **Title**: Should be clear and concise, optionally include JIRA ID
2. **Description**:
   - Reference the JIRA ticket: "Fixes KAFKA-12345"
   - Explain what changed and why
   - Describe testing strategy

3. **Testing**:
   - Unit tests for new code and bug fixes
   - Integration tests for feature changes
   - System tests for major changes (optional but appreciated)
   - Must include testing rationale in PR description

4. **Code Quality**:
   - Passes checkstyle: `./gradlew checkstyleMain checkstyleTest`
   - Passes spotbugs: `./gradlew spotbugsMain -x test`
   - Proper imports: `./gradlew spotlessApply`
   - License headers on new files

5. **Documentation**:
   - Update relevant documentation in `/docs/`
   - Include upgrade notes if breaking changes
   - Javadoc for public APIs

#### Review Process
1. **Automated Checks**:
   - Jenkins CI pipeline runs all checks
   - GitHub Actions runs Docker and security scans
   - Must pass before merging

2. **Community Review**:
   - Project members review for functionality and correctness
   - May request changes or clarifications
   - Iterate until approved

3. **Approval and Merge**:
   - At least one approval from a committer (usually lead of that component)
   - Committers have merge permission
   - PR is typically squashed into a single commit before merging

### Committer Checklist (for reviewers)
From `PULL_REQUEST_TEMPLATE.md`:
- [ ] Verify design and implementation
- [ ] Verify test coverage and CI build status
- [ ] Verify documentation (including upgrade notes)

### Code Style Guidelines
- **Language**: Mix of Java and Scala (prefer Java for new code)
- **Formatting**: Enforced by Checkstyle and Spotless
- **Import Order**: Must follow Kafka's conventions (enforced by Spotless)
- **Javadoc**: Required for public APIs and complex logic
- **Test Coverage**: Expected for all behavior changes

---

## 6. Developer Workflow Example

This example shows a complete workflow for fixing a bug reported in JIRA.

### Scenario
You want to fix KAFKA-99999: "Fix NPE in ProducerBatch.tryAppend() when batch is null"

### Step 1: Prepare Environment (5 minutes)

```bash
# Ensure you have latest Kafka source
cd ~/workspace/kafka
git fetch upstream
git checkout main
git reset --hard upstream/main

# Verify build works
./gradlew clean jar -q
echo "Build successful!"
```

### Step 2: Find and Review the Code (10-15 minutes)

```bash
# Locate the affected file
find . -name "*.java" -o -name "*.scala" | xargs grep -l "ProducerBatch" | grep -v test | head -5

# Open and review: core/src/main/scala/kafka/producer/ProducerBatch.scala
# Identify the issue around tryAppend() method

# Also look at existing tests
find . -path "*test*" -name "*ProducerBatch*"
```

### Step 3: Create Feature Branch (2 minutes)

```bash
# Create branch from JIRA ID
git checkout -b KAFKA-99999-fix-NPE-in-producer-batch
```

### Step 4: Write Test First (Optional but recommended)

```bash
# Find and open the test file
# Add a test case that reproduces the issue
# Example: test trying to append to a null batch
```

### Step 5: Implement the Fix (15-30 minutes)

```bash
# Edit the source file to add null check
# Example: add guard clause before accessing batch.property

# The fix might look like:
# if (batch == null) {
#   log.error("Batch is null in tryAppend()");
#   return false;
# }
```

### Step 6: Run Local Tests (15-30 minutes)

```bash
# Run tests for the affected module
./gradlew core:unitTest --tests ProducerBatchTest

# Run all unit tests to ensure no regressions
./gradlew unitTest -PmaxParallelForks=4

# Run integration tests (optional, more time-consuming)
./gradlew integrationTest -PmaxParallelForks=2
```

### Step 7: Code Quality Checks (5-10 minutes)

```bash
# Fix import order
./gradlew spotlessApply

# Check style compliance
./gradlew checkstyleMain checkstyleTest

# Run static analysis
./gradlew spotbugsMain -x test

# Run full check (should pass)
./gradlew clean check -x test
```

### Step 8: Commit Changes (2 minutes)

```bash
# Stage your changes
git add core/src/main/scala/kafka/producer/ProducerBatch.scala
git add core/src/test/scala/kafka/producer/ProducerBatchTest.scala

# Commit with clear message
git commit -m "KAFKA-99999: Fix NPE in ProducerBatch.tryAppend() when batch is null

Added null check before accessing batch properties in tryAppend() method.
This prevents a NullPointerException when the batch reference is null.

Testing: Added unit test to verify null batch is handled correctly.
The test reproduces the original issue and validates the fix."
```

### Step 9: Push and Create PR (5 minutes)

```bash
# Push to your fork
git push origin KAFKA-99999-fix-NPE-in-producer-batch

# Go to https://github.com/apache/kafka
# Click "Compare & pull request" button
# Or manually create PR from your fork to upstream
```

### Step 10: PR Description (Template)

```
## Summary
This PR fixes KAFKA-99999, which caused a NullPointerException in ProducerBatch.tryAppend()
when the batch reference was null during concurrent producer operations.

## Changes
- Added null check guard in ProducerBatch.tryAppend()
- Logs error and returns false if batch is null
- Includes unit test verifying the fix

## Testing Strategy
1. Unit test: ProducerBatchTest.testTryAppendWithNullBatch() - tests null handling
2. Existing tests: All existing ProducerBatch tests pass
3. Integration tests: Confirmed with concurrent producer scenarios

## Verification
- [x] All unit tests pass: `./gradlew core:unitTest`
- [x] Code style checks pass: `./gradlew checkstyleMain`
- [x] No spotbugs warnings: `./gradlew spotbugsMain -x test`
- [x] CI pipeline passes
```

### Step 11: Respond to Review (Variable)

```bash
# Reviewer may request changes, e.g., "Make error logging more descriptive"

# Make the requested change
git add core/src/main/scala/kafka/producer/ProducerBatch.scala

# Create new commit (don't amend - let reviewers see iteration)
git commit -m "KAFKA-99999: Address review feedback - improve error logging"

# Push update
git push origin KAFKA-99999-fix-NPE-in-producer-batch

# Comment on PR explaining the change
```

### Step 12: Merge (After Approval)

```bash
# Committer merges the PR
# GitHub typically squashes commits before merging:
# "KAFKA-99999: Fix NPE in ProducerBatch.tryAppend() when batch is null"

# The commit includes all your changes as a single squashed commit
```

### Step 13: Cleanup (1 minute)

```bash
# Delete local branch after merge
git checkout main
git branch -d KAFKA-99999-fix-NPE-in-producer-batch

# Sync local main with upstream
git fetch upstream
git reset --hard upstream/main
```

---

## Summary Checklist

### Before Starting Work
- [ ] Set up Java 11 or 17, Git, and Gradle wrapper
- [ ] Clone the Kafka repository
- [ ] Run `./gradlew jar` to verify the build works
- [ ] Find JIRA ticket and claim it

### Development
- [ ] Create feature branch from main
- [ ] Write tests for your changes
- [ ] Implement the fix/feature
- [ ] Verify all tests pass locally: `./gradlew test`
- [ ] Run code quality checks: `./gradlew spotlessApply && ./gradlew checkstyleMain`
- [ ] Commit with clear message referencing JIRA ID

### Before Submitting PR
- [ ] Ensure all tests pass: `./gradlew test`
- [ ] Run full CI simulation: `./gradlew clean check -x test`
- [ ] Verify no unintended changes in git diff
- [ ] Write clear PR description with testing strategy

### After PR Creation
- [ ] Monitor CI pipeline for failures
- [ ] Respond promptly to reviewer feedback
- [ ] Make requested changes in new commits (don't amend)
- [ ] Verify CI passes after updates

### Resources
- **JIRA**: https://issues.apache.org/jira/browse/KAFKA
- **Contributing Guide**: https://kafka.apache.org/contributing.html
- **Code Changes Guide**: https://cwiki.apache.org/confluence/display/KAFKA/Contributing+Code+Changes
- **Mailing List**: dev@kafka.apache.org
- **GitHub**: https://github.com/apache/kafka

