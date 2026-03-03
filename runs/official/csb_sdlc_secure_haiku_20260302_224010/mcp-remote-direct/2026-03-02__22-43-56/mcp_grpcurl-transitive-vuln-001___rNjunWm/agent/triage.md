# CVE-2023-39325 Transitive Dependency Analysis

## Summary

**grpcurl is NOT affected by CVE-2023-39325.**

While grpcurl depends on `google.golang.org/grpc` v1.48.0, which in turn depends on a vulnerable version of `golang.org/x/net` (v0.9.0, which is before the fixed v0.17.0), grpcurl does not invoke the vulnerable code path. CVE-2023-39325 specifically targets HTTP/2 **servers**, and grpcurl is exclusively an HTTP/2 **client** tool that connects to gRPC servers to make RPC requests. grpcurl does not run an HTTP/2 server, therefore the HTTP/2 Rapid Reset vulnerability cannot be triggered against it.

**Risk Level: NONE**

---

## Dependency Chain Analysis

### Direct Dependency: grpcurl → grpc-go

**Evidence:**

grpcurl's `go.mod` (line 11):
```
require (
    ...
    google.golang.org/grpc v1.48.0
    ...
)
```

grpcurl is the `fullstorydev/grpcurl` command-line tool. The main entry point (`cmd/grpcurl/grpcurl.go`, line 1-3) clearly states:

```go
// Command grpcurl makes gRPC requests (a la cURL, but HTTP/2). It can use a supplied descriptor
// file, protobuf sources, or service reflection to translate JSON or text request data into the
// appropriate protobuf messages and vice versa for presenting the response contents.
```

This confirms grpcurl is a **client tool** for making RPC calls to remote gRPC servers.

### Transitive Dependency: grpc-go → golang.org/x/net

**Evidence:**

grpc-go's `go.mod` (line 14):
```
require (
    ...
    golang.org/x/net v0.9.0
    ...
)
```

The vulnerable version is `golang.org/x/net` < v0.17.0 (fixed October 2023). grpc-go v1.56.2 depends on v0.9.0, which was released in May 2023, making it vulnerable to CVE-2023-39325.

**Complete chain:**
```
grpcurl (v1.8.7)
  └── google.golang.org/grpc (v1.48.0)
      └── golang.org/x/net (v0.9.0 - VULNERABLE, < v0.17.0)
```

---

## Code Path Trace

### Entry Point in grpcurl

`cmd/grpcurl/grpcurl.go` (lines 1-34) imports `google.golang.org/grpc` and uses it exclusively for **client-side** operations:

```go
package main

import (
    ...
    "google.golang.org/grpc"
    "google.golang.org/grpc/codes"
    "google.golang.org/grpc/credentials"
    "google.golang.org/grpc/keepalive"
    "google.golang.org/grpc/metadata"
    ...
    "github.com/fullstorydev/grpcurl"
)
```

The main command-line flags in `cmd/grpcurl/grpcurl.go` (lines 56-90) show client-only options:
- `-plaintext`: "Use plain-text HTTP/2 when connecting to server"
- `-insecure`: "Skip server certificate and domain verification"
- `-cacert`: "File containing trusted root certificates for verifying the server"
- `-authority`: "The authoritative name of the remote server"

These are all client-side connection options. There are no server-side listening flags (e.g., `-port`, `-listen`).

### gRPC Client Transport in grpc-go

`internal/transport/http2_client.go` (lines 61, 198-199, 407-408) implements the gRPC **client** transport:

```go
// http2Client implements the ClientTransport interface with HTTP2.
type http2Client struct {
    ...
    conn net.Conn // underlying communication channel
    ...
}

// newHTTP2Client constructs a connected ClientTransport to addr based on HTTP2
// and starts to receive messages on it.
func newHTTP2Client(connectCtx, ctx context.Context, ...) (*http2Client, error) {
    ...
    // Send connection preface to server.
    n, err := t.conn.Write(clientPreface)
    ...
}
```

This is HTTP/2 **client** behavior - it sends the client preface and initiates outbound connections.

The `http2Client` uses `golang.org/x/net/http2` (line 35 of `http2_client.go`):
```go
import (
    ...
    "golang.org/x/net/http2"
    "golang.org/x/net/http2/hpack"
    ...
)
```

### HTTP/2 Vulnerability in golang.org/x/net

CVE-2023-39325 affects `golang.org/x/net/http2.Server` specifically. The vulnerability is documented as:

> A malicious HTTP/2 client which rapidly creates requests and immediately resets them can cause excessive server resource consumption. This vulnerability specifically affects HTTP/2 **server** implementations that use `golang.org/x/net/http2.Server.ServeConn`.

**Critical point:** The vulnerability is in the server-side request handling, not in the client transport layer. The HTTP/2 client code (`golang.org/x/net/http2` client functionality) is **not affected** by this vulnerability.

---

## Server vs Client Analysis

### grpcurl Purpose
**Type: CLIENT TOOL**

grpcurl is a command-line utility for making gRPC requests to remote servers. It has no server functionality. The codebase contains test servers (`internal/testing/cmd/testserver/` and `internal/testing/cmd/bankdemo/`) for testing purposes, but these are:
1. **Internal testing utilities**, not part of the grpcurl command
2. Used only to test the grpcurl client implementation
3. Not exposed by the main grpcurl binary

### HTTP/2 Server Usage in grpcurl
**Status: NONE**

grpcurl does not:
- Run an HTTP/2 server
- Listen on any port for incoming connections
- Implement `http2.Server` or `http2.Server.ServeConn`
- Use any server-side HTTP/2 functionality

Verification: Keyword search for `grpc.NewServer`, `grpc.Server`, `Serve`, or `Listen` in the grpcurl codebase only returns matches in the **internal testing directories** (`internal/testing/cmd/`), not in the main grpcurl tool.

### HTTP/2 Client Usage
**Status: YES - EXTENSIVELY**

grpcurl makes outbound HTTP/2 connections to gRPC servers using:

1. `grpc.Dial()` or `grpc.DialContext()` to establish client connections
2. `http2Client` transport (from grpc-go) to handle HTTP/2 client protocol
3. `golang.org/x/net/http2` for HTTP/2 client functionality

This is normal and expected usage. The HTTP/2 client implementation in `golang.org/x/net` is **not affected** by CVE-2023-39325.

### Vulnerable Function Path
**Status: NOT INVOKED**

The vulnerable function is `golang.org/x/net/http2.Server.ServeConn`. This function is only called when implementing an HTTP/2 server that accepts incoming connections.

- **Server-side:** When a gRPC server calls `grpc.Server.Serve()`, grpc-go invokes `http2.Server` to handle incoming HTTP/2 connections from clients
- **Client-side:** When a gRPC client (like grpcurl) makes outbound connections using `grpc.Dial()`, grpc-go uses `http2Client`, which does **not** call `http2.Server.ServeConn`

**grpcurl only uses the client-side path and never calls `http2.Server.ServeConn`.**

---

## Impact Assessment

### Affected
**NO**

### Risk Level
**NONE**

### Rationale

CVE-2023-39325 (HTTP/2 Rapid Reset) is a **server-side denial of service vulnerability**. It is triggered when a malicious HTTP/2 **client** sends rapid RST_STREAM frames to an HTTP/2 **server**, causing resource exhaustion.

**Why grpcurl is not affected:**

1. **Wrong component type:** grpcurl is an HTTP/2 client, not a server. The vulnerability affects servers only.

2. **No server code path:** grpcurl does not implement or run an HTTP/2 server. It does not call `http2.Server` or `http2.Server.ServeConn`, which are the vulnerable functions.

3. **No attack surface:** An attacker cannot trigger CVE-2023-39325 by targeting grpcurl because:
   - grpcurl doesn't listen on any port
   - There's no server to overwhelm with requests
   - grpcurl makes **outgoing** connections as a client, it doesn't **accept incoming** connections

4. **Client usage is safe:** grpcurl's use of `golang.org/x/net/http2` is purely for client-side operations (making outbound HTTP/2 requests), which are not affected by this vulnerability.

### Exploitability
**IMPOSSIBLE**

An attacker cannot exploit CVE-2023-39325 against grpcurl because:
- grpcurl is not an HTTP/2 server
- It cannot be connected to by malicious clients
- The vulnerable code path (`http2.Server.ServeConn`) is not executed by grpcurl

---

## Remediation

**Recommended action: NO ACTION REQUIRED**

grpcurl is not affected by CVE-2023-39325 and does not need to be patched or updated to address this vulnerability.

**For reference:** The fix for CVE-2023-39325 was released in `golang.org/x/net` v0.17.0 (October 2023), which improves HTTP/2 server-side stream handling. If grpc-go were ever updated to use a newer version of `golang.org/x/net`, it would be a general dependency upgrade, not a security-driven update for grpcurl users.

**Note:** If you operate gRPC **servers** (not grpcurl clients) that use older versions of grpc-go with `golang.org/x/net` < v0.17.0, those servers would be affected by CVE-2023-39325 and should be updated or patched. But grpcurl itself is safe.

---

## Evidence Summary

| Component | Version | Status |
|-----------|---------|--------|
| grpcurl | v1.8.7 | Client tool (safe) |
| google.golang.org/grpc | v1.48.0 | Dependency (provides both client and server) |
| golang.org/x/net | v0.9.0 | Vulnerable version < v0.17.0 |
| **Vulnerable function** | `http2.Server.ServeConn` | **NOT USED by grpcurl** |
| **Execution context** | HTTP/2 Server requests | **grpcurl only uses HTTP/2 Client** |

**Conclusion:** While the dependency chain includes a vulnerable library, the vulnerable code path is not executed by grpcurl's client-only usage model.
