# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/envoy--v1.31.2`
- Use `repo:^github.com/sg-evals/envoy--v1.31.2$` filter in keyword_search
- Use `github.com/sg-evals/envoy--v1.31.2` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Security Reachability Analysis: Envoy Admin Interface

## Scenario

You are performing a security audit of Envoy Proxy's administration interface. During static analysis, you identified a function with potentially dangerous operations:

**Function**: `AdminImpl::handlerDrainListeners()` in `source/server/admin/admin.cc`

This function handles the `/drain_listeners` endpoint, which forcibly drains all active listeners, closing existing connections and rejecting new ones. The implementation modifies critical server state and could be used for denial-of-service attacks.

## Your Task

Determine whether this function is **exploitable from external HTTP input** (i.e., from the internet-facing data plane). Specifically:

1. **Trace the call path**: Identify all code paths from external HTTP request reception to `handlerDrainListeners()`
2. **Identify protection mechanisms**: Is this endpoint restricted to specific network interfaces, ports, or authentication?
3. **Assess exploitability**: Can an external attacker reach this function? Or is it isolated to internal/admin-only access?
4. **Document the access control model**: What prevents external traffic from triggering admin endpoints?

## Codebase Context

- **Repository**: github.com/sg-evals/envoy--v1.31.2 (mirror of envoyproxy/envoy) @ v1.31.1
- **Language**: C++
- **Focus Area**: Admin interface architecture and access control

## Background: Admin Interface vs Data Plane

Envoy has two separate network interfaces:

1. **Data Plane** (e.g., port 8080): Processes customer/external HTTP traffic
   - Configured via `listeners` in envoy.yaml
   - Typically bound to 0.0.0.0 or public IP
   - Handles production traffic

2. **Admin Interface** (e.g., port 9901): Debug and management endpoints
   - Configured via `admin` section in envoy.yaml
   - Typically bound to 127.0.0.1 (localhost only)
   - NOT meant for external access

## Expected Deliverable

Write your analysis to `/logs/agent/triage.md`.

Include enough evidence to support your exploitability conclusion, including:
- the full call chain from request reception to the target handler
- the boundary between data-plane and admin-plane request handling
- the controls that prevent or permit external reachability
- the network/configuration conditions under which the endpoint would become externally reachable

## Important Notes

- Focus on **reachability analysis**, not on fixing the vulnerability
- Use static analysis and code review techniques
- Consider both HTTP/1.1 and HTTP/2 code paths
- Document your reasoning and evidence for each conclusion
- Be specific about validation checks (don't just say "input is validated" - cite the specific check and where it occurs)

## Success Criteria

Your analysis will be scored on:
- Correct identification of all call paths (25%)
- Accurate identification of protection mechanisms (30%)
- Correct exploitability assessment (25%)
- Quality of evidence and reasoning (20%)
