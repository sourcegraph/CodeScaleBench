# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/kafka--0753c489`
- Use `repo:^github.com/sg-evals/kafka--0753c489$` filter in keyword_search
- Use `github.com/sg-evals/kafka--0753c489` as the `repo` parameter for go_to_definition/find_references/read_file


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

# big-code-kafka-sec-001: Kafka SASL Authentication Flow Security Analysis

## Task

Trace the Apache Kafka SASL authentication flow from channel creation through mechanism negotiation (PLAIN, SCRAM-SHA-256, OAUTHBEARER, GSSAPI), the challenge-response exchange, principal extraction, to ACL-based authorization. Identify all entry points where untrusted client data enters the SASL subsystem, map the data flow through each authentication mechanism, and analyze the security properties of the authentication and authorization chain.

## Context

- **Repository**: github.com/sg-evals/kafka--0753c489 (mirror of apache/kafka) (Java, ~1.2M LOC)
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
