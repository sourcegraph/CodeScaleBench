# Code Review: Apache Kafka Security Defects

You are reviewing a pull request to the Apache Kafka project (`apache/kafka` tag 3.8.0). The PR modifies authentication and authorization logic in the security subsystem.

**Your task:** Find and fix **all injected defects** in the modified code.

## Modified Files

The PR touches 4 files in the Kafka security subsystem:

1. `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java`
2. `clients/src/main/java/org/apache/kafka/common/security/authenticator/SaslServerAuthenticator.java`
3. `clients/src/main/java/org/apache/kafka/common/security/authenticator/CredentialCache.java`
4. `core/src/main/scala/kafka/security/authorizer/AclAuthorizer.scala`

These files handle SCRAM authentication, SASL server authentication, credential caching, and ACL-based authorization.

## What to Look For

Focus on security-critical defects including but not limited to:

- **Authentication bypass**: Missing or inverted credential validation checks
- **Authorization bypass**: Missing or inverted ACL permission checks
- **Credential validation**: Weakened iteration counts, disabled timing-attack protections
- **Token/session management**: Missing expiry checks, unsafe credential caching
- **Input validation**: Missing bounds checks, unsafe string comparisons

## Expected Output

1. **Code fixes**: Apply your fixes directly to the files in `/workspace`
2. **Review report**: Create `/workspace/review.json` with this structure:

```json
[
  {
    "file": "path/to/file.java",
    "line": 123,
    "severity": "critical",
    "description": "Brief description of the defect",
    "fix_applied": "Brief description of the fix"
  }
]
```

**Severity levels**: Use `critical` for authentication/authorization bypasses, `high` for credential validation weaknesses, `medium` for other security issues.

## Notes

- The workspace contains the full Kafka 3.8.0 source tree
- All defects are realistic, subtle security bugs that could plausibly appear in code review
- Some defects may require understanding interactions between multiple files
- This is a **security-focused** review — prioritize finding all authentication and authorization defects
