# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-benchmarks/envoy--1d0ba73a`
- Use `repo:^github.com/sg-benchmarks/envoy--1d0ba73a$` filter in keyword_search
- Use `github.com/sg-benchmarks/envoy--1d0ba73a` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Architecture Document: Envoy HTTP Connection Manager

**Repository:** github.com/sg-benchmarks/envoy--1d0ba73a (mirror of envoyproxy/envoy)
**Output:** Write your document to `/workspace/documentation.md`

## Task

Produce an architecture document for Envoy's **HTTP Connection Manager** (HCM) subsystem. The document must explain how the major components interact to process an HTTP request from arrival on a downstream connection through to upstream dispatch. Do not simply list APIs — explain the **design**, **data flow**, and **extension points**.

## Scope

Your document must cover these four components and how they work together:

### 1. ConnectionManagerImpl
The central network filter that owns the connection lifecycle. Explain:
- How it implements `Network::ReadFilter` to receive raw bytes
- How it creates and manages `ActiveStream` objects for each HTTP request
- Its role in codec creation (lazy codec instantiation for H1/H2 vs. H3)
- Connection-level concerns: drain decisions, overload management, watermark-based flow control

### 2. FilterManager and the HTTP Filter Chain
The per-stream filter chain execution engine. Explain:
- The decoder filter chain (request path) and encoder filter chain (response path)
- How `FilterChainFactory` creates filters for each stream
- Filter iteration: how `decodeHeaders`/`decodeData`/`decodeTrailers` propagate through decoder filters
- How filters can stop iteration, modify headers, or send local replies
- The distinction between `StreamDecoderFilter`, `StreamEncoderFilter`, and `StreamFilter` (dual)

### 3. Router Filter
The terminal decoder filter that forwards requests upstream. Explain:
- Route selection: how the router uses `RouteConfiguration` to pick a cluster
- How it obtains an HTTP connection pool from `ClusterManager`
- Upstream request lifecycle: `UpstreamRequest` creation, retry logic, timeout handling
- Shadow routing and hedged request support (if applicable)

### 4. Cluster Manager and Upstream Connectivity
The upstream connection pool and cluster management layer. Explain:
- How `ClusterManagerImpl` provides connection pools per cluster
- Load balancing: how the router obtains a host from the cluster's load balancer
- Connection pool mechanics: the relationship between logical connection pools and physical connections
- How health checking and outlier detection feed back into the load balancer

## Document Requirements

1. **Component Responsibilities** — what each component owns
2. **Data Flow** — the path of an HTTP request from downstream bytes to upstream dispatch, and the response path back
3. **Extension Points** — where users extend Envoy (HTTP filters, cluster extensions, load balancers, access loggers)
4. **Error Handling** — how errors at each stage (codec errors, filter errors, upstream failures) are handled
5. **relevant source files** — reference the actual source files in the envoyproxy/envoy repository

## Anti-Requirements

- Do NOT generate a simple API listing or header-file dump
- Do NOT fabricate class names or file paths that don't exist in the repository
- Do NOT cover Envoy components outside the HCM request path (e.g., xDS config delivery, listener management)
