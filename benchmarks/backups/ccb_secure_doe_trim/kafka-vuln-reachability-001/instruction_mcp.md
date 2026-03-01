# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/kafka--0cd95bc2`
- Use `repo:^github.com/sg-evals/kafka--0cd95bc2$` filter in keyword_search
- Use `github.com/sg-evals/kafka--0cd95bc2` as the `repo` parameter for go_to_definition/find_references/read_file


## Required Workflow

1. **Search first** — Use MCP tools to find relevant files and understand existing patterns
2. **Read remotely** — Use `sg_read_file` to read full file contents from Sourcegraph
3. **Edit locally** — Use Edit, Write, and Bash to create or modify files in your working directory
4. **Verify locally** — Run tests with Bash to check your changes

## Tool Selection

| Goal | Tool |
|------|------|
| Exact symbol/string | `sg_keyword_search` |
| Concepts/semantic search | `sg_nls_search` |
| Trace usage/callers | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Read full file | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

**Decision logic:**
1. Know the exact symbol? → `sg_keyword_search`
2. Know the concept, not the name? → `sg_nls_search`
3. Need definition of a symbol? → `sg_go_to_definition`
4. Need all callers/references? → `sg_find_references`
5. Need full file content? → `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search → read → references → definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms
- Read 2-3 related files before synthesising, rather than one at a time
- Don't read 20+ remote files without writing code — once you understand the pattern, start implementing

## If Stuck

If MCP search returns no results:
1. Broaden the search query (synonyms, partial identifiers)
2. Try `sg_nls_search` for semantic matching
3. Use `sg_list_files` to browse the directory structure
4. Use `sg_list_repos` to verify the repository name

---

**Sourcegraph Repository:** `github.com/sg-evals/kafka--0cd95bc2`

# Security Reachability Analysis: Apache Kafka SCRAM Authentication

## Objective

You are analyzing a potential vulnerability in Apache Kafka's SCRAM (Salted Challenge Response Authentication Mechanism) implementation. Your task is to trace the complete call path from network input to the nonce validation code and assess whether this vulnerability is exploitable from external network traffic.

## Background

Apache Kafka implements SASL/SCRAM authentication (RFC 5802) for client-broker authentication. The SCRAM protocol involves a multi-message exchange between client and server to establish authenticated sessions.

## Vulnerability Information

**Target Function:** `evaluateResponse()` in the `ScramSaslServer` class

**Location:** `clients/src/main/java/org/apache/kafka/common/security/scram/internals/ScramSaslServer.java`

**Issue:** The nonce validation logic in the SCRAM authentication exchange may not properly verify that the client nonce matches the server nonce according to RFC 5802 requirements.

## Your Task

Trace the complete call path to answer:

1. **Is the `evaluateResponse()` method reachable from external network input?**
   - What is the complete call chain from network socket to `evaluateResponse()`?
   - Which Kafka components handle SASL authentication requests?

2. **What triggers the nonce validation code path?**
   - What message type or authentication state triggers the vulnerable code?
   - What are the preconditions for reaching this code?

3. **Is this vulnerability exploitable?**
   - Can an unauthenticated external attacker reach this code?
   - What protocol messages must be sent to trigger the vulnerable path?
   - Are there any intermediate checks or guards that prevent exploitation?

4. **What is the attack surface?**
   - Which Kafka ports/listeners expose SASL/SCRAM authentication?
   - Can this be exploited over plaintext connections, TLS connections, or both?

## Required Analysis

Provide your analysis in `/logs/agent/triage.md` with the following sections:

### 1. Summary
Brief overview of the vulnerability and your reachability assessment.

### 2. Affected Code
- Identify the vulnerable function and file
- Explain the nonce validation issue
- Show the specific code that performs (or fails to perform) validation

### 3. Attack Path
- **Complete Call Chain:** Trace the path from network input to `evaluateResponse()`
  - Start from: Kafka broker network handling (SocketServer, Processor)
  - Through: SASL authentication layer
  - To: ScramSaslServer.evaluateResponse()
- **Authentication State Machine:** Explain the SCRAM protocol states and which state triggers nonce validation
- **Network Protocol:** What wire protocol messages reach this code?

### 4. Exploitability Assessment
- **Reachability:** YES/NO - Can external network traffic reach the vulnerable function?
- **Authentication Requirement:** Does the attacker need valid credentials?
- **Attack Scenario:** Describe a realistic attack scenario if exploitable
- **Mitigating Factors:** Identify any controls that limit exploitation (e.g., TLS requirement, rate limiting)

### 5. Severity Assessment
Rate the severity considering:
- Attack complexity
- Required privileges
- Scope of impact
- Affected deployments (plaintext vs TLS)

## Constraints

- You have access to the Apache Kafka source code at the vulnerable commit
- Use code search and call graph analysis to trace the complete path
- Do NOT provide fix code - this is analysis only
- Focus on reachability and exploitability, not on implementing patches

## Deliverable

Write your analysis to `/logs/agent/triage.md` in markdown format with the sections listed above.
