# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/grpcurl--25c896aa` — use `repo:^github.com/sg-evals/grpcurl--25c896aa$` filter
- `github.com/sg-evals/grpc-go--v1.56.2` — use `repo:^github.com/sg-evals/grpc-go--v1.56.2$` filter

Scope ALL keyword_search/nls_search queries to these repos.
Use the repo name as the `repo` parameter for read_file/go_to_definition/find_references.


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

**Sourcegraph Repositories:** `github.com/sg-evals/grpcurl--25c896aa`, `github.com/sg-evals/grpc-go--v1.56.2`

# Security Triage: Transitive Dependency Vulnerability Assessment

## Objective

You are a security analyst reviewing a potential vulnerability in a Go project. Your task is to determine if the project is affected by a vulnerability in a transitive dependency and document the complete import chain.

## Context

**Project**: `fullstorydev/grpcurl` (v1.8.7) - A command-line tool for interacting with gRPC servers (like cURL, but for gRPC)

**Vulnerability**: CVE-2023-39325 in `golang.org/x/net/http2`

**CVE Summary**:
- **Severity**: High (CVSS 7.5)
- **Type**: Denial of Service via HTTP/2 Rapid Reset
- **Package**: `golang.org/x/net/http2`
- **Affected versions**: < v0.17.0
- **Fixed in**: v0.17.0 (October 2023)
- **Description**: A malicious HTTP/2 client which rapidly creates requests and immediately resets them can cause excessive server resource consumption. While the total number of requests is bounded by `http2.Server.MaxConcurrentStreams`, resetting an in-progress request allows the attacker to create a new request while the existing one is still executing. This vulnerability specifically affects HTTP/2 **server** implementations that use `golang.org/x/net/http2.Server.ServeConn`.

## The Dependency Chain

The `fullstorydev/grpcurl` project has the following dependency structure:

```
fullstorydev/grpcurl v1.8.7
  └── google.golang.org/grpc v1.56.2
        └── golang.org/x/net v0.14.0 (August 2023, VULNERABLE)
```

## Vulnerability Scope

**Vulnerable Symbol**: `golang.org/x/net/http2.Server.ServeConn`

**Important Context**: CVE-2023-39325 affects HTTP/2 **SERVER** implementations. It does **NOT** affect HTTP/2 **clients**. The vulnerability is triggered when a malicious client connects to an HTTP/2 server and sends rapid RST_STREAM frames.

## Repositories Available

You have access to three Git repositories in `/workspace`:

1. **grpcurl/** - The consuming project (`github.com/fullstorydev/grpcurl` at v1.8.7)
2. **grpc-go/** - The intermediate dependency (`google.golang.org/grpc` at v1.56.2)
3. **net/** - The vulnerable library (`golang.org/x/net` at v0.14.0, VULNERABLE version)

## Your Task

Analyze the code and provide a security triage report answering these questions:

1. **Is grpcurl affected by CVE-2023-39325?**
   - Does grpcurl use `google.golang.org/grpc`?
   - Does `grpc-go` use `golang.org/x/net/http2`?
   - Does grpcurl actually call the vulnerable code path (`http2.Server.ServeConn`)?
   - Or does it only use HTTP/2 **client** functionality?

2. **What is the complete import chain?**
   - Trace the dependency from grpcurl → grpc-go → golang.org/x/net
   - Identify the specific files and functions in grpcurl that use gRPC
   - Identify how grpc-go uses `golang.org/x/net/http2`
   - Determine if grpc-go uses `http2.Server` (server) or `http2.Transport` (client)

3. **What is the actual usage pattern?**
   - Is grpcurl a **client** tool or a **server**?
   - Does grpcurl run an HTTP/2 server, or does it only make HTTP/2 client requests?
   - Are there any server-side HTTP/2 code paths in grpcurl or grpc-go that would expose the vulnerability?

4. **Assessment**
   - Is the project affected? (YES/NO)
   - What is the risk level? (CRITICAL/HIGH/MEDIUM/LOW/NONE)
   - Why is it affected or not affected?

## Deliverable

Write your analysis to `/logs/agent/triage.md` with the following sections:

```
# CVE-2023-39325 Transitive Dependency Analysis

## Summary
[Brief summary: Is grpcurl affected? What's the verdict?]

## Dependency Chain Analysis

### Direct Dependency: grpcurl → grpc-go
[Evidence from grpcurl's go.mod and code that imports/uses grpc-go]

### Transitive Dependency: grpc-go → golang.org/x/net
[Evidence from grpc-go's go.mod and code that uses golang.org/x/net/http2]

### Vulnerable Code Usage Analysis
[Evidence of whether http2.Server.ServeConn or http2.Transport (client) is used]

## Code Path Trace

### Entry Point in grpcurl
[File and function in grpcurl that makes gRPC calls]

### gRPC Client in grpc-go
[How grpc-go implements gRPC client calls using HTTP/2]

### HTTP/2 Transport in golang.org/x/net
[Which HTTP/2 components are actually used: Server or Transport (client)?]

## Server vs Client Analysis

**grpcurl Purpose**: [Is it a client tool or server tool?]

**HTTP/2 Server Usage**: [Does grpcurl or grpc-go run an HTTP/2 server?]

**HTTP/2 Client Usage**: [Does grpcurl use HTTP/2 client to connect to gRPC servers?]

**Vulnerable Function Path**: [Is http2.Server.ServeConn called anywhere in the stack?]

## Impact Assessment

**Affected**: [YES/NO]

**Risk Level**: [CRITICAL/HIGH/MEDIUM/LOW/NONE]

**Rationale**: [Explain why the project is or is not affected based on client vs server usage]

**Exploitability**: [Can an attacker trigger CVE-2023-39325 against grpcurl?]

## Remediation

[Recommended actions: upgrade, accept risk, or no action needed]
```

## Important Notes

- This is an **analysis-only** task. Do NOT modify any code.
- Provide specific file paths, line numbers, and code snippets as evidence.
- The vulnerability is in a **transitive** dependency (grpcurl → grpc-go → x/net).
- Pay close attention to **client vs server** distinction: CVE-2023-39325 only affects **servers**.
- grpcurl is a **command-line tool** - think about what that means for server vs client usage.
- A project can have a vulnerable library in its dependency tree but still be NOT affected if it doesn't use the vulnerable code path.
