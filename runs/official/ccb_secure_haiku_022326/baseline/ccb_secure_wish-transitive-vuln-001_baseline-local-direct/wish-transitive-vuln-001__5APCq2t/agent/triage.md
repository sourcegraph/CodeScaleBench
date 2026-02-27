# CVE-2024-45337 Transitive Dependency Analysis

## Summary

**Affected: YES**

The `charmbracelet/wish` v0.5.0 project **IS affected** by CVE-2024-45337, an authorization bypass vulnerability in `golang.org/x/crypto/ssh`.

The vulnerability exists in a transitive dependency chain:
```
charmbracelet/wish v0.5.0
  └── gliderlabs/ssh v0.3.4
        └── golang.org/x/crypto v0.0.0-20210616213533-5ff15b29337e (VULNERABLE - June 2021)
```

While `wish` also has a direct dependency on `golang.org/x/crypto v0.0.0-20220307211146` (March 2022, still vulnerable), the more critical issue is that `gliderlabs/ssh` brings in an **older vulnerable version**.

**Risk Level: MEDIUM-HIGH**

Applications using `wish` with public key authentication are vulnerable to authorization bypass attacks if they make assumptions about how the `PublicKeyCallback` is invoked.

---

## Dependency Chain Analysis

### Direct Dependency: wish → gliderlabs/ssh

**File**: `/workspace/wish/go.mod:9`

```
require (
    github.com/gliderlabs/ssh v0.3.4
)
```

**Evidence of usage**: `/workspace/wish/wish.go:8`
```go
import (
    "github.com/gliderlabs/ssh"
)
```

Wish imports `gliderlabs/ssh` and provides wrapper functions that expose public key authentication:
- `/workspace/wish/options.go:161-163` - `WithPublicKeyAuth()` function
- `/workspace/wish/options.go:73-88` - `WithAuthorizedKeys()` function
- `/workspace/wish/options.go:93-131` - `WithTrustedUserCAKeys()` function

### Transitive Dependency: gliderlabs/ssh → golang.org/x/crypto

**File**: `/workspace/ssh/go.mod:7`

```
require (
    golang.org/x/crypto v0.0.0-20210616213533-5ff15b29337e
)
```

**Commit date**: June 16, 2021 (BEFORE fix in v0.31.0 released December 2024)

**Import**: `/workspace/ssh/server.go:11`
```go
import (
    gossh "golang.org/x/crypto/ssh"
)
```

### Vulnerable Code Usage

The vulnerable `PublicKeyCallback` is directly exposed in `/workspace/ssh/server.go:144-153`:

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

This wrapper directly sets `golang.org/x/crypto/ssh.ServerConfig.PublicKeyCallback`, which is the vulnerable interface.

---

## Code Path Trace

### Entry Point in wish

**File**: `/workspace/wish/options.go:160-163`

```go
// WithPublicKeyAuth returns an ssh.Option that sets the public key auth handler.
func WithPublicKeyAuth(h ssh.PublicKeyHandler) ssh.Option {
    return ssh.PublicKeyAuth(h)
}
```

This function is used like this (from example at `/workspace/wish/examples/identity/main.go:26-28`):

```go
wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
    return true  // Accept all keys
})
```

Higher-level convenience functions also expose public key auth:
- `WithAuthorizedKeys()` at line 73-88
- `WithTrustedUserCAKeys()` at line 93-131

Both of these create a custom `PublicKeyHandler` that makes authorization decisions and call `WithPublicKeyAuth()`.

### Wrapper in gliderlabs/ssh

**File**: `/workspace/ssh/server.go:116-164`

The `Server.config()` method creates a `golang.org/x/crypto/ssh.ServerConfig` and sets up the callback:

```go
func (srv *Server) config(ctx Context) *gossh.ServerConfig {
    // ... create config ...
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
    return config
}
```

This creates the callback directly from the user-provided `PublicKeyHandler` without any additional validation or state management.

### Vulnerable Code in golang.org/x/crypto

**File**: `/workspace/crypto/ssh/server.go:488-573`

The vulnerability is in the `PublicKeyCallback` mechanism (lines 519-523):

```go
candidate, ok := cache.get(s.user, pubKeyData)
if !ok {
    candidate.user = s.user
    candidate.pubKeyData = pubKeyData
    candidate.perms, candidate.result = config.PublicKeyCallback(s, pubKey)  // CALLED HERE
    if candidate.result == nil && candidate.perms != nil && candidate.perms.CriticalOptions != nil && candidate.perms.CriticalOptions[sourceAddressCriticalOption] != "" {
        candidate.result = checkSourceAddress(
            s.RemoteAddr(),
            candidate.perms.CriticalOptions[sourceAddressCriticalOption])
    }
    cache.add(candidate)
}
```

**Key vulnerability points**:

1. **Multiple key queries**: The SSH protocol allows clients to query multiple public keys (RFC 4252 section 7) to see which ones are acceptable BEFORE proving control of the private key.

2. **Callback is called for each query**: The `PublicKeyCallback` is invoked for EACH key the client queries, not just the one they're actually authenticating with (lines 519-523).

3. **No state isolation**: Applications that store state in a closure or context during the callback (e.g., "this is the key the user authenticated with") will be wrong because:
   - A client might query Key A (callback called, returns OK)
   - Then query Key B (callback called, returns ERROR)
   - Then authenticate with Key A using `isQuery=false`

   The application might incorrectly believe Key B was used for authentication.

4. **Query vs. authentication distinction**: Lines 532-549 show the `isQuery` flag distinguishes between:
   - `isQuery=true`: Client is just asking if the key is acceptable (no authentication attempt)
   - `isQuery=false`: Client is actually attempting authentication with this key

   An application misusing the callback might not realize it's called for both queries and actual authentication attempts.

---

## Impact Assessment

### Affected: YES

**Evidence Summary**:
- ✅ wish imports gliderlabs/ssh (wish/go.mod:9)
- ✅ gliderlabs/ssh imports vulnerable golang.org/x/crypto v0.0.0-20210616213533-5ff15b29337e (ssh/go.mod:7)
- ✅ gliderlabs/ssh directly uses golang.org/x/crypto/ssh.ServerConfig.PublicKeyCallback (ssh/server.go:145)
- ✅ wish exposes public key authentication through WithPublicKeyAuth() and other functions (wish/options.go:160-163)
- ✅ The vulnerable callback is invoked for each key query, allowing authorization bypass

### Risk Level: MEDIUM-HIGH

**Reasoning**:
- **Severity**: The underlying CVE is CVSS 7.5 (Medium)
- **Exposure**: wish is a library for building SSH servers, so many applications could be affected
- **Exploitability**: Requires application-level misuse of the API, but this is a common mistake
- **Impact**: Authorization bypass could allow unauthorized access

### Exploitability: POSSIBLE BUT REQUIRES MISUSE

An attacker can exploit this vulnerability IF:

1. **The application makes state-dependent authorization decisions**: For example:

```go
var authenticatedKeyID string

wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
    authenticatedKeyID = key.Marshal() // WRONG: Gets set for every query!
    return isAuthorized(key)
})
```

2. **The application assumes the callback is only called once**: An application might track "which key the user authenticated with" by storing state in a closure:

```go
var lastCheckedKey ssh.PublicKey

wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
    lastCheckedKey = key  // WRONG: Could be ANY key the client queried, not the one authenticated
    // ... authorization logic ...
})
```

3. **The application makes decisions based on key order**: If an application processes keys in a specific order and makes assumptions based on that:

```go
keyOrder := 0
wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
    keyOrder++
    if keyOrder == 1 {
        // WRONG: Assumes first queried key is the authenticated one
        return true
    }
    return false
})
```

**Attack Scenario**:
1. Attacker has two keys: Key A (authorized) and Key B (not authorized)
2. Attacker attempts to connect and queries keys in order: B, A
3. Callback is called twice:
   - First for Key B (callback might set state/flag)
   - Then for Key A
4. Application's flawed authorization logic could incorrectly authenticate based on:
   - The state from the Key B query
   - Assuming Key A is "the authenticated key" based on order
   - Assuming the callback is only called once

### Mitigations in the Code

**Existing protections in golang.org/x/crypto**:
- Caching mechanism (lines 519-530): The callback result is cached, reducing redundant calls
- Signature verification (lines 552-569): Even if callback returns OK, the private key must be proven

**Existing protections in gliderlabs/ssh**:
- None specific to this vulnerability. The wrapper at `/workspace/ssh/server.go:145` directly exposes the vulnerable callback interface without additional validation.

**Existing protections in wish**:
- None specific to this vulnerability. Wish is a thin wrapper over gliderlabs/ssh.

---

## Remediation

### Immediate Actions (HIGH PRIORITY)

1. **Update golang.org/x/crypto to v0.31.0 or later**

   This contains the fix that clarifies the callback behavior and documentation.

   ```bash
   go get -u golang.org/x/crypto@v0.31.0
   ```

2. **Update gliderlabs/ssh to a version with crypto >= v0.31.0**

   Contact or check gliderlabs/ssh repository for updated version.
   - Currently using: v0.3.4
   - Status: Need to verify if newer version exists or if upstream is maintained

3. **Update charmbracelet/wish to depend on fixed versions**

   Once gliderlabs/ssh is fixed, update wish's dependencies.

### Application-Level Mitigations (CRITICAL)

For applications using wish with public key authentication:

1. **Do NOT store state in the callback**: Don't use closures to track which keys were queried

   ```go
   // WRONG
   lastKey := ""
   wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
       lastKey = key.String()  // This will be every queried key, not authenticated one
       return true
   })

   // CORRECT
   wish.WithPublicKeyAuth(func(ctx ssh.Context, key ssh.PublicKey) bool {
       return isAuthorizedKey(key)  // Stateless authorization check
   })
   ```

2. **Use the session context after authentication**: The authenticated key is available AFTER successful authentication via:

   ```go
   func handler(s ssh.Session) {
       // After authentication succeeds, the actual authenticated key is available
       auth := s.Context().Permissions()
       // Use the authenticated user info, not callback state
   }
   ```

3. **Assume the callback is called for every key query**: Design your authorization logic to handle:
   - Multiple callback invocations per authentication attempt
   - Queries vs. actual authentication attempts (this is transparent to the callback)

### Upstream Actions (FOR LIBRARY MAINTAINERS)

1. **Update dependencies**: Ensure both gliderlabs/ssh and wish update to crypto >= v0.31.0

2. **Document the vulnerability**: Add a security advisory to both projects

3. **Consider adding a wrapper**: gliderlabs/ssh could add an additional abstraction that makes the callback behavior clearer and prevents common misuses

---

## Conclusion

The `charmbracelet/wish` v0.5.0 project **IS vulnerable to CVE-2024-45337** through a transitive dependency on an outdated version of `golang.org/x/crypto/ssh`.

While the vulnerability itself is in the underlying SSH library, the exposure risk is MEDIUM-HIGH because:
- wish is used to build SSH servers
- Applications using wish's public key authentication could make authorization decisions incorrectly
- The vulnerable code path is directly used without additional safeguards

**Recommended action**: Update dependencies to golang.org/x/crypto >= v0.31.0 immediately and audit any code using `wish.WithPublicKeyAuth()` to ensure it doesn't misuse the callback as described in the exploitation scenarios above.
