# Envoy Contributor Guide

## 1. Build Prerequisites

### Required Tools and Versions

Before building Envoy, you must install the following dependencies:

#### Linux (Ubuntu)
```bash
sudo apt-get install \
   autoconf \
   curl \
   libtool \
   patch \
   python3-pip \
   unzip \
   virtualenv
```

**Compiler Requirements:**
- Clang >= 9 (currently CI uses Clang 14) - Recommended for development
- GCC >= 9 - Also known to work
- C++20 standard support required

For Clang setup on Linux:
1. Download Clang 14 from [LLVM official site](http://releases.llvm.org/download.html)
2. Extract and run: `bazel/setup_clang.sh <PATH_TO_EXTRACTED_CLANG_LLVM>`
3. Optional - make Clang default: `echo "build --config=clang" >> user.bazelrc`

**Additional Compiler Toolchain:**
- Go version 1.17+ (required for BoringSSL and Buildifier)
- Install buildifier: `go install github.com/bazelbuild/buildtools/buildifier@latest`
- Install buildozer: `go install github.com/bazelbuild/buildtools/buildozer@latest`

#### macOS
```bash
brew install coreutils wget libtool go bazelisk clang-format autoconf aspell
```

**Additional Requirements:**
- Full Xcode installation (not just Command Line Tools)
- Apple clang version 11.0.0 or higher
- Refer to bazel/README.md for SDK troubleshooting if needed

#### Windows
- Windows 10 SDK version 1803 (10.0.17134.12) minimum; version 1903+ recommended
- Visual Studio 2019 Build Tools (VC++ workload)
- MSYS2 shell (installed at path with no spaces, e.g., C:\msys64)
- Python 3 from python.org (not Windows Store or MSYS2 flavor)
- See bazel/README.md for detailed environment variable setup

### Build System Tool: Bazel

**Install Bazelisk** (recommended to avoid version compatibility issues):

Linux:
```bash
sudo wget -O /usr/local/bin/bazel https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-$([ $(uname -m) = "aarch64" ] && echo "arm64" || echo "amd64")
sudo chmod +x /usr/local/bin/bazel
```

macOS:
```bash
brew install bazelisk
```

### Envoy Dependencies Documentation
Full details available in:
- [Bazel Build Documentation](bazel/README.md) - Complete build instructions
- [Build Dependencies](https://www.envoyproxy.io/docs/envoy/latest/start/building#requirements) - Official documentation
- [Bazel Developer Guide](bazel/DEVELOPER.md) - Bazel rule development

---

## 2. Build System

### Build Tool Overview

Envoy uses **Bazel** as its primary build system. Bazel provides:
- Fast, incremental builds with caching
- Support for multiple compilation modes (debug, release, optimized)
- Remote Build Execution (RBE) support
- Modular extension system with customizable configurations

### Key Build Configuration

- **Configuration file:** `.bazelrc` (25KB with comprehensive settings)
- **JVM settings:** Started with `-Xmx3g` heap
- **C++ Standard:** C++20 on Linux with position-independent code
- **Workspace:** Defined in `WORKSPACE` file with modular dependency loading

### Build Commands

#### Development Builds (Recommended for Local Development)

```bash
# Fast development build (minimal optimization)
bazel build envoy

# Same as above (fastbuild mode by default)
bazel build -c fastbuild envoy
```

#### Production/Release Builds

```bash
# Optimized release build with full optimizations
bazel build -c opt envoy

# Optimized build without debug symbols
bazel build -c opt envoy.stripped
```

#### Debug Builds

```bash
# Debug build with symbols for GDB debugging
bazel build -c dbg envoy
```

#### Building Specific Components

```bash
# Build a specific library or target
bazel build //source/extensions/filters/network/http_connection_manager:lib

# Build just the static binary
bazel build //source/exe:envoy-static

# Build with specific compiler configuration
bazel build --config=clang envoy
```

### Build Configuration Options

#### Compiler Configurations

```bash
# Use Clang with libc++
bazel build --config=libc++ envoy

# Use Clang with libstdc++
bazel build --config=clang envoy

# Default (GCC with libstdc++)
bazel build envoy
```

#### Address Sanitizer (for bug detection)

```bash
# Build with ASAN enabled
bazel build -c dbg --config=asan envoy
bazel test -c dbg --config=asan //test/...
```

#### Thread Sanitizer

```bash
# Using Docker sandbox (recommended)
bazel test -c dbg --config=docker-tsan //test/...
```

#### Memory Sanitizer

```bash
# Using Docker sandbox
bazel test -c dbg --config=docker-msan //test/...
```

#### Remote Build Execution (RBE)

```bash
# Build with Google Cloud RBE
bazel build envoy --config=remote-clang \
    --remote_cache=grpcs://remotebuildexecution.googleapis.com \
    --remote_executor=grpcs://remotebuildexecution.googleapis.com \
    --remote_instance_name=projects/envoy-ci/instances/default_instance
```

#### Docker Sandbox

```bash
# Build using Docker sandbox with consistent toolchain
bazel build envoy --config=docker-clang
```

### Optional Features (can be disabled/enabled)

```bash
# Disable hot restart
bazel build envoy --define hot_restart=disabled

# Disable gRPC client support
bazel build envoy --define google_grpc=disabled

# Enable HTTP/3 (QUIC) - disabled by default
bazel build envoy --//bazel:http3=True

# Disable deprecated features
bazel build envoy --define deprecated_features=disabled

# Enable all deprecated features (for compatibility testing)
bazel build envoy --define deprecated_features=enabled
```

### Building with Docker (Easy Setup)

For development without local dependency installation:

```bash
# Build using CI Docker image
./ci/run_envoy_docker.sh './ci/do_ci.sh dev'
```

This uses the `envoyproxy/envoy-build-ubuntu` Docker image with all dependencies pre-installed.

### Code Formatting and Linting (without Docker)

```bash
# Check code formatting
bazel run //tools/code_format:check_format -- check

# Fix formatting issues
bazel run //tools/code_format:check_format -- fix

# Check spelling
./tools/spelling/check_spelling_pedantic.py check
```

---

## 3. Running Tests

### Test Framework

Envoy uses **Google Test (gtest)** with **Google Mock** for mocking. Custom matchers are provided for Envoy-specific testing needs.

### Test Directory Structure

```
test/
├── benchmark/          - Performance benchmark tests
├── common/             - Unit tests mirroring source/common structure
├── integration/        - End-to-end integration tests
├── fuzz/              - Fuzzing tests (OSS-Fuzz)
├── mocks/             - Mock implementations of core interfaces
├── extensions/        - Extension-specific unit tests
├── server/            - Server-specific tests
├── test_common/       - Shared test utilities and helpers
└── tools/             - Test infrastructure tools
```

### Running All Tests

```bash
# Run all tests
bazel test //test/...

# Run all tests with verbose output
bazel test --test_output=streamed //test/...
```

### Running Specific Tests

```bash
# Run a single test file/target
bazel test //test/common/http:async_client_impl_test

# Run with verbose output
bazel test --test_output=streamed //test/common/http:async_client_impl_test

# Run with trace-level logging
bazel test --test_output=streamed //test/common/http:async_client_impl_test --test_arg="-l trace"

# Force test re-run (bypass cache)
bazel test //test/common/http:async_client_impl_test --cache_test_results=no
```

### Running Tests with Specific Configurations

```bash
# Run tests with IPv4 only (useful in IPv4-only networks)
bazel test //test/... --test_env=ENVOY_IP_TEST_VERSIONS=v4only

# Run tests with IPv6 only
bazel test //test/... --test_env=ENVOY_IP_TEST_VERSIONS=v6only

# Run with Address Sanitizer
bazel test -c dbg --config=asan //test/...

# Run with thread sanitizer
bazel test -c dbg --config=docker-tsan //test/...
```

### Test Infrastructure Options

```bash
# Disable heap checker (normally enabled for leak detection)
bazel test //test/... --test_env=HEAPCHECK=

# Change heap checker mode
bazel test //test/... --test_env=HEAPCHECK=minimal

# Run tests without sandbox (for tools requiring filesystem access)
bazel test //test/... --strategy=TestRunner=local

# Run with custom test runner script
bazel test //test/http:http_test --strategy=TestRunner=local --run_under=/path/to/script.sh
```

### Integration Tests

```bash
# Run all integration tests
bazel test //test/integration/...

# Run specific integration test
bazel test //test/integration:protocol_integration_test

# Run with verbose protocol tracing
bazel test //test/integration:protocol_integration_test --test_output=streamed \
  --test_arg="-l trace" --test_env="ENVOY_NGHTTP2_TRACE="
```

### Debugging Tests with GDB

```bash
# Build test with debug symbols
bazel build -c dbg //test/common/http:async_client_impl_test
bazel build -c dbg //test/common/http:async_client_impl_test.dwp

# Run under GDB
gdb bazel-bin/test/common/http/async_client_impl_test
```

### Code Coverage

Generate comprehensive coverage reports:

```bash
# Full coverage report
test/run_envoy_bazel_coverage.sh
# Output: generated/coverage/coverage.html

# Coverage for specific test/target
VALIDATE_COVERAGE=false test/run_envoy_bazel_coverage.sh //test/common/http:async_client_impl_test

# Fuzz target coverage
FUZZ_COVERAGE=true VALIDATE_COVERAGE=false test/run_envoy_bazel_coverage.sh
# Output: generated/fuzz_coverage/coverage.html
```

**Coverage Requirements:** All new code must have 100% test coverage.

### Custom Test Matchers

Envoy provides custom Google Mock matchers for cleaner test code:

```cpp
// Test HTTP status code
EXPECT_THAT(response->headers(), HttpStatusIs("200"));

// Test specific header value
EXPECT_THAT(response->headers(), HeaderValueOf(Headers::get().Server, "envoy"));

// Test header with regex matcher
EXPECT_THAT(request->headers(),
            HeaderValueOf(Headers::get().AcceptEncoding, HasSubstr("gzip")));

// Compare header maps
EXPECT_THAT(response->headers(), HeaderMapEqualRef(expected_headers));

// Compare protobufs
EXPECT_THAT(config, ProtoEq(expected_config));
```

See [test/README.md](test/README.md) for comprehensive matcher documentation.

---

## 4. CI Pipeline

### CI Platform: GitHub Actions

Envoy uses **GitHub Actions** as the primary continuous integration platform, with additional integration systems.

### CI Configuration Files

- **Primary:** `.github/workflows/` directory (30+ workflow files)
- **Per-branch config:** `.github/config.yml` (runtime configuration per branch)
- **Dependency management:** `.github/dependabot.yml` (automated updates)
- **Bazel CI:** `.bazelci/presubmit.yml`
- **CircleCI:** `.circleci/config.yml`
- **Zuul (OpenStack):** `.zuul.yaml`

### Key GitHub Actions Workflows

| Workflow | Purpose | Trigger |
|----------|---------|---------|
| `_request.yml` | Entry point for all CI requests | Main branch push/PR |
| `request.yml` | Per-branch trigger | All branches |
| `envoy-prechecks.yml` | Format, dependencies, publish checks | Pre-commit |
| `envoy-checks.yml` | Core validation (build, test, lint) | Pull request |
| `envoy-macos.yml` | macOS-specific builds | Pull request |
| `codeql-daily.yml` | Security scanning | Daily schedule |
| `envoy-dependency.yml` | Dependency management | Automated |
| `envoy-publish.yml` | Release publishing | Release tags |
| `command.yml` | PR comment commands | PR comments |

### CI Checks That Run on Pull Requests

1. **Build checks:**
   - Debug build (`-c dbg`)
   - Optimized build (`-c opt`)
   - Release build (stripped)

2. **Test checks:**
   - Unit tests: `bazel test //test/...`
   - Integration tests
   - Fuzz testing
   - Coverage validation (100% for new code)

3. **Code quality checks:**
   - Format checking (clang-format)
   - Linting (clang-tidy)
   - Spelling check
   - Code coverage analysis

4. **Platform-specific:**
   - Linux builds (Ubuntu, CentOS)
   - macOS builds
   - Windows builds (optional, officially unsupported as of Aug 2023)

5. **Advanced checks:**
   - Address Sanitizer (ASAN)
   - Thread Sanitizer (TSAN)
   - Memory Sanitizer (MSAN)
   - CodeQL security scanning
   - Dependency validation

### CI Environment Variables

Control CI behavior in custom repositories:

```bash
ENVOY_CI=1              # Enable CI in non-official repositories
ENVOY_MOBILE_CI=1       # Enable Envoy Mobile CI
ENVOY_MACOS_CI=1        # Enable macOS CI
ENVOY_WINDOWS_CI=1      # Enable Windows CI (experimental)
CI_DEBUG=1              # Enable CI debug output
```

### Typical CI Run Timeline

- **Small PR (1-10 files changed):** 15-30 minutes
- **Medium PR (10-50 files changed):** 30-60 minutes
- **Large PR (50+ files changed):** 60-90+ minutes

Build time depends on:
- Number of files changed
- Whether it affects dependencies
- Number of tests affected
- CI system load

### Remote Build Execution (RBE)

Part of CI uses Google Cloud Remote Build Execution:
- Configuration: `--config=remote-clang`
- Provides consistent build environment across developers
- Can be used locally to match CI exactly

---

## 5. Code Review Process

### Contribution Workflow Overview

1. **Create GitHub Issue** (for major features > 100 LOC)
2. **Fork Repository**
3. **Create Feature Branch**
4. **Install Development Hooks**
5. **Implement and Test**
6. **Submit Pull Request**
7. **Address Review Comments**
8. **Merge**

### Key Documentation Files

- **[CONTRIBUTING.md](CONTRIBUTING.md)** - Main contribution guidelines (22KB)
- **[STYLE.md](STYLE.md)** - C++ coding standards (17KB, based on Google C++ style)
- **[PULL_REQUEST_TEMPLATE.md](PULL_REQUEST_TEMPLATE.md)** - Automated PR template
- **[OWNERS.md](OWNERS.md)** - Maintainer list and expertise areas
- **[CODEOWNERS](CODEOWNERS)** - Code ownership mapping (20KB)
- **[EXTENSION_POLICY.md](EXTENSION_POLICY.md)** - Extension contribution guidelines

### Installation: Development Support Toolchain

Before starting development, install git hooks for pre-commit and pre-push checks:

```bash
./support/bootstrap
```

This installs hooks that:
- Check code formatting (clang-format)
- Validate DCO sign-off on commits
- Check for common issues

See [support/README.md](support/README.md) for details.

### PR Requirements Checklist

#### Before Opening PR:

- [ ] Create GitHub issue for features > 100 LOC (discuss design first)
- [ ] Run `./support/bootstrap` to install git hooks
- [ ] Add unit and/or integration tests for new code
- [ ] Ensure 100% test coverage for new code (use `test/run_envoy_bazel_coverage.sh`)
- [ ] Follow C++ coding style ([STYLE.md](STYLE.md))
- [ ] Use inclusive language (no whitelist/blacklist, master/slave, etc.)
- [ ] Ensure all commits have DCO sign-off: `git commit -s`

#### PR Title and Description:

```
Format: <component>: <description>

Examples:
- "http conn man: add new feature"
- "docs: fix grammar error"
- "buffer: fix memory leak in read buffer"

Requirements:
- Start with subsystem name (lowercase)
- Descriptive, under 70 characters
- Include "Fixes #XXX" for bug fixes
- Include "Implements #XXX" for features
- Explain "why" not just "what"
- Include risk assessment: Low/Medium/High
```

#### PR Description Template:

```markdown
## Description
Brief explanation of what the PR does.

## Risk Level
Low / Medium / High

## Testing
How was this tested? (unit tests, integration tests, manual testing)

## Docs
Any documentation changes needed?

## Release Notes
Impact on users? Include in changelogs/current.yaml if user-facing.

Fixes #XXXX
```

#### PR Checklist Items:

- [ ] Changes include tests
- [ ] New code has 100% coverage
- [ ] Documentation updated (if user-facing)
- [ ] Release notes added (if user-facing)
- [ ] All commits have DCO sign-off
- [ ] No rebases after review starts (use merge commits instead)
- [ ] PR is not marked as draft

### Testing Requirements

```bash
# Verify test coverage (required: 100% for new code)
test/run_envoy_bazel_coverage.sh

# Run all affected tests
bazel test //test/...

# Run formatter check
bazel run //tools/code_format:check_format -- check

# Verify no spelling errors
./tools/spelling/check_spelling_pedantic.py check
```

### Code Review Process

1. **Automatic Checks:** GitHub Actions runs automatically
   - Build validation
   - Test execution
   - Format checking
   - Coverage validation

2. **Code Review Assignment:** Maintainers assigned based on CODEOWNERS
   - Reviews typically start within 24 hours
   - Maintainers have varying availability (tracked via Opsgenie)
   - Major feature reviews require broad consensus

3. **Review Guidelines:**
   - Be responsive to feedback
   - If PR hasn't progressed in 7 days, may be closed
   - Use merge commits for updates (don't rebase)
   - Don't force push after review starts

4. **Approval and Merge:**
   - Requires approval from designated maintainer
   - All CI checks must pass
   - Squash merge is used (number of commits doesn't matter)

### Breaking Changes and Deprecation

**Deprecation Process:**
1. Mark feature deprecated in proto/code
2. Add `DEPRECATED_FEATURE_TEST()` for old functionality tests
3. Implement conversion to new functionality
4. Document in release notes

**Timeline:**
- **Release N:** Feature marked deprecated, warnings logged
- **Release N+1:** Default to failure (unless explicitly overridden)
- **Release N+2+:** Code removed entirely

### Release Notes

All user-facing changes must include release notes in `changelogs/current.yaml`:

```yaml
# Format: subsystem in alphabetical order
bug_fixes:
- area: http
  change: |
    Fix memory leak in HTTP request parsing when receiving large headers.

- area: http conn man
  change: |
    Fixed bug where stream was not properly reset on connection close.
    (Fixes #12345)

features:
- area: http router
  change: |
    Added new configuration option `max_grpc_timeout` to limit gRPC
    timeout headers. (Implements #12346)
```

### Style Guide and Code Standards

See [STYLE.md](STYLE.md) for complete C++ style guide including:
- Naming conventions (classes, functions, variables)
- Comment style and documentation
- Header file organization
- Exception handling policy
- Logging standards
- Deviations from Google C++ style guide

### Development Tools

**Code Formatting:**
```bash
# Check format
bazel run //tools/code_format:check_format -- check

# Fix formatting
bazel run //tools/code_format:check_format -- fix
```

**Linting:**
- Configured in `.clang-tidy`
- Runs automatically in CI

**Editor Setup:**
- **VS Code:** See [tools/vscode/README.md](tools/vscode/README.md)
- **Compilation Database:** `tools/gen_compilation_database.py` for clangd/YouCompleteMe

---

## 6. Developer Workflow Example

### Scenario: Fix Bug in HTTP Connection Manager Filter

The HTTP Connection Manager is a critical component that processes HTTP traffic. Let's walk through fixing a hypothetical bug where stream state is not properly cleaned up on connection close.

### Step-by-Step Workflow

#### Phase 1: Setup (One-time)

```bash
# Clone the repository
git clone https://github.com/yourusername/envoy.git
cd envoy

# Create tracking branch from main
git checkout main
git pull upstream main

# Install development support (pre-commit hooks, formatters)
./support/bootstrap

# Verify your Bazel setup
bazel build envoy --help  # Should work without errors
```

#### Phase 2: Create Issue and Discuss Design

Before starting implementation:

```bash
# Open GitHub issue describing the bug:
# Title: "http conn man: memory leak when stream not cleaned up on connection close"
# Description:
# - Reproduction steps
# - Expected behavior
# - Actual behavior
# - Suspected component: HTTP Connection Manager filter

# Wait for maintainer feedback/confirmation before proceeding
```

#### Phase 3: Create Feature Branch

```bash
git checkout -b fix/http-stream-cleanup-on-close
```

#### Phase 4: Locate and Understand the Code

The HTTP Connection Manager is located at:

```bash
# Main implementation
ls -la source/extensions/filters/network/http_connection_manager/

# Key files:
# - http_connection_manager.h       (header with main class)
# - http_connection_manager.cc      (implementation)
# - active_stream.h                 (stream state management)
# - active_stream.cc                (stream cleanup logic)
```

Examine the code:

```bash
# Read the filter implementation
cat source/extensions/filters/network/http_connection_manager/http_connection_manager.h

# Look for connection close handling
grep -n "onDownstreamConnectionClose\|reset\|cleanup" \
  source/extensions/filters/network/http_connection_manager/*.cc

# Examine related tests
ls test/extensions/filters/network/http_connection_manager/
```

#### Phase 5: Implement the Fix

Based on analysis, create a fix. Example: ensuring streams are properly cleaned up in the connection close handler.

```cpp
// File: source/extensions/filters/network/http_connection_manager/http_connection_manager.cc

void HttpConnectionManager::onDownstreamConnectionClose() {
  // ... existing code ...

  // FIX: Properly clean up active streams
  for (auto& stream : active_streams_) {
    stream->resetStream(reason);  // Add missing cleanup
  }
}
```

#### Phase 6: Write Tests

Create unit tests for the fix:

```bash
# Test file location follows source structure
cat test/extensions/filters/network/http_connection_manager/http_connection_manager_test.cc

# Add new test case:
TEST_F(HttpConnectionManagerTest, StreamCleanupOnConnectionClose) {
  // Arrange: Set up stream with pending data
  // Act: Close connection
  // Assert: Verify stream is properly cleaned up
}
```

#### Phase 7: Build and Verify Locally

```bash
# Build the specific component
bazel build //source/extensions/filters/network/http_connection_manager:lib

# Build the executable
bazel build -c opt envoy

# Run unit tests for the component
bazel test //test/extensions/filters/network/http_connection_manager:http_connection_manager_test

# Run all HTTP-related tests
bazel test //test/extensions/filters/network/http_connection_manager/...

# Check code coverage (must be 100% for new code)
test/run_envoy_bazel_coverage.sh \
  //test/extensions/filters/network/http_connection_manager:http_connection_manager_test
```

#### Phase 8: Format and Lint Code

```bash
# Run formatter check
bazel run //tools/code_format:check_format -- check

# Auto-fix formatting
bazel run //tools/code_format:check_format -- fix

# Check spelling
./tools/spelling/check_spelling_pedantic.py check
```

#### Phase 9: Commit Changes

The development hooks from `./support/bootstrap` will:
- Verify code formatting
- Check for DCO sign-off
- Validate commit message style

```bash
# Stage your changes
git add source/extensions/filters/network/http_connection_manager/*.cc \
        test/extensions/filters/network/http_connection_manager/*_test.cc

# Commit with DCO sign-off (hooks will enforce this)
git commit -s -m "http conn man: fix stream cleanup on connection close

Previously, active streams were not properly cleaned up when the
downstream connection closed, leading to memory leaks. This fix ensures
all active streams are reset with the connection_termination reason code
when the connection closes.

Fixes #12345"
```

#### Phase 10: Update Release Notes

If the fix affects user-facing behavior:

```yaml
# File: changelogs/current.yaml
bug_fixes:
- area: http conn man
  change: |
    Fixed memory leak when streams are not properly cleaned up on
    downstream connection close. (Fixes #12345)
```

#### Phase 11: Push and Create Pull Request

```bash
# Push your branch
git push origin fix/http-stream-cleanup-on-close

# GitHub will show a "Compare & pull request" button
# Or create PR at: https://github.com/envoyproxy/envoy/pulls

# PR Title: "http conn man: fix stream cleanup on connection close"
# PR Description template filled in with:
# - What changed and why
# - How tested (ran unit tests, coverage 100%)
# - Risk assessment (Low - isolated to stream cleanup logic)
# - Release notes included
# - Fixes #12345
```

#### Phase 12: Respond to Review

GitHub Actions automatically:
- Builds the code in multiple modes (debug, release)
- Runs full test suite
- Checks code formatting
- Validates test coverage
- Runs additional sanitizers

Maintainer provides code review feedback:

```bash
# If changes needed, make them locally
git add modified_files.cc
git commit -m "Address review feedback: improve error handling"
git push origin fix/http-stream-cleanup-on-close

# Do NOT rebase after review starts - use merge instead
git pull origin main
# (Resolve any conflicts)
git push origin fix/http-stream-cleanup-on-close
```

#### Phase 13: Merge

Once approved and all CI checks pass:
- Maintainer merges with squash (all commits become one)
- PR closes automatically
- Changes become part of main branch
- Will be included in next release

#### Phase 14: Verify in CI

Final verification in CI:
- Full test suite passes: `bazel test //test/...`
- Coverage validation passes
- All sanitizers pass
- All platforms (Linux, macOS) pass

### Key Commands Reference

```bash
# Setup
./support/bootstrap
bazel build envoy

# Development
bazel build //source/extensions/filters/network/http_connection_manager:lib
bazel test //test/extensions/filters/network/http_connection_manager:http_connection_manager_test
test/run_envoy_bazel_coverage.sh

# Cleanup
bazel run //tools/code_format:check_format -- fix

# Git workflow
git checkout -b fix/issue-name
git commit -s -m "component: description"
git push origin fix/issue-name
```

### Common Issues and Solutions

| Issue | Solution |
|-------|----------|
| Build fails with missing dependencies | Run: `bazel clean --expunge` then rebuild |
| Tests fail in local but pass in CI | Try: `bazel test --config=docker-clang` to match CI environment |
| Code formatting fails | Run: `bazel run //tools/code_format:check_format -- fix` |
| Coverage is not 100% | Add tests for untested code paths |
| DCO sign-off missing | Use: `git commit -s` or `git rebase --exec 'git commit --amend --no-edit -n -S' main` |

---

## Additional Resources

### Official Documentation

- **[Envoy Project Website](https://www.envoyproxy.io/)**
- **[Project Governance](GOVERNANCE.md)** - Decision-making and maintainer structure
- **[Extension Policy](EXTENSION_POLICY.md)** - Guidelines for adding new extensions
- **[Dependency Policy](DEPENDENCY_POLICY.md)** - External dependency management
- **[API Versioning](api/API_VERSIONING.md)** - Data plane API stability guarantees

### Build and Testing

- **[Bazel Build Guide](bazel/README.md)** - Comprehensive build documentation
- **[External Dependencies](bazel/EXTERNAL_DEPS.md)** - Managing dependencies
- **[Performance Testing](bazel/PPROF.md)** - Using tcmalloc/pprof
- **[Test Framework](test/README.md)** - Overview of test infrastructure
- **[Integration Tests](test/integration/README.md)** - Writing integration tests

### Development Environment

- **[VS Code Setup](tools/vscode/README.md)** - IDE configuration
- **[Docker CI](ci/README.md)** - Using CI Docker image locally
- **[Envoy Filter Example](https://github.com/envoyproxy/envoy-filter-example)** - Template for external filters

### Architecture and Design

- **[Flow Control](source/docs/flow_control.md)** - Data flow in Envoy
- **[Subset Load Balancer](source/docs/subset_load_balancer.md)** - Component deep-dive
- **[Release Process](RELEASES.md)** - How releases are managed
- **[Repository Layout](REPO_LAYOUT.md)** - Directory structure explanation

### Community

- **[Code of Conduct](CODE_OF_CONDUCT.md)** - Community expectations
- **[Security Policy](SECURITY.md)** - Reporting vulnerabilities
- **[Slack Channel](https://envoyproxy.io/community/get-in-touch/)** - Real-time community discussion

---

## Quick Reference

### Essential Commands

```bash
# Initial setup
./support/bootstrap

# Build variants
bazel build envoy                              # Development build
bazel build -c opt envoy                       # Production build
bazel build -c dbg envoy                       # Debug with symbols

# Testing
bazel test //test/...                          # All tests
bazel test //test/common/http:...              # Specific package
test/run_envoy_bazel_coverage.sh               # Coverage report

# Code quality
bazel run //tools/code_format:check_format -- fix
./tools/spelling/check_spelling_pedantic.py fix

# Git workflow
git checkout -b feature-name
git commit -s -m "component: description"
git push origin feature-name
```

### Key Directories

| Path | Purpose |
|------|---------|
| `source/` | Main Envoy implementation |
| `source/extensions/` | Modular filter and extension implementations |
| `test/` | Test infrastructure and test code |
| `bazel/` | Build system configuration and rules |
| `docs/` | End-user documentation |
| `changelogs/` | Release notes and version history |
| `.github/workflows/` | GitHub Actions CI configuration |

---

**Version:** Envoy v1.32.1 (API v3.0.0)
**Last Updated:** February 2026
**Documentation Quality:** Production-ready based on official Envoy sources
