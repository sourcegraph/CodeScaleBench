# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/envoy--v1.32.1`
- Use `repo:^github.com/sg-evals/envoy--v1.32.1$` filter in keyword_search
- Use `github.com/sg-evals/envoy--v1.32.1` as the `repo` parameter for go_to_definition/find_references/read_file


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

**Sourcegraph Repository:** `github.com/sg-evals/envoy--v1.32.1`

# Team Handoff: Envoy ext_authz Filter

You are taking over ownership of the **ext_authz HTTP filter** from a departing team member. Your task is to produce a comprehensive handoff document that will help you (and future maintainers) understand this component.

## Context

The ext_authz filter is one of Envoy's authorization extensions. Your predecessor maintained it for the past year but is moving to a different project. You need to quickly build a working mental model of this component.

## Your Task

Explore the Envoy codebase and produce a handoff document at `/logs/agent/onboarding.md` covering the following sections:

### 1. Purpose
What does the ext_authz filter do? What problems does it solve? When would someone use it?

### 2. Dependencies
- **Upstream dependencies**: What other Envoy components or libraries does ext_authz depend on?
- **Downstream consumers**: What uses or integrates with ext_authz? How is it configured in Envoy's filter chain?

### 3. Relevant Components
List the most important source files for this filter. For each file, explain its role (e.g., "configuration parsing", "request handling", "gRPC client implementation").

### 4. Failure Modes
What can go wrong? What are common failure scenarios? How does the filter handle errors (e.g., authorization service unavailable, timeout, network failure)?

### 5. Testing
How is this filter tested? Where are the tests located? Are there integration tests, unit tests, or both?

### 6. Debugging
If something goes wrong with ext_authz in production, how would you debug it? What logs, metrics, or traces would you look at?

## Deliverable

Write your findings to `/logs/agent/onboarding.md` using the following structure:

```
# ext_authz Filter Handoff Document

## 1. Purpose
[Your findings here]

## 2. Dependencies
### Upstream Dependencies
[What ext_authz depends on]

### Downstream Consumers
[What depends on ext_authz]

## 3. Relevant Components
- **path/to/file.cc**: [Role/responsibility]
- **path/to/file.h**: [Role/responsibility]
...

## 4. Failure Modes
[Failure scenarios and error handling]

## 5. Testing
[Test locations, test types, how to run tests]

## 6. Debugging
[Debugging strategies, observability]
```

## Guidelines

- Be specific. Reference actual file paths, class names, function names.
- Focus on understanding the **system's behavior**, not just describing the code.
- This is analysis only — do not modify any code.
- Use code search and file exploration tools to explore the codebase efficiently.
