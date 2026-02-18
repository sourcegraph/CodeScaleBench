# big-code-kafka-sec-001: Kafka SASL Authentication Flow

This repository is large (~1.2M LOC). Use targeted search to trace data flows from entry points to sensitive operations.

## Task Type: Security Analysis

Your goal is to analyze the Kafka SASL authentication subsystem for security properties by tracing data flow. Focus on:

1. **Entry point identification**: Find where untrusted client data enters the SASL authentication subsystem
2. **Data flow tracing**: Follow data through channel builders, SASL handshake, mechanism-specific exchanges, to authorization
3. **Mitigation assessment**: Identify existing security controls and their effectiveness
4. **Vulnerability classification**: Name specific vulnerability classes (auth bypass, credential leakage, ACL misconfiguration)

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — role in the attack surface

## Entry Points
1. path/to/entry.ext:function_name — accepts [type of untrusted input]

## Data Flow
### Flow 1: [name]
1. Source: path/to/source.ext (untrusted input enters)
2. Transform: path/to/transform.ext (data processed/validated)
3. Sink: path/to/sink.ext (sensitive operation)

## Dependency Chain
[Ordered list of files from entry to sink]

## Analysis
[Vulnerability class, existing mitigations, gaps, attack scenarios, remediation]

## Summary
[Concise vulnerability description and impact]
```

## Search Strategy

- Start in `clients/src/main/java/org/apache/kafka/common/network/SaslChannelBuilder.java`
- Trace authentication to `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java`
- Search for PLAIN mechanism in `clients/src/main/java/org/apache/kafka/common/security/plain/internals/`
- Search for SCRAM mechanism in `clients/src/main/java/org/apache/kafka/common/security/scram/internals/`
- Look for principal extraction in `DefaultKafkaPrincipalBuilder.java`
- Check authorization in `server/src/main/java/org/apache/kafka/server/authorizer/Authorizer.java`
- Use `find_references` to trace how `SaslServerAuthenticator.authenticate()` is called
