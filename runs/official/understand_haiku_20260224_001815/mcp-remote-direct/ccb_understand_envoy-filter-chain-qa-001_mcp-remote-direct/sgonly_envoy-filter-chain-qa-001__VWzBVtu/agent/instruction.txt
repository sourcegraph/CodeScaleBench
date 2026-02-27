# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/envoy--d7809ba2`
- Use `repo:^github.com/sg-evals/envoy--d7809ba2$` filter in keyword_search
- Use `github.com/sg-evals/envoy--d7809ba2` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Architecture Q&A: Envoy HTTP Filter Chain

**Repository:** github.com/sg-evals/envoy--d7809ba2 (mirror of envoyproxy/envoy)
**Task Type:** Architecture Q&A (investigation only — no code changes)

## Background

Envoy is a high-performance service proxy that processes HTTP requests through a layered filter architecture. Understanding how a request flows from initial TCP accept through to the upstream server is fundamental to working with Envoy's codebase.

## Questions

Answer ALL of the following questions about Envoy's HTTP request processing pipeline:

### Q1: Listener to Connection Manager

When a downstream client opens a TCP connection to Envoy, how does the listener hand off the connection to the HTTP connection manager? Specifically:
- What mechanism selects which network filter chain to use for an incoming connection?
- How is the HTTP connection manager (`ConnectionManagerImpl`) installed as a network filter?
- What happens in `onData()` when the first bytes arrive?

### Q2: HTTP Filter Chain Creation and Iteration

Once HTTP request headers are parsed, how does Envoy build and iterate through the HTTP filter chain?
- At what point in request processing is the HTTP filter chain created?
- In what order are decoder filters invoked vs. encoder filters?
- What return values can a filter use to control iteration (stop, continue, buffer)?

### Q3: Router and Upstream

How does the router filter (the terminal HTTP filter) forward requests to upstream servers?
- How does the router obtain the target cluster and select a specific upstream host?
- What is the role of `UpstreamRequest` and the upstream filter chain?
- How does the response flow back through the filter chain to the downstream client?

### Q4: Architectural Boundaries

Explain the distinction between these two "filter chain" concepts in Envoy:
- The network-level filter chain (managed by `FilterChainManager`)
- The HTTP-level filter chain (managed by `FilterManager`)

Why are they separate, and how do they relate to each other?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Envoy HTTP Filter Chain Architecture

## Q1: Listener to Connection Manager
<answer with specific file paths, class names, and function references>

## Q2: HTTP Filter Chain Creation and Iteration
<answer with specific file paths, class names, and function references>

## Q3: Router and Upstream
<answer with specific file paths, class names, and function references>

## Q4: Architectural Boundaries
<answer with specific file paths, class names, and function references>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, classes, and functions — avoid vague or speculative answers
- Focus on the `source/common/http/`, `source/common/router/`, and `source/common/listener_manager/` directories
