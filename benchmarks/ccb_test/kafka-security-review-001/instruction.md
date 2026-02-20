# Code Review: Apache Kafka Security Defects

You are reviewing a pull request to the Apache Kafka project (`apache/kafka` tag 3.8.0). The PR modifies authentication and authorization logic in the security subsystem.

**Your task:** Find **all injected defects** in the modified code and propose fixes as unified diffs.

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

Create `/workspace/review.json` with this structure:

```json
[
  {
    "file": "clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java",
    "line": 123,
    "severity": "critical",
    "description": "Brief description of the defect",
    "fix_patch": "--- a/clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java\n+++ b/clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java\n@@ -120,5 +120,5 @@\n-    old line\n+    new line\n"
  }
]
```

Each entry must include:
- `file` — Relative path from repository root
- `line` — Approximate line number where the defect occurs
- `severity` — One of: `critical`, `high`, `medium`
- `description` — What the defect is and what impact it has
- `fix_patch` — Unified diff showing the proposed fix (use `--- a/` and `+++ b/` prefix format)

**Severity levels**: Use `critical` for authentication/authorization bypasses, `high` for credential validation weaknesses, `medium` for other security issues.

**Do NOT edit source files directly.** Express all fixes as unified diffs in your review report. The evaluation system will apply your patches and verify correctness.

## Evaluation

Your review will be evaluated on:
- **Detection accuracy** (50%): Precision and recall of reported defects
- **Fix quality** (50%): Whether your proposed patches correctly resolve the defects

## Constraints

- **Time limit**: 1200 seconds
- Do NOT edit source files directly — express fixes only in `fix_patch`
- Do NOT run tests — the evaluation system handles verification

## Notes

- The workspace contains the full Kafka 3.8.0 source tree
- All defects are realistic, subtle security bugs that could plausibly appear in code review
- Some defects may require understanding interactions between multiple files
- This is a **security-focused** review — prioritize finding all authentication and authorization defects
