# Bug Investigation: Library Scanner Fails with Updated Trivy Components

**Repository:** future-architect/vuls
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

The vulnerability scanner's library detection subsystem is broken due to incompatible dependencies and missing package ecosystem support. Users report the following failures:

1. **Trivy DB client initialization fails**: The vulnerability database client creation call rejects the current arguments, causing library scanning to abort before any analysis begins. The upstream Trivy API has added a required parameter that the scanner does not provide.

2. **Missing package ecosystems**: Lockfiles for PNPM and .NET dependency formats are not recognized during library scans. Projects using these package managers have zero vulnerability findings despite having known vulnerable dependencies.

3. **Stale import paths**: The Trivy OS analyzer reference has moved to a new module location. The scanner still imports from the old location, which causes build failures when compiling against the current Trivy release.

4. **Incomplete scan scope control**: During library scans, non-application analyzers (OS packaging, secrets, licenses) may execute unnecessarily, producing noise in the results and slowing scans.

## Your Task

1. Investigate the codebase to find the root cause of these library scanning failures
2. Write a regression test as a single file at `/workspace/regression_test.go`
3. Your test must be self-contained and runnable with `go test -run TestRegression -v -timeout 60s /workspace/regression_test.go`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should cover at least: the Trivy DB client initialization failure and missing ecosystem detection
- Test timeout: 60 seconds
