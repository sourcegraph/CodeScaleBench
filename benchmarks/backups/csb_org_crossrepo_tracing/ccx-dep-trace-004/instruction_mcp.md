# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/grafana` — use `repo:^github.com/sg-evals/grafana$` filter
- `github.com/sg-evals/grafana-loki` — use `repo:^github.com/sg-evals/grafana-loki$` filter
- `github.com/sg-evals/grafana-mimir` — use `repo:^github.com/sg-evals/grafana-mimir$` filter

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

**Sourcegraph Repositories:** `github.com/sg-evals/grafana`, `github.com/sg-evals/grafana-loki`, `github.com/sg-evals/grafana-mimir`

# API Call Chain: Grafana to Loki Query Path

## Your Task

When Grafana executes a log query to a Loki datasource, it sends HTTP requests through a
specific code path. Your task is to trace the end-to-end call chain from the Grafana side
through to the Loki backend.

**Specific question**: Identify the key types/functions at each hop in this HTTP call chain:
1. In `grafana/grafana`: What is the type/struct that acts as the HTTP client for Loki queries?
   (Look in `pkg/tsdb/loki/`)
2. In `sg-evals/grafana-loki`: What is the function that parses incoming HTTP instant query
   requests? (Look in `pkg/loghttp/`)

Your answer should trace from Grafana's API layer → Loki's HTTP parsing layer.

## Context

You are working on a codebase task involving API call chain tracing across the Grafana
observability stack. Understanding the HTTP call path is important for debugging latency,
adding observability, or extending the query pipeline.

## Available Resources

Your ecosystem includes the following repositories:
- `grafana/grafana` at v11.4.0
- `grafana/loki` at v3.3.4

## Output Format

Create a file at `/workspace/answer.json` with your findings in the following structure:

```json
{
  "chain": [
    {"repo": "grafana/grafana", "path": "relative/path/to/file.go", "symbol": "TypeOrFunctionName"}
  ],
  "text": "Narrative explanation of the call chain, citing specific repos and file paths."
}
```

**Important**: Use exact repo identifiers as they appear in the oracle:
- For Grafana: `"repo": "grafana/grafana"`
- For Loki: `"repo": "sg-evals/grafana-loki"`
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-evals/kubernetes-client-go`). Strip this prefix in your answer — use `sg-evals/kubernetes-client-go`, NOT `github.com/sg-evals/kubernetes-client-go`.

The `grafana/loki` repository corresponds to `sg-evals/grafana-loki` in Sourcegraph.

List the chain steps in order from Grafana (caller) to Loki (callee). Your answer is evaluated
against a closed-world oracle — precision matters.

## Evaluation

Your answer will be scored on:
- **Dependency chain**: Did you trace the correct ordered call chain across repos?
- **Provenance**: Did you cite the correct file paths and repository names?
