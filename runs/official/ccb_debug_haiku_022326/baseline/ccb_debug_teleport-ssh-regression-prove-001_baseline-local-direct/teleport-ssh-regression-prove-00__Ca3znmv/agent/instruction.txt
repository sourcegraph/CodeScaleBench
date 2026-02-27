# Bug Investigation: Multi-Device U2F Authentication Limited to Single Token

**Repository:** gravitational/teleport
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

Users who have registered multiple U2F hardware tokens with Teleport report that during login, only one of their registered devices is recognized. The authentication flow presents a challenge for only a single device, preventing users from selecting which hardware token to use.

Specifically:

1. **Single-device lock-in**: After registering multiple U2F tokens via the MFA management flow, attempting to log in only issues a challenge for one device. The system should present challenges for all registered tokens so the user can tap whichever device is available.

2. **MFA device management gaps**: Operations for adding, listing, and removing MFA devices (both U2F and TOTP) do not correctly handle the transition from single-device to multi-device authentication. For example, deleting one device when multiple are registered may behave unexpectedly.

3. **Client/server version compatibility**: Older clients connecting to a newer server (and vice versa) may fail to negotiate the correct U2F challenge format, causing authentication errors during version upgrades.

## Your Task

1. Investigate the codebase to find the root cause of these multi-device U2F authentication limitations
2. Write a regression test as a single file at `/workspace/regression_test.go`
3. Your test must be self-contained and runnable with `go test -run TestRegression -v -timeout 60s /workspace/regression_test.go`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should cover at least: multi-device U2F challenge generation and client/server compatibility
- Test timeout: 60 seconds
