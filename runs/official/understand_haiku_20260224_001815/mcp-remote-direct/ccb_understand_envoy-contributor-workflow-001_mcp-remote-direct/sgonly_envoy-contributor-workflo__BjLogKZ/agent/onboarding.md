# Envoy Contributor Guide

## 1. Build Prerequisites

### System Requirements

Before building Envoy, you need to install several dependencies depending on your platform:

**Ubuntu/Debian:**
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

**Fedora/RHEL:**
```bash
dnf install \
    aspell-en \
    libatomic \
    libstdc++ \
    libstdc++-static \
    libtool \
    lld \
    patch \
    python3-pip
```

**macOS:**
- Install Homebrew if not already installed
- Run: `brew install coreutils wget libtool go bazelisk clang-format autoconf aspell`
- Requires full Xcode installation (not just Command Line Tools)
- Xcode 11.1 or later is required

**Windows:**
- Windows 10 SDK version 1903 or later (10.0.18362.1)
- Visual Studio 2019 Build Tools with VC++ workload
- MSYS2 shell (install to path without spaces, e.g., C:\msys64)
- Python 3 (Windows-native flavor from python.org)
- Git

### Compiler Requirements

- **Clang**: 9 or later (Clang 14 is currently used in CI)
- **GCC**: 9 or later
- **Go**: 1.17 or later (for BoringSSL and buildifier)

### Language Standard

Envoy requires **C++17** support and uses C++17 features throughout the codebase.

### Installation of Bazelisk

Bazelisk is the recommended tool to use instead of Bazel directly to avoid version incompatibilities.

**Linux:**
```bash
sudo wget -O /usr/local/bin/bazel https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-$([ $(uname -m) = "aarch64" ] && echo "arm64" || echo "amd64")
sudo chmod +x /usr/local/bin/bazel
```

**macOS:**
```bash
brew install bazelisk
```

**Windows:**
```cmd
mkdir %USERPROFILE%\bazel
powershell Invoke-WebRequest https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-windows-amd64.exe -OutFile %USERPROFILE%\bazel\bazel.exe
set PATH=%USERPROFILE%\bazel;%PATH%
```

### Build Tools Installation

After installing Go, install the Bazel formatting and analysis tools:
```bash
go install github.com/bazelbuild/buildtools/buildifier@latest
go install github.com/bazelbuild/buildtools/buildozer@latest
```

You may need to set these environment variables:
```bash
export BUILDIFIER_BIN=$GOPATH/bin/buildifier
export BUILDOZER_BIN=$GOPATH/bin/buildozer
```

### Linux Clang Setup (Optional but Recommended)

Download Clang 14 from the [LLVM official site](http://releases.llvm.org/download.html), extract it, and run:
```bash
bazel/setup_clang.sh <PATH_TO_EXTRACTED_CLANG_LLVM>
```

To make Clang the default compiler:
```bash
echo "build --config=clang" >> user.bazelrc
```

---

## 2. Build System

### Overview

Envoy uses **Bazel** as its build system. Bazel provides:
- Fine-grained dependency management
- Reproducible builds
- Support for building both development and production artifacts
- Integration with various build configurations and tests

Key Bazel documentation:
- [Building Envoy with Bazel](https://github.com/envoyproxy/envoy/blob/main/bazel/README.md)
- [Managing external dependencies](https://github.com/envoyproxy/envoy/blob/main/bazel/EXTERNAL_DEPS.md)
- [Guide to Envoy Bazel rules](https://github.com/envoyproxy/envoy/blob/main/bazel/DEVELOPER.md)

### Repository Structure

The Envoy repository is organized as:
- `source/` - Core Envoy code and extensions
- `source/common/` - Core library code
- `source/exe/` - Code for the standalone server binary
- `source/extensions/` - All Envoy extensions (filters, tracers, clusters, etc.)
- `test/` - Unit and integration tests
- `api/` - Protocol buffer definitions for the xDS API
- `bazel/` - Bazel configuration and rules
- `ci/` - CI scripts and Docker configurations
- `docs/` - User-facing documentation
- `tools/` - Developer utilities

### Basic Build Commands

**Build the entire Envoy binary (development mode):**
```bash
bazel build envoy
```

**Build with optimization (release mode):**
```bash
bazel build -c opt envoy
```

**Build with debugging symbols:**
```bash
bazel build -c dbg envoy
```

**Build a specific component:**
```bash
bazel build //source/extensions/filters/http/router:config
```

**Use Docker for builds (recommended for consistency):**
```bash
./ci/run_envoy_docker.sh './ci/do_ci.sh dev'
```

### Compilation Modes

Bazel supports three compilation modes:
- **fastbuild** (default): `-O0`, fast compilation, good for development
- **opt**: `-O2 -DNDEBUG`, optimized for production
- **dbg**: `-O0 -ggdb3`, debugging symbols without optimization

### Build Configuration Options

**Disable optional features:**
- Hot restart: `--define hot_restart=disabled`
- gRPC: `--define google_grpc=disabled`
- tcmalloc: `--define tcmalloc=disabled`
- Signal tracing: `--define signal_trace=disabled`
- HTTP/3: `--//bazel:http3=False`

**Enable optional features:**
- FIPS-compliant BoringSSL: `--define boringssl=fips`
- Exported symbols: `--define exported_symbols=enabled`
- Performance annotations: `--define perf_annotation=enabled`

**Extension configuration:**
```bash
# Disable an extension
bazel build envoy --//source/extensions/filters/http/ext_authz:enabled=false

# Enable an extension (if not enabled by default)
bazel build envoy --//source/extensions/filters/http/kill_request:enabled
```

### Size Optimization

For building smaller binaries:
```bash
bazel build envoy --config=sizeopt
```

### Clang-Tidy and Code Formatting

**Check code formatting:**
```bash
bazel run //tools/code_format:check_format -- check
```

**Fix code formatting:**
```bash
bazel run //tools/code_format:check_format -- fix
```

**Run clang-tidy:**
```bash
./ci/run_envoy_docker.sh './ci/do_ci.sh clang_tidy'
```

---

## 3. Running Tests

### Test Framework

Envoy uses the **Google Test framework** (gtest) for unit tests and includes:
- [Google Test](https://github.com/google/googletest) for assertions and matchers
- [Google Mock](https://github.com/google/googletest/blob/master/googlemock/README.md) for mocking
- Custom matchers for HTTP headers, protobufs, etc.
- Integration testing framework for end-to-end testing

### Test Locations

- **Unit tests**: Located in `test/` directory mirroring the `source/` structure
  - Example: Code in `source/common/http/` has tests in `test/common/http/`
- **Extension tests**: `test/extensions/` mirrors `source/extensions/`
- **Integration tests**: `test/integration/`
- **Mock implementations**: `test/mocks/`

### Running Tests

**Run all tests:**
```bash
bazel test //test/...
```

**Run a specific test file:**
```bash
bazel test //test/common/http:async_client_impl_test
```

**Run with verbose output:**
```bash
bazel test --test_output=streamed //test/common/http:async_client_impl_test
```

**Run with additional test arguments:**
```bash
bazel test --test_output=streamed //test/common/http:async_client_impl_test --test_arg="-l trace"
```

**Disable test result caching (force rerun):**
```bash
bazel test //test/common/http:async_client_impl_test --cache_test_results=no
```

### Test Environment Variables

**Control IP versions tested:**
```bash
# Test IPv4 only
bazel test //test/... --test_env=ENVOY_IP_TEST_VERSIONS=v4only

# Test IPv6 only
bazel test //test/... --test_env=ENVOY_IP_TEST_VERSIONS=v6only
```

**Configure heap checker (gperftools):**
```bash
# Disable heap checker
bazel test //test/... --test_env=HEAPCHECK=

# Use minimal mode
bazel test //test/... --test_env=HEAPCHECK=minimal
```

### Specialized Test Configurations

**Address Sanitizer (ASAN):**
```bash
bazel test -c dbg --config=clang-asan //test/...
```

**Thread Sanitizer (TSAN):**
```bash
bazel test -c dbg --config=docker-tsan //test/...
```

**Memory Sanitizer (MSAN):**
```bash
bazel test -c dbg --config=docker-msan //test/...
```

**Coverage reports:**
```bash
test/run_envoy_bazel_coverage.sh
# Results: generated/coverage/coverage.html
```

### Debugging Tests

**Run a test under GDB:**
```bash
bazel build -c dbg //test/common/http:async_client_impl_test
bazel build -c dbg //test/common/http:async_client_impl_test.dwp
gdb bazel-bin/test/common/http/async_client_impl_test
```

**Run test with custom sandbox isolation:**
```bash
bazel test //test/common/http:async_client_impl_test --strategy=TestRunner=local
```

---

## 4. CI Pipeline

### Overview

Envoy uses **Azure Pipelines** for its main CI system. The CI pipeline:
- Builds Envoy with multiple configurations (clang, gcc, various sanitizers)
- Runs the full test suite
- Checks code formatting and style
- Runs clang-tidy static analysis
- Generates coverage reports
- Builds Docker images
- Tests on macOS and Linux

**CI Status Dashboard**: [Azure Pipelines - CNCF/Envoy](https://dev.azure.com/cncf/envoy/_build)

### CI Configuration Files

- **Azure Pipelines**: `.azure-pipelines/` directory (main CI configuration)
- **Circle CI**: `.circleci/config.yml` (minimal, placeholder only)
- **Build scripts**: `ci/do_ci.sh` (main entry point for CI builds)
- **Docker**: `ci/` directory contains CI Docker image configurations

### Supported CI Targets

The `./ci/do_ci.sh` script provides various build targets for local and CI execution:

**Development builds:**
- `dev` - Build with fastbuild and run tests (clang)
- `dev.contrib` - Development build with contrib extensions
- `debug` - Build with debug symbols and run tests
- `release` - Build optimized binary and run tests
- `sizeopt` - Size-optimized build and tests

**Specific test configurations:**
- `asan` - Build and test with ASAN (address sanitizer)
- `tsan` - Build and test with TSAN (thread sanitizer)
- `msan` - Build and test with MSAN (memory sanitizer)
- `coverage` - Build and generate coverage report

**Code quality:**
- `format` - Run formatting and linting tools
- `clang_tidy <files>` - Run clang-tidy on specified files
- `check_proto_format` - Validate API proto files
- `fix_proto_format` - Fix formatting in proto files

**Other targets:**
- `api` - Build and test API
- `compile_time_options` - Test with various compile-time options
- `docs` - Generate documentation

### Running CI Builds Locally

**Using Docker (recommended for consistency):**
```bash
./ci/run_envoy_docker.sh './ci/do_ci.sh dev'
```

**Set custom build directory:**
```bash
ENVOY_DOCKER_BUILD_DIR=~/build ./ci/run_envoy_docker.sh './ci/do_ci.sh release.server_only'
```

**Use custom Docker image:**
```bash
IMAGE_NAME=envoyproxy/envoy-build-ubuntu ./ci/run_envoy_docker.sh './ci/do_ci.sh dev'
```

### CI Troubleshooting

**Trigger CI re-run without code changes:**
```bash
# Comment on PR with:
/retest
```

**Force full CI re-run:**
```bash
# Push an empty commit
git commit -s --allow-empty -m 'Kick CI'
git push
```

Or use the alias:
```bash
git config --add alias.kick-ci "!git commit -s --allow-empty -m 'Kick CI' && git push"
git kick-ci
```

### CI Checks on Pull Requests

When you open a PR, the following CI checks automatically run:
1. **Build checks** - Builds succeed on multiple configurations
2. **Test execution** - All unit and integration tests pass
3. **Code formatting** - clang-format compliance
4. **Linting** - clang-tidy, spell checking
5. **Code coverage** - Coverage metrics (target: 100% for new code)
6. **Integration tests** - End-to-end testing
7. **Sanitizer tests** - ASAN, TSAN, MSAN checks

**All checks must pass before PR merge.**

---

## 5. Code Review Process

### Prerequisites for Submission

Before creating a PR, you must:

1. **Install development support tools:**
   ```bash
   ./support/bootstrap
   ```
   This installs git hooks for automatic DCO sign-off and format checking.

2. **Understand the contribution guidelines:**
   - Read [CONTRIBUTING.md](https://github.com/envoyproxy/envoy/blob/main/CONTRIBUTING.md)
   - Review [STYLE.md](https://github.com/envoyproxy/envoy/blob/main/STYLE.md) for C++ style guidelines
   - For API changes, check [API_VERSIONING.md](https://github.com/envoyproxy/envoy/blob/main/api/API_VERSIONING.md)

3. **Determine if pre-discussion is needed:**
   - Major features (>100 LOC or user-facing behavior changes): Open a GitHub issue first
   - Small bug fixes: No prior communication needed

### Submitting a Pull Request

**PR Title Format:**
- Start with subsystem name in lowercase
- Examples: `http conn man: add new feature`, `docs: fix grammar`, `router: add x-envoy-overloaded header`

**PR Description Template:**

```
## Summary
[Brief description of what this PR does]

## Commit Message
[This becomes the Git commit message. Include behavior changes, fixes, etc.]

## Additional Description
[Provide context useful to reviewers]

## Risk Level
[Low | Medium | High]

## Testing
[Describe testing performed: unit tests, integration, manual testing]

## Documentation
[Document changes made or write "N/A" if none]

## Release Notes
[Add entry to changelogs/current.yaml or write "N/A"]

## Platform Specific Features
[If applicable, explain platform-specific code or write "N/A"]

## Issues
[Link issues: "Fixes #XXX" to auto-close on merge]

## API Considerations (if applicable)
[For API changes, address review checklist items]

Signed-off-by: Your Name <your.email@example.com>
```

### Required Conditions for Merge

✓ All CI checks must pass
✓ All tests must pass (100% test coverage for added code)
✓ Code must follow [STYLE.md](STYLE.md) guidelines
✓ Documentation updated for user-facing changes
✓ Release notes added (in `changelogs/current.yaml`)
✓ PR must be actively worked on (7+ days of inactivity = closure)
✓ DCO sign-off required (automatic via `./support/bootstrap` git hooks)

### The Code Review Workflow

1. **Reviewer assignment**: When your PR passes initial checks, a maintainer is assigned
2. **Review cycle**: Maintainers typically respond within one business day
3. **Address feedback**: Push new commits addressing reviewer comments
4. **Do NOT rebase**: After reviewer assignment, avoid rebasing (use merge instead)
   ```bash
   # Instead of rebasing, merge from main
   git checkout main
   git pull
   git checkout your-branch
   git merge main
   git push
   ```
5. **Merge**: Maintainers squash-merge your commits with a cleaned-up title and message

### Important Review Guidelines

- **Domain experts**: Code should be reviewed by someone knowledgeable in that area
- **Cross-company reviews**: For new extensions/features, at least one approval should be from a different organization than the PR author
- **Senior maintainer review**: Core code changes should be reviewed by at least one senior maintainer
- **Test coverage**: New code must have tests with 100% coverage (explain exceptions)

### Coding Standards and Compliance

**Inclusive Language Policy:**
Required replacements:
- `whitelist` → `allowlist`
- `blacklist` → `denylist` or `blocklist`
- `master` → `primary` or `main`
- `slave` → `secondary` or `replica`

**C++ Style:**
- Code formatted with clang-format (automatic)
- Google C++ style guidelines with Envoy-specific deviations
- 100-character line limit
- See [STYLE.md](STYLE.md) for detailed rules

**Breaking Changes:**
Governed by [API versioning](api/API_VERSIONING.md) and [deprecation policy](CONTRIBUTING.md#breaking-change-policy)
- Deprecated features must have replacement implementation available
- Multi-phase deprecation: warn → fail by default → remove

### Runtime Guarding High-Risk Changes

For high-risk behavioral changes, use runtime feature guards:

```cpp
if (Runtime::runtimeFeatureEnabled("envoy.reloadable_features.my_feature_name")) {
  [new code path]
} else {
  [old code path]
}
```

Features are set true in [source/common/runtime/runtime_features.cc](https://github.com/envoyproxy/envoy/blob/main/source/common/runtime/runtime_features.cc)

### DCO (Developer Certificate of Origin)

All commits must be signed off. The `./support/bootstrap` command sets up git hooks to auto-sign, but you can also:

```bash
# Sign individual commits
git commit -s

# Set up aliases
git config --add alias.c "commit -s"
git config --add alias.amend "commit -s --amend"

# Fix unsigned commits in PR
git rebase -i HEAD^^  # interactive rebase to squash
# Add sign-off: Signed-off-by: Name <email@example.com>
git push origin -f
```

---

## 6. Developer Workflow Example

### Scenario: Fix a Bug in the HTTP Router Filter

This walkthrough shows the complete workflow for contributing a bug fix to Envoy's HTTP router filter.

#### Step 1: Clone and Setup

```bash
# Clone the repository
git clone https://github.com/envoyproxy/envoy.git
cd envoy

# Create a feature branch
git checkout -b fix/http-router-bug

# Install development tools
./support/bootstrap
```

#### Step 2: Understand the Code Structure

The HTTP router filter is located at:
- **Code**: `source/extensions/filters/http/router/`
- **Tests**: `test/extensions/filters/http/router/`
- **Configuration**: `api/envoy/extensions/filters/http/router/`
- **Build rules**: `BUILD` files in each directory

Understand the architecture:
```
source/extensions/filters/http/router/
├── router.h              # Main filter implementation
├── router.cc
├── config.h              # Factory configuration
├── config.cc
└── BUILD

test/extensions/filters/http/router/
├── router_test.cc        # Unit tests
├── config_test.cc        # Configuration tests
└── BUILD
```

#### Step 3: Make Your Changes

Let's say we're fixing a bug in route header handling:

```bash
# Edit the relevant source files
vim source/extensions/filters/http/router/router.cc
vim source/extensions/filters/http/router/router.h
```

#### Step 4: Write/Update Tests

Add or update test coverage in `test/extensions/filters/http/router/`:

```bash
# Create/update test file
vim test/extensions/filters/http/router/router_test.cc

# Ensure 100% coverage for your changes
# Tests should cover normal operation and edge cases
```

Example test structure:
```cpp
TEST_F(RouterTest, TestMyFix) {
  // Setup test fixture
  // Execute code under test
  // Verify results with EXPECT_* macros
}
```

#### Step 5: Build and Test Locally

**Build just the router extension:**
```bash
bazel build //source/extensions/filters/http/router:router_lib
```

**Run the router tests:**
```bash
bazel test //test/extensions/filters/http/router:router_test
```

**Run with verbose output for debugging:**
```bash
bazel test --test_output=streamed //test/extensions/filters/http/router:router_test
```

**Run all router-related tests:**
```bash
bazel test //test/extensions/filters/http/router/...
```

#### Step 6: Check Code Style and Formatting

**Check formatting:**
```bash
bazel run //tools/code_format:check_format -- check
```

**Fix formatting issues automatically:**
```bash
bazel run //tools/code_format:check_format -- fix
```

**Run pre-commit checks manually:**
```bash
./support/bootstrap  # If not done yet
git add <your files>
# Pre-push hooks will run automatically on `git push`
```

#### Step 7: Documentation and Release Notes

If your fix changes user-visible behavior:

**Update documentation** (if needed):
```bash
# Edit relevant docs in docs/root/
vim docs/root/version_history.rst
```

**Add release note** to `changelogs/current.yaml`:
```yaml
- area: router
  change: |
    Fixed bug in route header handling where headers were incorrectly
    duplicated when using certain match conditions. Fixes #12345.
```

#### Step 8: Commit Your Changes

The `./support/bootstrap` git hooks make this automatic, but here's what happens:

```bash
# Stage your changes
git add source/extensions/filters/http/router/router.cc
git add test/extensions/filters/http/router/router_test.cc
git add changelogs/current.yaml

# Commit - hook will automatically add DCO sign-off
git commit -m "router: fix duplicate header bug

Previously, headers were duplicated when using multiple match conditions.
This fix ensures each header is added only once.

Fixes #12345"
```

The commit message will be automatically augmented with:
```
Signed-off-by: Your Name <your.email@example.com>
```

#### Step 9: Push and Create Pull Request

```bash
git push origin fix/http-router-bug
```

Then create a PR on GitHub with a title like:
- `router: fix duplicate header bug`

Use the PR template to fill in:
```
## Commit Message
[Your commit message above]

## Testing
- Added unit test: TestRouterDuplicateHeaderFix
- Verified with: bazel test //test/extensions/filters/http/router:router_test
- All 5 new tests pass; 100% coverage for bug fix code

## Documentation
- Updated changelogs/current.yaml with fix description
- No docs changes needed (internal fix)

## Risk Level
Low - affects only specific edge case in header matching

Fixes #12345
```

#### Step 10: Address Code Review Feedback

When reviewers request changes:

```bash
# Make the requested changes
vim source/extensions/filters/http/router/router.cc

# Add a new commit (do NOT rebase)
git add source/extensions/filters/http/router/router.cc
git commit -m "Address review feedback: clarify comment in header handling"

# Push the new commit
git push origin fix/http-router-bug
```

**Important**: Do not rebase or force-push after a reviewer is assigned. New commits are easier for reviewers to see incremental changes.

#### Step 11: Iterate Until Approval

The cycle continues:
1. Reviewer requests changes in PR comments
2. You make changes and push new commits
3. Reviewer approves when satisfied
4. A maintainer merges your PR with squash

The final commit will have:
- Cleaned-up title and message
- Your commits squashed into one
- Your original DCO sign-off preserved

#### Step 12: Monitor the Merged PR

After merge:
- Watch that CI completes successfully on main
- If you see failures on main related to your change, respond quickly
- PR is auto-closed (via "Fixes #12345" in commit message)
- Related issues are auto-closed

### Common Workflow Commands

**Update your branch with latest main:**
```bash
git checkout main
git pull
git checkout fix/http-router-bug
git merge main
git push
```

**View your changes vs main:**
```bash
git diff main
```

**View commits in your branch:**
```bash
git log --oneline main..HEAD
```

**Clean up local branch after merge:**
```bash
git checkout main
git pull
git branch -d fix/http-router-bug
```

### Resources

- [Contributing Guide](https://github.com/envoyproxy/envoy/blob/main/CONTRIBUTING.md) - Full contribution guidelines
- [Code Review Policy](https://github.com/envoyproxy/envoy/blob/main/CONTRIBUTING.md#pr-review-policy-for-maintainers)
- [API Review Checklist](https://github.com/envoyproxy/envoy/blob/main/api/review_checklist.md) - For API changes
- [Extension Policy](https://github.com/envoyproxy/envoy/blob/main/EXTENSION_POLICY.md) - For new extensions
- [OWNERS.md](https://github.com/envoyproxy/envoy/blob/main/OWNERS.md) - Maintainers and domain experts
- [Mailing list](https://groups.google.com/forum/#!forum/envoy-dev) - envoy-dev for questions

---

## Additional Resources

### Testing Frameworks
- [Google Test Documentation](https://github.com/google/googletest)
- [Integration Test Framework](https://github.com/envoyproxy/envoy/blob/main/test/integration/README.md)
- [Custom Test Matchers](https://github.com/envoyproxy/envoy/blob/main/test/README.md)

### Build and Dependency Management
- [Bazel Configuration](bazel/README.md)
- [External Dependencies](bazel/EXTERNAL_DEPS.md)
- [Dependency Policy](DEPENDENCY_POLICY.md)

### Documentation
- [Official Documentation](https://www.envoyproxy.io/docs/envoy/latest/)
- [Envoy Architecture](https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/arch_overview)
- [Repository Layout](REPO_LAYOUT.md)

### Development Tools
- [VSCode Setup](tools/vscode/README.md)
- [Docker for Development](ci/README.md)
- [Performance Testing](bazel/PPROF.md)
- [Symbol Resolution](bazel/README.md#stack-trace-symbol-resolution)

### Community
- [envoy-dev mailing list](https://groups.google.com/forum/#!forum/envoy-dev)
- [envoy-announce mailing list](https://groups.google.com/forum/#!forum/envoy-announce)
- [Slack Channel](https://envoyproxy.slack.com/)
