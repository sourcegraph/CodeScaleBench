# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/wish--v0.5.0` — use `repo:^github.com/sg-evals/wish--v0.5.0$` filter
- `github.com/sg-evals/ssh--v0.3.4` — use `repo:^github.com/sg-evals/ssh--v0.3.4$` filter

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

**Sourcegraph Repositories:** `github.com/sg-evals/wish--v0.5.0`, `github.com/sg-evals/ssh--v0.3.4`

# Security Triage: Transitive Dependency Vulnerability Assessment

## Objective

You are a security analyst reviewing a potential vulnerability in a Go project. Your task is to determine if the project is affected by a vulnerability in a transitive dependency and document the complete import chain.

## Context

**Project**: `charmbracelet/wish` (v0.5.0) - An SSH server library for building interactive terminal applications

**Vulnerability**: CVE-2024-45337 in `golang.org/x/crypto/ssh`

**CVE Summary**:
- **Severity**: Medium (CVSS 7.5)
- **Type**: Authorization Bypass
- **Package**: `golang.org/x/crypto/ssh`
- **Affected versions**: < v0.31.0
- **Fixed in**: v0.31.0 (December 2024)
- **Description**: Misuse of `ServerConfig.PublicKeyCallback` may cause authorization bypass. The SSH protocol allows clients to inquire about whether a public key is acceptable before proving control of the corresponding private key. `PublicKeyCallback` may be called with multiple keys, and the order in which the keys were provided cannot be used to infer which key the client successfully authenticated with. Applications that misuse this API by making authorization decisions based on key order or by assuming the callback is only called once per authentication attempt are vulnerable.

## The Dependency Chain

The `charmbracelet/wish` project has the following dependency structure:

```
charmbracelet/wish v0.5.0
  └── gliderlabs/ssh v0.3.4
        └── golang.org/x/crypto v0.0.0-20210616213533-5ff15b29337e (June 2021)
```

## Repositories Available

You have access to two Git repositories in `/workspace`:

1. **wish/** - The consuming project (`github.com/charmbracelet/wish` at v0.5.0)
2. **ssh/** - The intermediate dependency (`github.com/gliderlabs/ssh` at v0.3.4)
3. **crypto/** - The vulnerable library (`golang.org/x/crypto` at vulnerable commit)

## Your Task

Analyze the code and provide a security triage report answering these questions:

1. **Is wish affected by CVE-2024-45337?**
   - Does wish use `gliderlabs/ssh`?
   - Does `gliderlabs/ssh` use `golang.org/x/crypto/ssh`?
   - Does wish actually call the vulnerable code path (`PublicKeyCallback` or related functionality)?

2. **What is the complete import chain?**
   - Trace the dependency from wish → gliderlabs/ssh → golang.org/x/crypto
   - Identify the specific files and functions in wish that use public key authentication
   - Identify how gliderlabs/ssh wraps and uses `ServerConfig.PublicKeyCallback`

3. **How is the vulnerability exposed?**
   - What wish API functions expose the vulnerable code?
   - What would an application using wish need to do to trigger the vulnerability?
   - Are there any mitigations in the wrapper code?

4. **Assessment**
   - Is the project affected? (YES/NO)
   - What is the risk level? (CRITICAL/HIGH/MEDIUM/LOW)
   - What is the remediation path?

## Deliverable

Write your analysis to `/logs/agent/triage.md` with the following sections:

```
# CVE-2024-45337 Transitive Dependency Analysis

## Summary
[Brief summary: Is wish affected? What's the verdict?]

## Dependency Chain Analysis

### Direct Dependency: wish → gliderlabs/ssh
[Evidence from wish's go.mod and code that imports/uses gliderlabs/ssh]

### Transitive Dependency: gliderlabs/ssh → golang.org/x/crypto
[Evidence from gliderlabs/ssh's go.mod and code that uses golang.org/x/crypto/ssh]

### Vulnerable Code Usage
[Evidence that the vulnerable ServerConfig.PublicKeyCallback is actually used]

## Code Path Trace

### Entry Point in wish
[File and function in wish that provides public key auth functionality]

### Wrapper in gliderlabs/ssh
[How gliderlabs/ssh wraps and calls ServerConfig.PublicKeyCallback]

### Vulnerable Code in golang.org/x/crypto
[The actual vulnerable callback mechanism]

## Impact Assessment

**Affected**: [YES/NO]

**Risk Level**: [CRITICAL/HIGH/MEDIUM/LOW]

**Exploitability**: [Description of how an attacker could exploit this]

**Mitigations**: [Any existing mitigations in the code]

## Remediation

[Recommended actions to fix the vulnerability]
```

## Important Notes

- This is an **analysis-only** task. Do NOT modify any code.
- Provide specific file paths, line numbers, and code snippets as evidence.
- The vulnerability is in the **transitive** dependency, not the direct dependency.
- You must prove that wish is affected by showing the complete call chain.
- Consider both the dependency tree AND the actual code usage.
