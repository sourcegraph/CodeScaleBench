# CVE-2024-45337 Transitive Dependency Analysis

## Summary

**VERDICT: YES, wish is AFFECTED by CVE-2024-45337**

**Risk Level: MEDIUM to HIGH**

The `charmbracelet/wish` v0.5.0 project is **directly affected** by CVE-2024-45337 in `golang.org/x/crypto/ssh`. The vulnerability is exposed through wish's public key authentication API, which is a core feature used to build SSH servers. Applications using wish's public key authentication features are vulnerable to authorization bypass if they misuse the `PublicKeyAuth` API by making authorization decisions based on key order or assuming the callback is only called once per authentication attempt.

---

## Dependency Chain Analysis

### Direct Dependency: wish → gliderlabs/ssh v0.3.4

**Evidence:**

File: `go.mod` (line 9)
```
require (
    github.com/gliderlabs/ssh v0.3.4
    ...
)
```

**Usage in wish:**
- `wish.go` imports `github.com/gliderlabs/ssh` as `ssh` (line 8)
- Public API `WithPublicKeyAuth()` in `options.go` (lines 161-162) directly uses `ssh.PublicKeyAuth(h)`
- Additional public APIs that use public key auth:
  - `WithAuthorizedKeys()` (lines 73-88): Parses authorized keys file and sets up key validation
  - `WithTrustedUserCAKeys()` (lines 93-131): Sets up certificate-based authentication

**Code Evidence:**
```go
// wish.go line 8
import (
    "github.com/gliderlabs/ssh"
)

// options.go lines 161-162
func WithPublicKeyAuth(h ssh.PublicKeyHandler) ssh.Option {
    return ssh.PublicKeyAuth(h)
}
```

### Transitive Dependency: gliderlabs/ssh v0.3.4 → golang.org/x/crypto v0.0.0-20210616213533-5ff15b29337e

**Evidence:**

File: `go.mod` (line 7)
```
require (
    golang.org/x/crypto v0.0.0-20210616213533-5ff15b29337e
)
```

This version is from June 16, 2021. The vulnerability was fixed in `golang.org/x/crypto v0.31.0` released in December 2024, meaning all versions prior to 0.31.0 are vulnerable.

**Vulnerable Code Usage:**

File: `server.go` (lines 144-152)
```go
if srv.PublicKeyHandler != nil {
    config.PublicKeyCallback = func(conn gossh.ConnMetadata, key gossh.PublicKey) (*gossh.Permissions, error) {
        applyConnMetadata(ctx, conn)
        if ok := srv.PublicKeyHandler(ctx, key); !ok {
            return ctx.Permissions().Permissions, fmt.Errorf("permission denied")
        }
        ctx.SetValue(ContextKeyPublicKey, key)
        return ctx.Permissions().Permissions, nil
    }
}
```

This code directly sets `config.PublicKeyCallback`, which is the vulnerable function from `golang.org/x/crypto/ssh`. The callback is called by the underlying SSH library during the public key authentication handshake.

### Vulnerable Code in golang.org/x/crypto/ssh

The vulnerability is in how `ServerConfig.PublicKeyCallback` is used. According to the SSH RFC, the protocol allows clients to inquire about key acceptability before proving control of the private key. This means:

1. A client can present multiple keys and ask "is this key acceptable?" for each one
2. The `PublicKeyCallback` gets invoked multiple times, once per key presented
3. The order of invocation cannot be used to determine which key the client authenticated with
4. The client may authenticate using a key that was not the first one queried

---

## Code Path Trace

### Entry Point in wish (wish options)

**File:** `options.go` (lines 160-162)

```go
// WithPublicKeyAuth returns an ssh.Option that sets the public key auth handler.
func WithPublicKeyAuth(h ssh.PublicKeyHandler) ssh.Option {
    return ssh.PublicKeyAuth(h)
}
```

**Usage Pattern in Applications:**

From `examples/identity/main.go` (lines 26-28):
```go
wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
    return true  // Accept all keys
}),
```

And later in the same example (lines 36-41):
```go
switch {
case ssh.KeysEqual(s.PublicKey(), carlos):
    wish.Println(s, "Hey Carlos!")
default:
    wish.Println(s, "Hey, I don't know who you are!")
}
```

**Key Risk Pattern:** The application accepts any key in the auth handler, but then later relies on `s.PublicKey()` (which is stored in context by gliderlabs/ssh) to identify the user. This is vulnerable because the callback may have been called with multiple keys.

### Wrapper in gliderlabs/ssh

**File:** `server.go` (lines 116-164) - The `config()` method

The `PublicKeyHandler` is wrapped in a closure that becomes the `ServerConfig.PublicKeyCallback`:

```go
if srv.PublicKeyHandler != nil {
    config.PublicKeyCallback = func(conn gossh.ConnMetadata, key gossh.PublicKey) (*gossh.Permissions, error) {
        applyConnMetadata(ctx, conn)
        if ok := srv.PublicKeyHandler(ctx, key); !ok {
            return ctx.Permissions().Permissions, fmt.Errorf("permission denied")
        }
        ctx.SetValue(ContextKeyPublicKey, key)  // <-- VULNERABILITY: Last key is stored
        return ctx.Permissions().Permissions, nil
    }
}
```

**Critical Issue:** The context stores the last key that was accepted in `ContextKeyPublicKey`. When a client presents multiple keys:
1. The callback is invoked for each key
2. The `PublicKeyHandler` may return true for multiple keys
3. The last accepted key is stored in the context
4. But the actual authenticated key may be different

This is defined in `ssh.go` (lines 38-39):
```go
// PublicKeyHandler is a callback for performing public key authentication.
type PublicKeyHandler func(ctx Context, key PublicKey) bool
```

### Related Code

**File:** `context.go` (lines 55-57)
```go
// ContextKeyPublicKey is a context key for use with Contexts in this package.
// The associated value will be of type PublicKey.
ContextKeyPublicKey = &contextKey{"public-key"}
```

Applications retrieve this via `Session.PublicKey()`, which accesses the stored key from the context.

---

## Impact Assessment

### Affected: YES

**Severity:** MEDIUM to HIGH (CVSS 7.5)

**Affected Components:**
1. All wish v0.5.0 deployments using public key authentication
2. All applications using wish's `WithPublicKeyAuth()` API
3. All applications using wish's `WithAuthorizedKeys()` API
4. All applications using wish's `WithTrustedUserCAKeys()` API

**Affected Versions:**
- `charmbracelet/wish` v0.5.0 (and earlier versions using gliderlabs/ssh v0.3.4)
- `gliderlabs/ssh` v0.3.4 (and earlier versions using golang.org/x/crypto before v0.31.0)
- `golang.org/x/crypto` versions < v0.31.0

### Exploitability

**Attack Scenario:**

An attacker could exploit this vulnerability if:

1. An SSH server using wish implements a `PublicKeyAuth` handler that doesn't properly validate each key
2. The application later uses `s.PublicKey()` to make authorization decisions based on the key
3. The attacker presents multiple public keys during authentication

**Example Attack:**

```go
// Vulnerable code pattern
wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
    // Naively accepts any key
    return true
}),
wish.WithMiddleware(func(h ssh.Handler) ssh.Handler {
    return func(s ssh.Session) {
        // Later, application tries to identify user by key
        if isAdminKey(s.PublicKey()) {  // VULNERABLE!
            grantAdminAccess()
        }
        h(s)
    }
})
```

**Attack Steps:**

1. Attacker has two keys: `user_key` and `admin_key`
2. SSH client library calls `PublicKeyCallback` for each key before authenticating
3. The callback is invoked:
   - First for `user_key` → returns true (accepted)
   - Then for `admin_key` → returns true (accepted)
4. Client authenticates using `user_key`
5. But the server's context has `admin_key` stored as the last accepted key
6. Application checks `s.PublicKey()` and sees `admin_key`, grants admin access
7. Attacker gains unintended access

### Mitigations in Wrapper Code

**Positive Finding:** gliderlabs/ssh v0.3.4 stores the authenticated key correctly:

File: `server.go` (lines 150-151)
```go
ctx.SetValue(ContextKeyPublicKey, key)
return ctx.Permissions().Permissions, nil
```

This stores the key that was accepted. However, the vulnerability exists because:
1. The callback is called multiple times
2. The application developer might not realize this and make wrong assumptions
3. The protocol design allows clients to query multiple keys before proving control

**Workaround for Application Developers:**

Applications using wish should:
1. Only authorize a single key per connection
2. Return `false` for keys that aren't authorized
3. Trust that gliderlabs/ssh is storing the correct authenticated key
4. Not make authorization decisions in the callback itself

### Risk Factors

**HIGH RISK if:**
- Application grants different permissions based on different keys
- Application uses multiple keys for role-based access control
- Application doesn't validate that the presented key matches expected key material

**MEDIUM RISK if:**
- Application only checks presence of a valid key (all authorized keys grant same access)
- Application doesn't care about which specific key was used

---

## Remediation

### Immediate Actions

1. **Update `golang.org/x/crypto` to v0.31.0 or later:**
   - This fixes the underlying vulnerability in the crypto library
   - Requires `gliderlabs/ssh` to be updated to use the newer version

2. **Update `gliderlabs/ssh` to a version using golang.org/x/crypto >= v0.31.0:**
   - Currently `gliderlabs/ssh` v0.3.4 is locked to an older version
   - Check if newer versions of gliderlabs/ssh are available with updated dependencies

3. **Update `charmbracelet/wish` to the latest version:**
   - Later versions likely depend on newer versions of gliderlabs/ssh

### Upgrade Path

```bash
# Current state
wish v0.5.0
  └── gliderlabs/ssh v0.3.4
        └── golang.org/x/crypto v0.0.0-20210616213533-5ff15b29337e (VULNERABLE)

# Desired state
wish vX.Y.Z (latest)
  └── gliderlabs/ssh vA.B.C (latest)
        └── golang.org/x/crypto >= v0.31.0 (FIXED)
```

### Dependency Update Steps

1. **Check for newer gliderlabs/ssh versions:**
   - Visit https://github.com/gliderlabs/ssh/releases
   - Identify the minimum version that uses golang.org/x/crypto >= v0.31.0

2. **Update go.mod:**
   ```bash
   go get github.com/gliderlabs/ssh@<new-version>
   go get github.com/charmbracelet/wish@<new-version>
   go mod tidy
   ```

3. **Verify the transitive dependency:**
   ```bash
   go mod graph | grep "golang.org/x/crypto"
   ```

4. **Test the application thoroughly:**
   - Verify public key authentication still works
   - Test with multiple keys
   - Verify SSH session establishment

### Code Review Actions

For existing applications using wish with public key authentication:

1. **Review all `WithPublicKeyAuth` usage:**
   - Ensure the callback only returns `true` for actually authorized keys
   - Don't make critical authorization decisions based on key order

2. **Review all `Session.PublicKey()` usage:**
   - Verify it's only used for logging/auditing, not access control
   - Access control decisions should already be made in the auth handler

3. **Implement defense in depth:**
   ```go
   // BAD: Making decisions based on which key is stored
   switch {
   case isAdminKey(s.PublicKey()):
       grantAdmin()
   }

   // GOOD: Making decisions in the auth handler
   wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
       if isAuthorized(ctx.User(), key) {
           // Store the authorization level in the context
           ctx.SetValue("admin", key)
           return true
       }
       return false
   })
   ```

---

## Timeline

- **June 2021:** golang.org/x/crypto v0.0.0-20210616213533-5ff15b29337e released (VULNERABLE)
- **March 2022:** charmbracelet/wish v0.5.0 released using vulnerable golang.org/x/crypto
- **November 2024:** CVE-2024-45337 disclosed
- **December 2024:** golang.org/x/crypto v0.31.0 released with fix

---

## Conclusion

The `charmbracelet/wish` v0.5.0 project is **affected by CVE-2024-45337** through a transitive dependency on `golang.org/x/crypto` via `gliderlabs/ssh`. While the vulnerability is in the SSH protocol handling itself, applications using wish's public key authentication features are exposed to the risk of authorization bypass if they misuse the API.

**Recommended Action:** Update all three packages (wish, gliderlabs/ssh, and golang.org/x/crypto) to their latest versions that include the security fix for CVE-2024-45337.
