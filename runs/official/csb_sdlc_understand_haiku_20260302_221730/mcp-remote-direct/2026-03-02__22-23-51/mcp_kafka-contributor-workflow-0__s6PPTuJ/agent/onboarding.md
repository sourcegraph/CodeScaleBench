# Apache Kafka Contributor Guide

## Overview

This guide provides step-by-step instructions for contributing to Apache Kafka. It covers the build system, testing, CI/CD pipeline, code review process, and a complete contributor workflow example.

---

## 1. Build Prerequisites

### Java Requirements

Apache Kafka is built and tested with **Java 8, 11, 17, and 21**. The project sets the `release` parameter in javac and scalac to `8` to ensure backward compatibility with Java 8.

- **Recommended**: Java 11, 17, or 21 (Java 8 support is deprecated and planned for removal in Kafka 4.0)
- **Note**: Java 21 has known issues with some code quality tools; use Java 11 or 17 for code quality checks

### Scala Requirements

Apache Kafka supports **Scala 2.12 and 2.13**.

- **Default**: Scala 2.13
- **Note**: Scala 2.12 support is deprecated and will be removed in Kafka 4.0

### System Dependencies

- **Git** (for cloning and managing the repository)
- **Gradle** (included via `./gradlew` wrapper; Gradle 7.0+)
- **Maven** (required for Kafka Streams archetype testing)
- **Python 3** (for system integration tests using ducktape)
- **Docker** (for running system tests locally; version 1.12.3+)
- **Vagrant** (for local Kafka cluster testing; version 1.6.4+)

### Installation Verification

```bash
# Verify Java installation
java -version

# Verify Git installation
git --version

# Verify Gradle (using the wrapper in the Kafka repo)
./gradlew --version
```

---

## 2. Gradle Build System

### Key Gradle Files

- **`build.gradle`** — Root build configuration with plugins, dependencies, and common tasks
- **`settings.gradle`** — Defines all subprojects (modules) included in the build
- **`gradle.properties`** — Project metadata (version, Scala version, JVM arguments)
- **`gradle/` directory** — Additional gradle scripts and dependencies configuration

### Module Structure

Kafka is organized into multiple modules, defined in `settings.gradle`:

**Core Modules:**
- `core` — Kafka broker and server
- `clients` — Java client libraries (producers, consumers)
- `streams` — Kafka Streams (with submodules for examples, test utils, upgrade tests)
- `connect` — Kafka Connect framework and connectors

**Other Modules:**
- `server-common` — Shared server utilities
- `group-coordinator` — Group coordination logic
- `transaction-coordinator` — Transaction coordination
- `raft` — Kraft mode implementation
- `storage` — Log storage layer
- `tools` — Admin tools and CLI utilities
- `metadata` — Metadata management
- `log4j-appender` — Logging integration
- `jmh-benchmarks` — Microbenchmarks
- `examples` — Example code and applications

### Key Gradle Tasks

#### Building

```bash
# Build all JAR files
./gradlew jar

# Build a specific module
./gradlew core:jar
./gradlew clients:jar

# Build source JAR
./gradlew srcJar

# Build release tarball
./gradlew clean releaseTarGz
# Result: ./core/build/distributions/

# Build with all Scala versions
./gradlewAll jar
```

#### Documentation

```bash
# Build aggregated Javadoc
./gradlew aggregatedJavadoc

# Build Javadoc for all modules
./gradlew javadoc
./gradlew javadocJar

# Build Scaladoc
./gradlew scaladoc
./gradlew scaladocJar

# Build both
./gradlew docsJar
```

#### Testing

See "Running Tests" section below.

#### Code Quality

```bash
# Run checkstyle (code style validation)
./gradlew checkstyleMain checkstyleTest spotlessCheck

# Apply spotless formatting (fix import order)
# Note: Requires JDK 11 or 17, not Java 21
./gradlew spotlessApply

# Run SpotBugs (static bug detection)
./gradlew spotbugsMain spotbugsTest -x test

# Run all checks (without tests)
./gradlew check -x test
```

#### IDE Integration

```bash
# Generate Eclipse project files
./gradlew eclipse

# Generate IntelliJ IDEA project files
./gradlew idea
```

#### Dependency Analysis

```bash
# List all dependencies
./gradlew allDeps

# Find specific dependency versions
./gradlew allDepInsight --configuration runtimeClasspath --dependency com.fasterxml.jackson.core:jackson-databind

# Check for outdated dependencies
./gradlew dependencyUpdates
```

#### Cleaning

```bash
# Clean all build artifacts
./gradlew clean
```

### Common Build Options

Build options are passed with the `-P` flag:

```bash
# Example: Run tests in parallel with custom options
./gradlew test \
  -PmaxParallelForks=4 \
  -PmaxTestRetries=2 \
  -PmaxTestRetryFailures=10 \
  -PscalaVersion=2.13

# Build with a specific Scala version
./gradlew -PscalaVersion=2.12 jar

# Build with custom Java compilation release level
./gradlew -PscalaVersion=2.13 test
```

**Common Options:**
- `-PscalaVersion=2.12` or `-PscalaVersion=2.13` — Choose Scala version
- `-PmaxParallelForks=N` — Limit parallel test processes (default: number of processors)
- `-PmaxScalacThreads=N` — Max threads for Scala compiler (default: min of 8 and processors)
- `-PignoreFailures=true` — Continue build despite test failures
- `-PshowStandardStreams=true` — Show test stdout/stderr on console
- `-PskipSigning=true` — Skip artifact signing
- `-PtestLoggingEvents=started,passed,skipped,failed` — Control test logging output
- `-PmaxTestRetries=N` — Max retries per failed test (default: 0)
- `-PmaxTestRetryFailures=N` — Max cumulative retry failures before stopping retries (default: 0)
- `-PenableTestCoverage=true` — Enable coverage reports (adds 15-20% overhead)

### Build with All Scala Versions

```bash
# Use gradlewAll to build and test with all supported Scala versions
./gradlewAll jar
./gradlewAll test
./gradlewAll releaseTarGz
```

---

## 3. Running Tests

### Test Types

Kafka has three types of automated tests:

1. **Unit Tests** — Fast, isolated tests of individual components
2. **Integration Tests** — Slower tests that exercise multiple components together
3. **System Tests** — Full end-to-end tests using Python ducktape framework

### Unit and Integration Tests (Gradle-based)

#### Run All Tests

```bash
# Run all unit and integration tests
./gradlew test

# Run only unit tests
./gradlew unitTest

# Run only integration tests
./gradlew integrationTest
```

#### Run Tests for a Specific Module

```bash
# Test only the clients module
./gradlew clients:test

# Test only the streams module (including all sub-tests)
./gradlew :streams:testAll

# Test core with unit tests only
./gradlew core:unitTest
```

#### Run a Specific Test Class

```bash
# Run a single test class
./gradlew clients:test --tests RequestResponseTest

# Run tests from core module
./gradlew core:test --tests kafka.api.ProducerFailureHandlingTest

# Run with full package name (Java tests)
./gradlew clients:test --tests org.apache.kafka.clients.MetadataTest
```

#### Run a Specific Test Method

```bash
# Run a specific test method
./gradlew core:test --tests kafka.api.ProducerFailureHandlingTest.testCannotSendToInternalTopic

./gradlew clients:test --tests org.apache.kafka.clients.MetadataTest.testTimeToNextUpdate
```

#### Force Re-run Without Code Changes

```bash
# Re-run all tests
./gradlew test --rerun

# Re-run unit tests
./gradlew unitTest --rerun

# Re-run a specific test
./gradlew clients:test --tests RequestResponseTest --rerun
```

#### Repeatedly Run a Test (Debugging Flakes)

```bash
# Loop until test fails (useful for debugging flaky tests)
I=0; while ./gradlew clients:test --tests RequestResponseTest --rerun --fail-fast; do (( I=$I+1 )); echo "Completed run: $I"; sleep 1; done
```

#### Configure Test Logging

Edit `src/test/resources/log4j.properties` in the relevant module to adjust logging:

```properties
# In clients/src/test/resources/log4j.properties
log4j.logger.org.apache.kafka=INFO  # Show INFO level logs for all Kafka components
```

Then run tests:

```bash
./gradlew cleanTest clients:test --tests NetworkClientTest
# Logs appear in: clients/build/test-results/test/
```

#### Test Retries and Flakiness Handling

By default, each failed test is retried once, with a maximum of 5 retries per test run:

```bash
# Customize retry behavior
./gradlew test -PmaxTestRetries=3 -PmaxTestRetryFailures=10
```

#### Test Coverage Reports

Generate code coverage reports (Note: adds 15-20% overhead):

```bash
# Coverage for entire project
./gradlew reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false

# Coverage for a single module
./gradlew clients:reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false
```

### System Integration Tests (Python-based)

System tests use the **ducktape** framework. Build Kafka first:

```bash
./gradlew clean systemTestLibs
```

#### Run System Tests Locally with Docker

**Requirements:** Docker 1.12.3+

```bash
# Run all system tests
bash tests/docker/run_tests.sh

# Run tests with debug output
_DUCKTAPE_OPTIONS="--debug" bash tests/docker/run_tests.sh | tee debug_logs.txt

# Run a subset of tests by directory
TC_PATHS="tests/kafkatest/tests/streams tests/kafkatest/tests/tools" bash tests/docker/run_tests.sh

# Run a specific test file
TC_PATHS="tests/kafkatest/tests/client/pluggable_test.py" bash tests/docker/run_tests.sh

# Run a specific test class
TC_PATHS="tests/kafkatest/tests/client/pluggable_test.py::PluggableConsumerTest" bash tests/docker/run_tests.sh

# Run a specific test method
TC_PATHS="tests/kafkatest/tests/client/pluggable_test.py::PluggableConsumerTest.test_start_stop" bash tests/docker/run_tests.sh

# Run with Kafka in native mode
_DUCKTAPE_OPTIONS="--globals '{\"kafka_mode\":\"native\"}'" TC_PATHS="tests/kafkatest/tests/" bash tests/docker/run_tests.sh

# Remove Docker containers after testing
bash tests/docker/ducker-ak down -f
```

#### Run System Tests Locally with Vagrant

**Requirements:** VirtualBox, Vagrant 1.6.4+, Python 3 virtualenv

```bash
# Setup environment
cd kafka/tests
virtualenv -p python3 venv
. ./venv/bin/activate
python3 setup.py develop
cd ..

# Bootstrap Vagrant
tests/bootstrap-test-env.sh

# Bring up cluster
vagrant/vagrant-up.sh

# Build Kafka
./gradlew systemTestLibs

# Run all tests
ducktape tests/kafkatest/tests
```

#### System Test Unit Tests

The Python test framework has unit tests:

```bash
cd tests
python3 setup.py test
```

Unit tests follow the naming convention: module name starts with "check", class begins with "Check", method name starts with "check".

---

## 4. CI Pipeline

### Jenkins CI

Apache Kafka uses **Jenkins** as the primary CI system. The pipeline is defined in the `Jenkinsfile` at the repository root.

#### Jenkins Pipeline Overview

The Jenkins pipeline runs in **parallel stages** for each Java/Scala version combination:

1. **JDK 8 + Scala 2.12** (8-hour timeout)
   - Runs: validation, all tests, Kafka Streams archetype test

2. **JDK 11 + Scala 2.13** (8-hour timeout)
   - Runs: validation, tests (only on dev branch)

3. **JDK 17 + Scala 2.13** (8-hour timeout)
   - Runs: validation, tests (only on dev branch)

4. **JDK 21 + Scala 2.13** (8-hour timeout)
   - Runs: validation, all tests

#### Pipeline Stages

1. **Validation** (`doValidation()`)
   ```bash
   ./retry_zinc ./gradlew -PscalaVersion=$SCALA_VERSION clean check -x test \
       --profile --continue -PxmlSpotBugsReport=true -PkeepAliveMode="session"
   ```
   Runs code quality checks: checkstyle, spotbugs, spotless

2. **Testing** (`doTest()`)
   ```bash
   ./gradlew -PscalaVersion=$SCALA_VERSION test \
       --profile --continue -PkeepAliveMode="session" -PtestLoggingEvents=started,passed,skipped,failed \
       -PignoreFailures=true -PmaxParallelForks=2 -PmaxTestRetries=1 -PmaxTestRetryFailures=10
   ```

3. **Kafka Streams Archetype** (`doStreamsArchetype()`)
   - Publishes libraries to Maven local
   - Generates a project using the Streams archetype
   - Compiles the generated project

#### Jenkins Configuration

- **Location**: `Jenkinsfile` at repository root
- **Agents**: Ubuntu label
- **Tools**: JDK versions configured per stage
- **Timeouts**: 8 hours per stage
- **Notifications**: Sent to `dev@kafka.apache.org` on failures (non-PR builds only)
- **Build Scans**: Uploaded to https://ge.apache.org (Apache's Gradle Enterprise server)

#### Jenkins PR Whitelisting

Users who can trigger Jenkins builds on pull requests are configured in `.asf.yaml`:

```yaml
jenkins:
  github_whitelist:
    - FrankYang0529
    - kamalcph
    - apoorvmittal10
    - lianetm
    - brandboat
    - kirktrue
    - nizhikov
    - OmniaGM
    - dongnuo123
    - frankvicky
```

### GitHub Actions CI

Apache Kafka also uses **GitHub Actions** for specialized testing:

#### Docker Build and Test Workflow

- **File**: `.github/workflows/docker_build_and_test.yml`
- **Trigger**: Manual workflow dispatch
- **Inputs**:
  - Image type: `jvm` or `native`
  - Kafka URL: URL to use for building Docker image
- **Steps**:
  1. Build Docker image from specified Kafka URL
  2. Run tests within the image
  3. Run CVE scanning (Trivy) on the image
  4. Upload test and scan reports as artifacts

#### Other GitHub Actions Workflows

- `.github/workflows/docker_official_image_build_and_test.yml` — Official Docker image builds
- `.github/workflows/docker_promote.yml` — Docker image promotion
- `.github/workflows/docker_rc_release.yml` — Release candidate Docker builds
- `.github/workflows/docker_scan.yml` — Security scanning
- `.github/workflows/stale.yml` — Stale issue management

### Build Caching and Gradle Enterprise

Kafka uses **Gradle Enterprise** at https://ge.apache.org for:

- Build scans (performance analysis, task insights)
- Build cache (CI only; disabled locally)
- Distributed builds

Configuration in `settings.gradle`:

```groovy
gradleEnterprise {
    server = "https://ge.apache.org"
    buildScan {
        capture { taskInputFiles = true }
        uploadInBackground = !isCI
        publishAlways()
        publishIfAuthenticated()
        obfuscation {
            ipAddresses { addresses -> addresses.collect { address -> "0.0.0.0"} }
        }
    }
}
```

---

## 5. Code Review Process

### Overview

Apache Kafka follows the **Apache Software Foundation (ASF)** contribution process using GitHub Pull Requests, JIRA for issue tracking, and email-based code review on the dev mailing list.

### Finding Issues to Work On

**JIRA Issue Tracker**: https://issues.apache.org/jira/browse/KAFKA

The Apache Kafka project tracks all work in JIRA. Contributors can:

1. Browse open issues: Filter by status (Open, In Progress, Ready for Review)
2. Look for issues labeled `starter` or `help-wanted`
3. Check the project roadmap for prioritized items
4. Comment on an issue to claim it (e.g., "I'd like to work on this")

**Issue Types**:
- Bug — Problems in existing code
- Improvement — Enhancements to existing features
- New Feature — New functionality
- Task — Administrative work

### Creating a Pull Request

#### Prerequisites

1. **Fork the Repository**: Go to https://github.com/apache/kafka and click "Fork"

2. **Clone Your Fork**:
   ```bash
   git clone https://github.com/YOUR_USERNAME/kafka.git
   cd kafka
   ```

3. **Add Upstream Remote**:
   ```bash
   git remote add upstream https://github.com/apache/kafka.git
   git fetch upstream
   ```

4. **Create a Feature Branch**:
   ```bash
   git checkout -b KAFKA-XXXXX upstream/main
   ```
   (Use the JIRA issue number in the branch name for clarity)

5. **Make Your Changes**
   - Edit code
   - Add/update tests
   - Add/update documentation
   - Run local tests to verify

6. **Commit Your Changes**:
   ```bash
   git commit -m "KAFKA-XXXXX: Brief summary of changes

   Detailed description of what was changed and why."
   ```

7. **Push to Your Fork**:
   ```bash
   git push origin KAFKA-XXXXX
   ```

8. **Create a Pull Request**
   - Go to your fork on GitHub
   - Click "Compare & pull request"
   - Use the PR template (auto-populated in `PULL_REQUEST_TEMPLATE.md`)

#### Pull Request Template

The PR template includes:

```markdown
*More detailed description of your change,
if necessary. The PR title and PR message become
the squashed commit message, so use a separate
comment to ping reviewers.*

*Summary of testing strategy (including rationale)
for the feature or bug fix. Unit and/or integration
tests are expected for any behaviour change and
system tests should be considered for larger changes.*

### Committer Checklist (excluded from commit message)
- [ ] Verify design and implementation
- [ ] Verify test coverage and CI build status
- [ ] Verify documentation (including upgrade notes)
```

### Code Review Expectations

#### What Reviewers Check

1. **Design and Implementation** — Does the solution make sense? Is it aligned with the project's architecture?
2. **Code Quality** — Does the code pass checkstyle, spotbugs, and spotless checks?
3. **Testing** — Are there adequate unit, integration, or system tests? Does the CI pipeline pass?
4. **Documentation** — Are JavaDoc, configuration docs, and upgrade notes updated?
5. **Backward Compatibility** — Are there any breaking changes? Are they justified?

#### Code Quality Requirements

Before submitting a PR, ensure:

```bash
# Run code quality checks
./gradlew spotlessApply   # Fix import order (JDK 11/17 only)
./gradlew checkstyleMain checkstyleTest  # Check code style
./gradlew spotbugsMain spotbugsTest -x test  # Check for bugs

# Run tests
./gradlew test

# Check the full pipeline locally
./gradlew clean check  # All checks except tests
./gradlew test         # Tests
```

#### Approval Process

1. **Community Review** — Kafka contributors provide feedback on your PR
2. **Automated Checks** — Jenkins CI runs the full test suite on multiple JDK/Scala versions
3. **Approval** — A committer approves the PR if everything looks good
4. **Merge** — A committer squashes and merges your PR to the main branch

Note: Only Apache Kafka committers can merge PRs. GitHub PR checks are enabled but final approval comes from the code review comments.

### Notifications and Linking

- **Issue Links**: PRs are automatically linked to JIRA issues when you mention them: "Fixes KAFKA-12345"
- **Notifications**:
  - Commits go to `commits@kafka.apache.org`
  - JIRA updates go to `jira@kafka.apache.org`
  - PR notifications go to `jira@kafka.apache.org`

### Apache License and CLA

By contributing to Apache Kafka, you affirm that:

1. The contribution is your original work
2. You license it under the Apache License 2.0
3. You have the legal authority to grant this license

No separate CLA signature is required; submitting a pull request constitutes agreement to these terms.

---

## 6. Developer Workflow Example

### Scenario: Fix a Bug in the Producer Client

Let's walk through a complete contributor workflow for fixing a bug in the Kafka producer.

#### Step 1: Find and Claim an Issue

1. Go to https://issues.apache.org/jira/browse/KAFKA
2. Search for bugs or improvements related to producer
3. Example: Find "KAFKA-16226: Producer send() and background thread synchronization issue"
4. Click on the issue and comment: "I'd like to work on this"

#### Step 2: Set Up Your Development Environment

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/kafka.git
cd kafka

# Add upstream reference
git remote add upstream https://github.com/apache/kafka.git
git fetch upstream

# Create a feature branch
git checkout -b KAFKA-16226 upstream/main

# Verify the build works
./gradlew clean jar
```

#### Step 3: Understand the Code

```bash
# Find files related to the issue
grep -r "RecordAccumulator" clients/src/main/java/

# Read the main file mentioned in the issue
cat clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java

# Look at existing tests
./gradlew clients:test --tests ProducerTest --dry-run
```

#### Step 4: Write a Failing Test (TDD Approach)

```bash
# Create a test file to reproduce the issue
# File: clients/src/test/java/org/apache/kafka/clients/producer/internals/ProducerSyncTest.java

cat > /tmp/ProducerSyncTest.java << 'EOF'
package org.apache.kafka.clients.producer.internals;

import org.junit.Test;
import static org.junit.Assert.*;

public class ProducerSyncTest {
    @Test
    public void testProducerSendAndBackgroundThreadSync() {
        // Test that verifies reduced synchronization between send() and background thread
        // This test should initially fail
        RecordAccumulator accumulator = new RecordAccumulator(...);
        // Assert expected behavior
    }
}
EOF

# Run the test (it should fail initially)
./gradlew clients:test --tests ProducerSyncTest
```

#### Step 5: Implement the Fix

Edit the source files:

```bash
# Edit the main source file
nano clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java

# Example change: Reduce synchronization in updateNodeLatencyStats()
# See line 988-991 in the actual file
```

Make targeted changes to fix the specific issue.

#### Step 6: Verify the Fix with Tests

```bash
# Run the specific test you wrote
./gradlew clients:test --tests ProducerSyncTest

# Run all producer-related tests
./gradlew clients:test --tests ProducerTest

# Run all client tests to ensure no regression
./gradlew clients:test

# If you need to repeatedly run a flaky test to verify it's fixed:
I=0; while ./gradlew clients:test --tests ProducerSyncTest --rerun; do (( I=$I+1 )); echo "Run: $I passed"; sleep 1; done
```

#### Step 7: Run Code Quality Checks

```bash
# Fix import order
./gradlew spotlessApply

# Check code style
./gradlew checkstyleMain checkstyleTest

# Check for bugs
./gradlew spotbugsMain spotbugsTest -x test

# Run full validation pipeline
./gradlew check -x test
```

Fix any issues reported by the quality tools.

#### Step 8: Run the Full Test Suite Locally

```bash
# Test your module thoroughly
./gradlew clients:test

# Optionally, test core module if your changes touch shared code
./gradlew core:test

# Test with multiple Scala versions if needed
./gradlew -PscalaVersion=2.12 clients:test
./gradlew -PscalaVersion=2.13 clients:test
```

#### Step 9: Commit Your Changes

```bash
# Stage your changes
git add clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java
git add clients/src/test/java/org/apache/kafka/clients/producer/internals/ProducerSyncTest.java

# Commit with a clear message
git commit -m "KAFKA-16226: Reduce synchronization in RecordAccumulator.updateNodeLatencyStats()

The method was unnecessarily synchronizing between the application thread
calling send() and the background thread running runOnce(). This change
avoids the sync point for the common case where the feature is disabled.

Testing:
- Added ProducerSyncTest to verify synchronized behavior
- All existing producer tests pass
- Verified with JDK 8, 11, 17, and 21"

# Verify your commit message is clear
git log -1
```

#### Step 10: Push to Your Fork

```bash
# Push your branch to your GitHub fork
git push origin KAFKA-16226

# Verify it's there
git remote -v
```

#### Step 11: Create a Pull Request

1. Go to your fork: https://github.com/YOUR_USERNAME/kafka
2. GitHub will prompt: "Compare & pull request" for your recent branch
3. Click the button to start creating a PR
4. Fill in the PR template:

```markdown
**Description:**
This PR fixes KAFKA-16226 by reducing unnecessary synchronization between
the application thread (calling send()) and the background thread
(running runOnce()) in RecordAccumulator.updateNodeLatencyStats().

The method now avoids the sync point in the common case where the
availability timeout feature is disabled, improving throughput for
most users.

**Testing:**
- Added ProducerSyncTest.testProducerSendAndBackgroundThreadSync()
- All existing producer tests pass
- Verified with JDK 8, 11, 17, and 21
- Verified with Scala 2.12 and 2.13

**Checklist:**
- [x] Code style checks pass (spotless, checkstyle)
- [x] New tests added for the change
- [x] All existing tests pass
- [x] No breaking changes
```

5. Click "Create pull request"

#### Step 12: Respond to Code Review

Once you create the PR:

1. **Jenkins CI runs automatically** — wait for test results
2. **Reviewers comment** — respond to questions and suggestions
3. **Make updates if needed** — push additional commits to the same branch
4. **Reviewers approve** — once satisfied

Example of responding to a review:

```bash
# If a reviewer requests changes
# 1. Make the changes
nano clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java

# 2. Commit and push
git add clients/src/...
git commit -m "Address review feedback: Add defensive null check in updateNodeLatencyStats()"
git push origin KAFKA-16226

# The PR is automatically updated
```

#### Step 13: Merge (Committer Only)

Once approved by a committer, they will squash and merge your PR:

```
# The committer runs something like (you don't do this):
# git commit --squash
# git push upstream main
```

Your PR is now merged! 🎉

#### Step 14: Update JIRA

After merge, a committer typically updates the JIRA issue:
- Status: Resolved
- Resolution: Fixed
- Fix Version: The next Kafka release version

#### Complete Example Diff

Here's what your changes might look like:

```diff
--- a/clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java
+++ b/clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java
@@ -985,10 +985,11 @@ public class RecordAccumulator {

     public void updateNodeLatencyStats(Integer nodeId, long nowMs, boolean canDrain) {
         // Don't bother with updating stats if the feature is turned off.
-        if (partitionAvailabilityTimeoutMs <= 0)
+        if (partitionAvailabilityTimeoutMs <= 0) {
             return;
-        synchronized (this) {
+        }
+        synchronized (this) {
             // Only update stats if we're tracking latency
             if (nodeId != null && nodeLatencyStats.containsKey(nodeId)) {
```

#### Helpful Commands During Development

```bash
# Check status of your changes
git status
git diff

# See commits you've made
git log --oneline -5

# Pull latest changes from main branch
git fetch upstream
git rebase upstream/main

# Force push after rebase (only if you're rebasing your own branch)
git push -f origin KAFKA-16226

# View your PR online
# Go to: https://github.com/apache/kafka/pulls
# Click your PR to see CI results and reviews

# Clean up after PR is merged
git checkout main
git pull upstream main
git branch -d KAFKA-16226
```

---

## Additional Resources

### Official Kafka Documentation

- **Contributing Guide**: https://kafka.apache.org/contributing.html
- **Contributing Code Changes**: https://cwiki.apache.org/confluence/display/KAFKA/Contributing+Code+Changes
- **Project Wiki**: https://cwiki.apache.org/confluence/display/KAFKA

### JIRA and Issue Tracking

- **KAFKA JIRA**: https://issues.apache.org/jira/browse/KAFKA
- **Issue Types**: New Feature, Improvement, Bug, Task
- **Assignee**: Comment on an issue to claim it

### Development Setup

- **Building**: See `README.md` "Build a jar and run it" section
- **System Tests**: See `tests/README.md` for full system testing guide
- **Performance Tests**: See `jmh-benchmarks/README.md` for JMH benchmarks
- **Vagrant Environment**: See `vagrant/README.md` for virtual cluster setup

### Community

- **Mailing Lists**: http://kafka.apache.org/contact.html
- **Slack**: Apache Kafka community Slack (check official website)
- **Dev List**: `dev@kafka.apache.org` (for technical discussion)

### Gradle and Build Tools

- **Gradle Documentation**: https://docs.gradle.org
- **Test Retry Plugin**: https://github.com/gradle/test-retry-gradle-plugin
- **Gradle Enterprise**: https://ge.apache.org (build scans)

---

## Tips for Success

1. **Start Small** — First contributions should be documentation, simple bugs, or small features
2. **Read the Code** — Spend time understanding the codebase before making large changes
3. **Test Thoroughly** — Kafka is critical infrastructure; thorough testing is essential
4. **Engage Early** — Comment on JIRA issues and discuss your approach before implementing
5. **Review Others' PRs** — Participate in code review to learn and help the community
6. **Follow the Style** — Use `spotlessApply` and `checkstyle` to match the project's style
7. **Document Changes** — Update JavaDoc, configuration docs, and upgrade notes
8. **Be Patient** — Code review can take time; committers are volunteers

---

**Last Updated**: March 2024
**Kafka Version**: 3.9.0
