# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/prometheus` — use `repo:^github.com/sg-evals/prometheus$` filter
- `github.com/sourcegraph-testing/prometheus-common` — use `repo:^github.com/sourcegraph-testing/prometheus-common$` filter

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

**Sourcegraph Repositories:** `github.com/sg-evals/prometheus`, `github.com/sourcegraph-testing/prometheus-common`

# Security Compliance Audit: TLS Configuration Across Prometheus Stack

## Your Task

For a security audit, prove that TLS is enforced on all external interfaces of the Prometheus monitoring stack. Find all Go source files in `prometheus/prometheus` that define, load, validate, or apply TLS configuration for: scrape targets, remote write/read endpoints, the web server, tracing exporters, and service discovery plugins.

**NOTE**: The canonical TLS config struct is defined in the `prometheus-common` library (available on Sourcegraph as `sourcegraph-testing/prometheus-common`). Include this definition file in your answer.

## Specific Files to Find

1. **TLS struct definition and factory function** (in prometheus-common)
2. **Config embedding** — where TLS is wired into scrape/remote/tracing configs
3. **Server-side TLS** — web server TLS setup
4. **Client-side TLS** — outbound connections: remote write, tracing, scrape, service discovery
5. **TLS validation** — promtool config validation

## Context

You are performing a compliance audit of the Prometheus monitoring stack. The goal is to verify that TLS is enforced on all external-facing interfaces. This requires tracing TLS configuration from its definition in the shared `prometheus-common` library through its embedding in Prometheus's own config, its application on the web server (server-side), its use in outbound connections (client-side), and its validation by the `promtool` CLI.

## Available Resources

Your ecosystem includes the following repositories:
- `prometheus/prometheus` at v3.2.1

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "files": [
    {"repo": "prometheus/prometheus", "path": "relative/path/to/file.go"},
    {"repo": "sourcegraph-testing/prometheus-common", "path": "relative/path/to/file.go"}
  ],
  "text": "Narrative explanation of the TLS architecture across the Prometheus stack."
}
```

**Important**: Use `"prometheus/prometheus"` or `"sourcegraph-testing/prometheus-common"` for repo names. Strip `github.com/` prefix.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/prometheus/prometheus`). Strip this prefix in your answer.

Include only the `files` field. Your answer is evaluated against a closed-world oracle — completeness matters.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find all relevant TLS configuration files across both repos?
- **Keyword presence**: Does your answer reference key TLS identifiers (TLSConfig, NewTLSConfig, ServeMultiple)?
- **Provenance**: Does your answer cite the correct repos and key file paths?
