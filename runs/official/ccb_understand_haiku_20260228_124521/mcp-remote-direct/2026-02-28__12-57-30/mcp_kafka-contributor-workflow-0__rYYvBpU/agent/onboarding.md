# Kafka Contributor Guide

A comprehensive guide to building, testing, and contributing to Apache Kafka. This document covers the developer workflow, build system, testing infrastructure, and code review process.

## 1. Build Prerequisites

### Java Version Requirements
Kafka is built and tested with **Java 8, 11, 17, and 21**.

Key points:
- **Minimum Java version**: Java 8
- **Release parameter**: Set to `8` to ensure binaries are compatible with Java 8 or higher
- **Deprecation notes**:
  - Java 8 support has been deprecated since Kafka 3.0 (removal planned for 4.0)
  - Java 11 support for broker and tools has been deprecated since Kafka 3.7 (removal planned for 4.0)
  - See [KIP-750](https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=181308223) and [KIP-1013](https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=284789510) for details

### Scala Support
- **Default version**: Scala 2.13.14
- **Supported versions**: Scala 2.12 and 2.13
- **Deprecation**: Scala 2.12 support has been deprecated since Kafka 3.0 (removal planned for 4.0)
- See [KIP-751](https://cwiki.apache.org/confluence/pages/viewpage.action?pageId=181308218) for details

### System Dependencies
- **Git**: For cloning the repository and version control
- **Gradle**: Build system (Gradle wrapper included in repo)
- **Maven**: Required for Kafka Streams quickstart archetype builds (version 3.x)

### Optional Tools
- **IDE Support**: IntelliJ IDEA, Eclipse (IDE projects can be generated with Gradle)
- **JMH**: For running microbenchmarks (included in `jmh-benchmarks/` module)

---

## 2. Gradle Build System

### Overview
Kafka uses **Gradle** as its primary build system. The project is organized as a multi-module Gradle project with approximately 40+ submodules.

### Key Modules
The main modules are defined in `settings.gradle`:
- `clients` - Java client libraries
- `core` - Kafka broker implementation
- `connect` - Kafka Connect framework and connectors
- `streams` - Kafka Streams library (with sub-modules for examples, scala, utils)
- `server`, `server-common` - Server-side code
- `storage` - Tiered storage implementation
- `tools` - Kafka command-line tools
- `log4j-appender` - Log4j integration
- `examples` - Example code

### Important Files
- `build.gradle` - Root build configuration
- `gradle.properties` - Project properties (version, Scala version, JVM args)
- `settings.gradle` - Module definitions and Gradle Enterprise configuration
- `gradle/dependencies.gradle` - Dependency versions

### Building the Project

#### Full Build
```bash
./gradlew jar
```

#### Build Specific Module
```bash
./gradlew core:jar
./gradlew clients:jar
./gradlew streams:testAll
```

#### Source JAR
```bash
./gradlew srcJar
```

#### Documentation
```bash
./gradlew aggregatedJavadoc    # Aggregated javadoc
./gradlew javadoc              # Javadoc and scaladoc
./gradlew javadocJar           # Javadoc jar for each module
./gradlew scaladoc             # Scala documentation
./gradlew scaladocJar          # Scaladoc jar for each module
./gradlew docsJar              # Both javadoc and scaladoc jars
```

#### Building with Different Scala Versions
```bash
# Use Scala 2.12 for a specific task
./gradlew -PscalaVersion=2.12 jar

# Build with all supported Scala versions
./gradlewAll jar
./gradlewAll test
./gradlewAll releaseTarGz
```

#### Release Artifacts
```bash
./gradlew clean releaseTarGz   # Creates gzipped tarball in core/build/distributions/
```

#### Rebuild Generated Messages
When switching branches, RPC messages may need to be regenerated:
```bash
./gradlew processMessages processTestMessages
```

### Gradle Properties and Options

Common properties (use with `-P` flag):
- `scalaVersion` - Scala version (2.12 or 2.13)
- `maxParallelForks` - Parallel test processes (default: number of processors)
- `maxScalacThreads` - Scala compiler threads (default: min(8, processors), range: 1-16)
- `ignoreFailures` - Ignore test failures (boolean)
- `showStandardStreams` - Show stdout/stderr in tests (boolean)
- `skipSigning` - Skip artifact signing (boolean)
- `testLoggingEvents` - Comma-separated test events to log (started, passed, skipped, failed)
- `xmlSpotBugsReport` - Enable XML reports for spotBugs (boolean)
- `maxTestRetries` - Max retries for failing tests (default: 0)
- `maxTestRetryFailures` - Max failures before disabling retries (default: 0)
- `enableTestCoverage` - Enable test coverage (boolean, adds 15-20% overhead)
- `keepAliveMode` - Gradle daemon keep-alive mode (daemon|session, default: daemon)
- `scalaOptimizerMode` - Scala compiler optimization (none|method|inline-kafka|inline-scala, default: inline-kafka)

Example:
```bash
./gradlew -PmaxParallelForks=4 -PskipSigning=true test
```

### Listing Available Tasks
```bash
./gradlew tasks
```

### Building IDE Projects
```bash
./gradlew eclipse
./gradlew idea
```

---

## 3. Running Tests

### Test Framework
Kafka uses **JUnit 5 (Jupiter)** as its primary test framework. Custom test extensions are available for running integration tests with Kafka clusters.

### Test Categories
- **Unit Tests**: Fast, no cluster setup required
- **Integration Tests**: Require cluster setup, tagged with `@Tag("integration")`
- **System Tests**: Complex multi-machine tests (see `tests/README.md`)

### Running All Tests
```bash
./gradlew test                    # Unit + integration tests
./gradlew unitTest                # Unit tests only
./gradlew integrationTest         # Integration tests only
```

### Running Tests for Specific Module
```bash
./gradlew clients:test            # All tests in clients module
./gradlew core:test               # All tests in core module
./gradlew streams:testAll         # All Streams tests
```

### Running Specific Test Class
```bash
./gradlew clients:test --tests RequestResponseTest
./gradlew clients:test --tests org.apache.kafka.clients.MetadataTest
```

### Running Specific Test Method
```bash
./gradlew core:test --tests kafka.api.ProducerFailureHandlingTest.testCannotSendToInternalTopic
./gradlew clients:test --tests org.apache.kafka.clients.MetadataTest.testTimeToNextUpdate
```

### Forcing Test Re-run Without Code Changes
```bash
./gradlew test --rerun
./gradlew unitTest --rerun
./gradlew integrationTest --rerun
```

### Repeatedly Running a Test (Useful for Flaky Tests)
```bash
I=0; while ./gradlew clients:test --tests RequestResponseTest --rerun --fail-fast; do (( I=$I+1 )); echo "Completed run: $I"; sleep 1; done
```

### Adjusting Test Logging
By default, limited logs are shown during tests. To increase verbosity:
1. Modify `log4j.properties` in the module's `src/test/resources` directory
2. Change log level from `WARN` to `INFO`:
   ```properties
   log4j.logger.org.apache.kafka=INFO
   ```
3. Run tests and check results in `{module}/build/test-results/test`

Example:
```bash
./gradlew cleanTest clients:test --tests NetworkClientTest
```

### Test Retries
By default: each failed test retries once up to 5 retries per test run. Adjust:
```bash
./gradlew test -PmaxTestRetries=1 -PmaxTestRetryFailures=5
```

See [Test Retry Gradle Plugin](https://github.com/gradle/test-retry-gradle-plugin) for more details.

### Test Coverage Reports
```bash
# Whole project
./gradlew reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false

# Single module
./gradlew clients:reportCoverage -PenableTestCoverage=true -Dorg.gradle.parallel=false
```

### Custom Cluster Test Annotations
For integration tests requiring a running Kafka cluster:
```java
@ExtendWith(value = Array(classOf[ClusterTestExtensions]))
class ApiVersionsRequestTest {
  @ClusterTest
  def testBasic(clusterInstance: ClusterInstance): Unit = {
    // Test code
  }
}
```

See `core/src/test/java/kafka/test/junit/README.md` for full documentation.

---

## 4. CI Pipeline

### CI Systems
Kafka uses **two CI systems**:

1. **Jenkins** (Primary for development/PR builds)
   - Defined in `Jenkinsfile` at repository root
   - Runs on multiple Java/Scala version combinations
   - Email notifications to `dev@kafka.apache.org` for failures

2. **GitHub Actions** (Docker and promotion workflows)
   - Located in `.github/workflows/`
   - Used for Docker image building, testing, and promotion
   - CVE scanning workflows

### Jenkinsfile Overview
The `Jenkinsfile` defines a multi-stage pipeline:

#### Build Stages (Parallel)
1. **JDK 8 and Scala 2.12**
   - Java: JDK 1.8 latest
   - Scala: 2.12
   - Timeout: 8 hours
   - Runs: validation, tests, Streams archetype test

2. **JDK 11 and Scala 2.13**
   - Java: JDK 11 latest
   - Scala: 2.13
   - Timeout: 8 hours
   - Runs: validation, tests (only on PRs)

3. **JDK 17 and Scala 2.13**
   - Java: JDK 17 latest
   - Scala: 2.13
   - Timeout: 8 hours
   - Runs: validation, tests (only on PRs)

4. **JDK 21 and Scala 2.13**
   - Java: JDK 21 latest
   - Scala: 2.13
   - Timeout: 8 hours
   - Runs: validation, tests

#### CI Checks Run on Every Build
1. **Validation** (code quality):
   ```bash
   ./retry_zinc ./gradlew -PscalaVersion=$SCALA_VERSION clean check -x test \
       --profile --continue -PxmlSpotBugsReport=true -PkeepAliveMode="session"
   ```
   - Checkstyle (coding standards)
   - Spotbugs (static analysis for bugs)
   - Spotless (code formatting)
   - Apache Rat (license headers)

2. **Unit and Integration Tests**:
   ```bash
   ./gradlew -PscalaVersion=$SCALA_VERSION test \
       --profile --continue -PkeepAliveMode="session" -PtestLoggingEvents=started,passed,skipped,failed \
       -PignoreFailures=true -PmaxParallelForks=2 -PmaxTestRetries=1 -PmaxTestRetryFailures=10
   ```

3. **Kafka Streams Archetype Test** (JDK 8 and JDK 21 only):
   - Tests that Streams quickstart archetype compiles and works
   - Uses Maven for archetype generation and compilation

#### GitHub Actions Workflows
Located in `.github/workflows/`:
- `docker_build_and_test.yml` - Build and test Docker images
- `docker_official_image_build_and_test.yml` - Official Docker image workflow
- `docker_promote.yml` - Promote RC Docker images to release
- `docker_rc_release.yml` - Release candidate Docker image creation
- `docker_scan.yml` - Nightly CVE scanning for Docker images
- `stale.yml` - Manage stale issues/PRs

### Pull Request Builds
- Only triggered on PRs (when `CHANGE_ID` environment variable is set)
- All four Java/Scala combinations run in parallel
- Test results reported back to GitHub
- Concurrent builds are aborted when new commits pushed

### CI Environment Variables
- `SCALA_VERSION` - Set for each build (2.12 or 2.13)
- `CHANGE_ID` - Set by Jenkins for pull requests

---

## 5. Code Review Process

### Before Creating a Pull Request

**Important**: Review the official contribution guidelines first:
- Apache Kafka Contributing Guide: https://kafka.apache.org/contributing.html
- Contributing Code Changes: https://cwiki.apache.org/confluence/display/KAFKA/Contributing+Code+Changes

### JIRA Ticket Workflow

1. **Browse Issues**:
   - Visit https://issues.apache.org/jira/browse/KAFKA
   - Look for unassigned issues with `newbie` label (good for first-time contributors)

2. **Claim a Ticket**:
   - Comment on the JIRA issue expressing interest
   - Coordinate with committers and other contributors
   - Fork the Apache Kafka repository

3. **Branch Naming**:
   - Not strictly enforced, but recommended: `KAFKA-XXXXX` (JIRA ticket number)
   - Example: `KAFKA-12345-bug-fix-description`

### Development Workflow

1. **Setup**:
   ```bash
   # Clone your fork
   git clone https://github.com/YOUR_USERNAME/kafka.git
   cd kafka

   # Add upstream remote
   git remote add upstream https://github.com/apache/kafka.git

   # Create feature branch
   git checkout -b KAFKA-12345-description
   ```

2. **Code Changes**:
   - Write code following Kafka's style guidelines
   - Add/modify tests as appropriate
   - Run code quality checks

3. **Code Quality Checks**:
   ```bash
   # Checkstyle (enforces consistent coding style)
   ./gradlew checkstyleMain checkstyleTest spotlessCheck

   # Spotbugs (static bug analysis)
   ./gradlew spotbugsMain spotbugsTest -x test

   # Spotless (auto-format imports)
   ./gradlew spotlessApply

   # Note: Use JDK 11 or 17 for spotlessCheck and spotlessApply
   # (Java 21 currently has issues - see README.md)
   ```

4. **Running Tests**:
   ```bash
   # Run all tests
   ./gradlew test

   # Run tests for changed modules
   ./gradlew clients:test core:test

   # Run specific test
   ./gradlew core:test --tests kafka.api.ProducerFailureHandlingTest
   ```

5. **Commit**:
   ```bash
   # Write meaningful commit messages
   # Format: [KAFKA-XXXXX] Brief description
   #
   # More detailed explanation of changes
   git commit -am "[KAFKA-12345] Fix bug in ProducerTest"
   ```

6. **Push to Your Fork**:
   ```bash
   git push origin KAFKA-12345-description
   ```

7. **Create Pull Request**:
   - Go to GitHub and create PR from your fork to `apache/kafka:main`
   - PR title should reference JIRA ticket: `[KAFKA-12345] Brief description`
   - Use the PR template provided in `PULL_REQUEST_TEMPLATE.md`
   - Include:
     - Summary of changes
     - Testing strategy (unit/integration/system tests)
     - Any documentation changes needed

### Pull Request Template

See `PULL_REQUEST_TEMPLATE.md` in repository root. Include:

```markdown
*More detailed description of your change, if necessary.
The PR title and PR message become the squashed commit message.*

*Summary of testing strategy (including rationale) for the feature or bug fix.
Unit and/or integration tests are expected for any behaviour change and
system tests should be considered for larger changes.*

### Committer Checklist (excluded from commit message)
- [ ] Verify design and implementation
- [ ] Verify test coverage and CI build status
- [ ] Verify documentation (including upgrade notes)
```

### Code Review Expectations

1. **Reviewers**:
   - Committers and experienced contributors review PRs
   - Assign specific reviewers if known
   - Multiple approvals typically required for major changes

2. **Approval Process**:
   - At least one +1 (approval) required
   - CI build must pass (all 4 Java/Scala combinations)
   - May request changes with specific feedback
   - Committer can merge when approved

3. **Code Standards**:
   - Follow Kafka's checkstyle rules
   - No spotbugs warnings
   - Proper test coverage required
   - Javadoc for public APIs
   - Backward compatibility considerations

4. **License Agreement**:
   - By submitting a PR, you agree to license your contribution under the project's open source license (Apache License 2.0)
   - This applies to all copyrighted material submitted via PR, email, or other means

### After Approval

1. **Final Updates**:
   - Address any requested changes
   - Push additional commits
   - Ensure CI passes with updated code

2. **Merge**:
   - Committer merges the PR
   - Commit message typically uses squashed format from PR template
   - Closed PR automatically closes associated JIRA ticket

---

## 6. Developer Workflow Example

### Complete Step-by-Step Example

Scenario: Fix a bug in Kafka's producer where it incorrectly handles metadata refresh.

#### Step 1: Find and Understand the Issue
```bash
# Browse JIRA at https://issues.apache.org/jira/browse/KAFKA
# Find issue: KAFKA-14850 "Producer not refreshing metadata on broker errors"

# Comment on the ticket:
# "I'd like to work on this bug. I'll investigate and submit a fix."
```

#### Step 2: Setup Local Repository
```bash
# Fork apache/kafka on GitHub
# Clone your fork
git clone https://github.com/YOUR_USERNAME/kafka.git
cd kafka

# Add upstream remote
git remote add upstream https://github.com/apache/kafka.git
git fetch upstream

# Create feature branch from main
git checkout -b KAFKA-14850-producer-metadata-refresh
```

#### Step 3: Investigate and Code
```bash
# Explore relevant code
# Look at clients/src/main/java/org/apache/kafka/clients/producer/

# Run existing tests to understand failure
./gradlew clients:test --tests KafkaProducerTest

# Identify the bug and write fix
# Example: Update MetadataUpdater.java to refresh on broker errors

# Write or update test
# Example: Add test case to KafkaProducerTest
```

#### Step 4: Local Testing
```bash
# Run specific test to verify fix
./gradlew clients:test --tests KafkaProducerTest.testMetadataRefreshOnBrokerError

# Run all client tests
./gradlew clients:test

# Run code quality checks
./gradlew checkstyleMain checkstyleTest spotlessApply
./gradlew spotbugsMain -x test
```

#### Step 5: Commit Changes
```bash
# Stage changes
git add -A

# Commit with meaningful message
git commit -m "[KAFKA-14850] Fix producer metadata not refreshing on broker errors

When a producer encounters a broker error, it should refresh metadata
immediately rather than waiting for the next scheduled refresh.

This change updates MetadataUpdater to call maybeUpdate() when broker
errors are encountered, ensuring rapid recovery from broker failures.

Testing:
- Added unit test: testMetadataRefreshOnBrokerError
- Ran full client test suite: all tests pass
- Code quality: checkstyle and spotbugs clean"
```

#### Step 6: Push and Create PR
```bash
# Push to your fork
git push origin KAFKA-14850-producer-metadata-refresh

# Go to GitHub and create Pull Request
# - From: YOUR_USERNAME:KAFKA-14850-producer-metadata-refresh
# - To: apache:kafka:main
# - Title: [KAFKA-14850] Fix producer metadata not refreshing on broker errors
# - Description:
```

#### Step 7: PR Description Template
```markdown
## Summary
The Kafka producer was not refreshing metadata when encountering broker errors,
leading to extended periods of unavailability after broker restarts. This fix
ensures metadata is refreshed immediately upon broker errors.

## Testing
- Added unit test: `testMetadataRefreshOnBrokerError()` in KafkaProducerTest
- Verified: all 127 client tests pass
- Code quality: checkstyle ✓, spotbugs ✓
- No backward compatibility issues

## Verification
```bash
./gradlew clients:test
```

All tests pass with 4 Java/Scala combinations on CI.
```

#### Step 8: Address Review Comments
```bash
# If reviewers request changes:
# Make edits to the code
vim clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java

# Run tests again
./gradlew clients:test --tests KafkaProducerTest.testMetadataRefreshOnBrokerError

# Commit the changes
git add -A
git commit -m "[KAFKA-14850] Address review comments: improve error handling"

# Push updated commit
git push origin KAFKA-14850-producer-metadata-refresh
```

#### Step 9: Merge
```bash
# Once approved by committer, PR is merged
# You'll see the commit in main branch:
git fetch upstream
git log upstream/main | grep KAFKA-14850
```

#### Step 10: Cleanup
```bash
# Delete your local branch
git checkout main
git branch -D KAFKA-14850-producer-metadata-refresh

# Delete remote branch
git push origin --delete KAFKA-14850-producer-metadata-refresh

# Update local main
git pull upstream main
```

---

## Additional Resources

### Official Documentation
- **Apache Kafka Website**: https://kafka.apache.org
- **Contributing Guide**: https://kafka.apache.org/contributing.html
- **Contributing Code Changes**: https://cwiki.apache.org/confluence/display/KAFKA/Contributing+Code+Changes
- **Protocol Guide**: https://kafka.apache.org/protocol.html
- **Quickstart**: https://kafka.apache.org/quickstart

### Key Documentation Files in Repo
- `README.md` - Build and test instructions
- `tests/README.md` - System tests and Trogdor framework
- `vagrant/README.md` - Vagrant development environment
- `docker/README.md` - Docker build and testing
- `jmh-benchmarks/README.md` - JMH microbenchmarks
- `core/src/test/java/kafka/test/junit/README.md` - Cluster test annotations

### JIRA
- **Issue Tracking**: https://issues.apache.org/jira/browse/KAFKA
- Look for issues with `newbie` label for first-time contributions

### Development Tools
- **IDE Support**: IntelliJ IDEA has built-in Gradle support; can also generate with `./gradlew idea`
- **Build Scans**: https://ge.apache.org (Apache Gradle Enterprise)
- **Dependency Analysis**:
  ```bash
  ./gradlew allDeps
  ./gradlew dependencyUpdates
  ```

### Common Issues and Solutions

**Issue**: Tests fail with Java 21 related to spotless
- **Solution**: Run spotlessCheck/spotlessApply with JDK 11 or 17 instead

**Issue**: Long build times
- **Solution**: Use `-PmaxParallelForks=1` to reduce parallelism if tests are flaky

**Issue**: Stale lock files
- **Solution**: Run `./gradlew clean` to reset build state

---

## Summary

The Kafka contribution workflow:

1. **Find** an issue on JIRA (https://issues.apache.org/jira/browse/KAFKA)
2. **Clone** your fork and create a feature branch
3. **Code** your fix with tests
4. **Verify** with `./gradlew test` and code quality checks
5. **Commit** with meaningful message referencing JIRA ticket
6. **Push** to your fork and create a PR
7. **Respond** to review comments
8. **Merge** when approved by committers

The Kafka project welcomes contributions from the community. Start with small bugs or documentation fixes, then progress to larger features. Engage early with committers and the community through JIRA comments and PR discussions.
