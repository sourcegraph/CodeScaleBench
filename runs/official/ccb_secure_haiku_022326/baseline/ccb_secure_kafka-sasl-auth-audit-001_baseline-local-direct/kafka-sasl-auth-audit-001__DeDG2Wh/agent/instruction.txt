# big-code-kafka-sec-001: Kafka SASL Authentication Flow Security Analysis

## Task

Trace the Apache Kafka SASL authentication flow from channel creation through mechanism negotiation (PLAIN, SCRAM-SHA-256, OAUTHBEARER, GSSAPI), the challenge-response exchange, principal extraction, to ACL-based authorization. Identify all entry points where untrusted client data enters the SASL subsystem, map the data flow through each authentication mechanism, and analyze the security properties of the authentication and authorization chain.

## Context

- **Repository**: apache/kafka (Java, ~1.2M LOC)
- **Category**: Security Analysis
- **Difficulty**: hard
- **Subsystem Focus**: `clients/src/main/java/org/apache/kafka/common/security/` (authenticator, plain, scram, oauthbearer packages) and `clients/src/main/java/org/apache/kafka/common/network/` (channel builders)

## Requirements

1. Identify all entry points where untrusted data enters the SASL subsystem (client connections, SASL tokens, handshake requests)
2. Trace the channel builder architecture: how `ChannelBuilders` creates `SaslChannelBuilder` which wires up `SaslServerAuthenticator`
3. Map the SASL handshake protocol: `ApiVersionsRequest` -> `SaslHandshakeRequest` -> mechanism-specific exchange -> authenticated principal
4. Trace at least two mechanism implementations (PLAIN and SCRAM) through their callback handlers to credential verification
5. Identify how `KafkaPrincipal` is extracted post-authentication and how `Authorizer.authorize()` enforces ACLs
6. Document existing mitigations and where they may be insufficient

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file.ext — role in attack surface
...

## Entry Points
1. path/to/entry.ext:function_name — accepts [type of untrusted input]
...

## Data Flow
### Flow 1: [name]
1. Source: path/to/source.ext (untrusted input enters here)
2. Transform: path/to/transform.ext (data is [processed/validated/not validated])
3. Sink: path/to/sink.ext (sensitive operation: [db query/file write/exec/etc.])

## Dependency Chain
[Ordered list of files from entry to sink]

## Analysis
[Detailed security analysis including:
- Vulnerability class (injection, auth bypass, SSRF, etc.)
- Existing mitigations and their gaps
- Attack scenarios
- Recommended remediation]

## Summary
[Concise description of the vulnerability and its impact]
```

## Evaluation Criteria

- Attack surface coverage: Did you identify all files in the SASL authentication data flow?
- Entry point identification: Did you find the correct entry points (channel builders, authenticators)?
- Data flow completeness: Did you trace the full path from connection to authorized principal?
- Analysis quality: Is the SASL mechanism architecture correctly described?
