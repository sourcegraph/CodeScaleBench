# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/envoy--1d0ba73a`
- Use `repo:^github.com/sg-evals/envoy--1d0ba73a$` filter in keyword_search
- Use `github.com/sg-evals/envoy--1d0ba73a` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Task: Generate Troubleshooting Runbook for Envoy Connection Pool Management

**Repository:** github.com/sg-evals/envoy--1d0ba73a (mirror of envoyproxy/envoy)
**Output:** Write your runbook to `/workspace/documentation.md`

## Objective

Produce a troubleshooting runbook for Envoy's connection pool management. Envoy's connection pools manage upstream HTTP/1.1, HTTP/2, and TCP connections, and are a common source of production issues.

## Scope

Explore the connection pool implementation:
- `source/common/http/conn_pool_base.cc` and `source/common/http/conn_pool_base.h`
- `source/common/tcp/conn_pool.cc`
- `source/common/upstream/cluster_manager_impl.cc` — how pools are managed per cluster

## Required Sections

Your runbook at `/workspace/documentation.md` must include:

### 1. Architecture Overview
- How connection pools are organized (per-cluster, per-thread)
- The lifecycle of a connection in the pool (connecting, active, draining)
- HTTP/1.1 vs HTTP/2 pool differences

### 2. Common Failure Scenarios
Describe at least 4 failure scenarios with:
- **Symptom**: What the operator observes (metrics, logs, errors)
- **Root Cause**: What code path leads to this behavior
- **Diagnostic Steps**: Specific Envoy admin API calls or config checks
- **Fix**: Configuration change or code-level explanation

Scenarios to cover (at minimum):
1. Connection pool exhaustion (pending requests overflow)
2. Upstream connection reset / premature close
3. Circuit breaker triggering unexpectedly
4. HTTP/2 GOAWAY causing request failures

### 3. Diagnostic Commands
- Envoy admin API endpoints useful for diagnosing pool issues (`/clusters`, `/stats`)
- Key metrics: `upstream_cx_*`, `upstream_rq_*`, `circuit_breakers.*`
- How to read Envoy's access logs for connection pool errors

### 4. Configuration Fixes
- `max_connections` and `max_pending_requests` tuning
- `connect_timeout` and `per_connection_buffer_limit_bytes`
- Circuit breaker thresholds

### 5. Code References
- Key source files and functions for each failure mode

## Quality Bar

- Metric names must match actual Envoy stats (verify in source or admin API docs)
- Diagnostic steps must be actionable (specific curl commands to admin API)
- Configuration fixes must reference actual Envoy config field names
