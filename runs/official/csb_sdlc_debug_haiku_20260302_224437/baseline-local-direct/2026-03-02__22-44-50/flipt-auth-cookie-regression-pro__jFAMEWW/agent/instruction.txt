# Bug Investigation: Authentication Fails for Browser Cookie-Based Tokens

**Repository:** flipt-io/flipt
**Task Type:** Find and Prove (write a regression test)

## Reported Issue

The authentication system in Flipt only accepts client tokens via the `Authorization` header using Bearer format. This prevents browser-based sessions from working, since browsers typically store authentication tokens in HTTP cookies.

Specifically:

1. **Cookie tokens rejected**: When a valid client token is stored in an HTTP cookie (under the key `flipt_client_token`), the authentication middleware does not extract or validate it. Requests that carry a valid token in a cookie but not in the Authorization header are rejected as unauthenticated.

2. **No server-level authentication bypass**: Certain internal servers (such as those handling delegated authentication flows) need to operate without authentication checks. There is currently no mechanism to configure the middleware to skip authentication for specific server instances, forcing all registered servers through the same authentication path regardless of their role.

## Your Task

1. Investigate the codebase to find the root cause of these authentication limitations
2. Write a regression test as a single file at `/workspace/regression_test.go`
3. Your test must be self-contained and runnable with `go test -run TestRegression -v -timeout 60s /workspace/regression_test.go`

## Constraints

- Do NOT fix the bug — only write a test that demonstrates it
- Your test must fail on the current (buggy) code for the RIGHT reason
- The test should cover at least: cookie-based token extraction failure and server skip behavior
- Test timeout: 60 seconds
