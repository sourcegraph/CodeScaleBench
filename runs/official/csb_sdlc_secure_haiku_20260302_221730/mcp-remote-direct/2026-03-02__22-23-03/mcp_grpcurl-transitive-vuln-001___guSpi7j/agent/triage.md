# CVE-2023-39325 Transitive Dependency Analysis

## Summary

**Is grpcurl affected by CVE-2023-39325?** **NO**

**Risk Level:** **NONE**

grpcurl is a command-line **client-only** tool that connects to and invokes RPCs on gRPC servers. While it has a transitive dependency on a vulnerable version of `golang.org/x/net`, the vulnerable code path (`http2.Server.ServeConn()`) is never executed by grpcurl because grpcurl never runs an HTTP/2 server. CVE-2023-39325 is a server-side vulnerability that requires accepting HTTP/2 connections from a malicious client, which is not possible with a client-only tool.

---

## Dependency Chain Analysis

### Direct Dependency: grpcurl → grpc-go

**Evidence:**

grpcurl's `go.mod` (github.com/sg-evals/grpcurl--25c896aa):
```go
require (
    google.golang.org/grpc v1.48.0
    ...
)
```

**Location:** `go.mod:11`

**Assessment:** ✅ Confirmed - grpcurl directly depends on google.golang.org/grpc

### Transitive Dependency: grpc-go → golang.org/x/net

**Evidence:**

grpc-go's `go.mod` (github.com/sg-evals/grpc-go--v1.56.2):
```go
require (
    ...
    golang.org/x/net v0.9.0
    ...
)
```

**Location:** `go.mod:14`

**Assessment:** ✅ Confirmed - grpc-go v1.56.2 depends on golang.org/x/net v0.9.0

**Vulnerability Status:** ⚠️ VULNERABLE - golang.org/x/net v0.9.0 (March 2023) is affected by CVE-2023-39325. The fix was released in v0.17.0 (October 2023).

---

## Code Path Trace

### Entry Point in grpcurl: Client Connection

**grpcurl Usage Pattern (cmd/grpcurl/grpcurl.go, lines 390-400):**
```go
dial := func() *grpc.ClientConn {
    dialTime := 10 * time.Second
    if *connectTimeout > 0 {
        dialTime = time.Duration(*connectTimeout * float64(time.Second))
    }
    ctx, cancel := context.WithTimeout(ctx, dialTime)
    defer cancel()
    var opts []grpc.DialOption
    ...
    return grpc.Dial(...)  // Creates client connection
}
```

**Location:** `cmd/grpcurl/grpcurl.go:391-400`

**Assessment:** ✅ grpcurl uses `grpc.Dial()` to create **client connections** to gRPC servers, not server connections.

### BlockingDial Function (grpcurl.go, line 611)

**Evidence:**
```go
// BlockingDial is a helper function to establish a client connection.
// It returns a *grpc.ClientConn if successful, or an error if the connection fails.
// connection will be insecure (plain-text).
func BlockingDial(ctx context.Context, network, address string, creds credentials.TransportCredentials, opts ...grpc.DialOption) (*grpc.ClientConn, error) {
```

**Location:** `grpcurl.go:611`

**Assessment:** ✅ grpcurl only creates **client connections** using BlockingDial

### gRPC Client Implementation in grpc-go

**http2Client Implementation (internal/transport/http2_client.go, line 35):**
```go
import (
    "golang.org/x/net/http2"
    ...
)

// http2Client implements the ClientTransport interface with HTTP2.
type http2Client struct {
    ...
    framer *framer
    ...
}
```

**Location:** `internal/transport/http2_client.go:35` and `:61-150`

**Assessment:** ✅ grpc-go's http2Client uses golang.org/x/net/http2 for HTTP/2 **client** operations

### HTTP/2 Server Implementation in grpc-go

**http2Server Implementation (internal/transport/http2_server.go, line 36):**
```go
import (
    ...
    "golang.org/x/net/http2"
    ...
)

// http2Server implements the ServerTransport interface with HTTP2.
type http2Server struct {
    ...
}
```

**Location:** `internal/transport/http2_server.go:36` and `:69-100`

**Assessment:** ⚠️ grpc-go includes an http2Server implementation that uses golang.org/x/net/http2 for **server** operations, but grpcurl never uses this.

---

## Server vs Client Analysis

### grpcurl Purpose

**From README.md:**
> "grpcurl is a command-line tool that lets you interact with gRPC servers. It's basically curl for gRPC servers."

**Assessment:** ✅ grpcurl is exclusively a **CLIENT** tool

### HTTP/2 Server Usage in grpcurl

**Search for `grpc.Server` usage in grpcurl:**

Results show `grpc.Server` only in:
1. **Test files** (`tls_settings_test.go`) - internal testing infrastructure, not production code
2. **Generated protobuf files** (`test.pb.go`, `bank.pb.go`) - just server registration function signatures
3. **Test/demo servers** (`testserver/testserver.go`, `bankdemo/main.go`) - these are standalone test servers, separate binaries from grpcurl

**Primary grpcurl code:** No usage of grpc.Server

**Assessment:** ✅ grpcurl does NOT run any HTTP/2 servers

### HTTP/2 Client Usage in grpcurl

**grpcurl Usage Pattern:**
1. Accepts user input (gRPC method, server address, request data)
2. Creates a **client connection** to the target gRPC server
3. Invokes RPC methods on that server
4. Displays responses

**Assessment:** ✅ grpcurl exclusively uses HTTP/2 **client** functionality via grpc-go's http2Client

### Vulnerable Function Path

**Vulnerable Function:** `golang.org/x/net/http2.Server.ServeConn()`

**Type:** **SERVER** function

**Trigger:** Accepts incoming HTTP/2 connections and processes frames

**grpcurl Usage:** ❌ NEVER CALLED

grpcurl never instantiates or calls `http2.Server.ServeConn()` because it never runs an HTTP/2 server.

---

## Impact Assessment

### Affected: **NO**

**Rationale:**

CVE-2023-39325 is a **server-side vulnerability** in the HTTP/2 protocol implementation. Specifically, it allows a malicious HTTP/2 **client** to cause excessive resource consumption on an HTTP/2 **server** by:

1. Rapidly creating requests
2. Immediately resetting them with RST_STREAM frames
3. Creating new requests while old ones are still executing

**grpcurl is a client tool** and never runs an HTTP/2 server. Therefore, it cannot be exploited by this vulnerability. The attack vector requires:
- An HTTP/2 server accepting connections
- Ability to send malicious RST_STREAM frames to the server
- Server processing of requests/streams

None of these conditions apply to grpcurl.

### Risk Level: **NONE**

**Exploitability:** An attacker **cannot** trigger CVE-2023-39325 against grpcurl because:

1. grpcurl never creates an HTTP/2 server
2. No server connection listeners exist
3. grpcurl never accepts incoming connections
4. The vulnerable `http2.Server.ServeConn()` is never called by grpcurl

### Dependency Status

While grpcurl transitively depends on golang.org/x/net v0.9.0, this is analogous to a client having a vulnerable library installed locally. The vulnerability is only exposed if the client:
- Runs an HTTP/2 server
- Accepts connections from untrusted sources

grpcurl does neither.

---

## Remediation

**Recommended Actions:** **No action required**

While a best-practice approach would be to upgrade dependencies, grpcurl is **not at risk** from CVE-2023-39325, so this upgrade is not a security necessity for this specific vulnerability.

**However, if grpc-go is upgraded to a version that depends on golang.org/x/net >= v0.17.0, grpcurl would benefit from:**
- Improved security posture (dependency hygiene)
- Access to bug fixes and performance improvements in the newer golang.org/x/net version
- Better alignment with security best practices

---

## Summary Table

| Aspect | Finding |
|--------|---------|
| **Vulnerable Package** | golang.org/x/net v0.9.0 |
| **Vulnerable Function** | http2.Server.ServeConn() |
| **Vulnerability Type** | Server-side DoS via HTTP/2 Rapid Reset |
| **Direct Dependency** | grpcurl → grpc-go ✅ |
| **Transitive Dependency** | grpc-go → golang.org/x/net v0.9.0 ✅ |
| **Grpcurl Architecture** | Client-only tool |
| **Server Functionality Used** | None |
| **Vulnerable Code Path Used** | No |
| **Affected by CVE-2023-39325** | **NO** |
| **Risk Level** | **NONE** |
| **Remediation Required** | No |
