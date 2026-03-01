# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/etcd-io-etcd` — use `repo:^github.com/sg-evals/etcd-io-etcd$` filter
- `github.com/sg-evals/grafana` — use `repo:^github.com/sg-evals/grafana$` filter
- `github.com/sg-evals/kubernetes-kubernetes` — use `repo:^github.com/sg-evals/kubernetes-kubernetes$` filter

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

**Sourcegraph Repositories:** `github.com/sg-evals/etcd-io-etcd`, `github.com/sg-evals/grafana`, `github.com/sg-evals/kubernetes-kubernetes`

# Authoritative Repo Identification for a Cross-Org Dependency

## Your Task

Your team is resolving a dependency conflict and needs to identify the authoritative
source of truth for a widely-used Go module. Multiple repos in your ecosystem vendor
or depend on `go.etcd.io/etcd/client/v3`, but only one GitHub repository contains
the **authoritative module declaration** for this package.

**Specific question**: Which GitHub repository (org/repo format) is the authoritative
source of truth for the Go module `go.etcd.io/etcd/client/v3`? Provide evidence by
identifying the exact file path that contains the `module go.etcd.io/etcd/client/v3`
declaration.

## Context

In Go, every module has a canonical `go.mod` file that declares the module path with
`module <path>`. The repo that declares `module go.etcd.io/etcd/client/v3` is the
authoritative source. Other repos may vendor or depend on it but are NOT the source
of truth.

The `kubernetes/kubernetes` repo vendors this module — you can
see this at `vendor/go.etcd.io/etcd/client/v3/`. However, this is a vendored copy,
not the authoritative source. Your task is to find where this module is authoritatively
maintained.

## Available Resources

Your ecosystem includes the following repositories:
- `kubernetes/kubernetes` at v1.32.0
- `etcd-io/etcd` at v3.5.17
- `grafana/grafana` at v11.4.0

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "text": "The authoritative source for go.etcd.io/etcd/client/v3 is the <org>/<repo> repository. The module declaration `module go.etcd.io/etcd/client/v3` is at <file_path> in the <org>/<repo> repository. Evidence: [cite the specific file and module declaration]."
}
```

## Evaluation

Your answer is evaluated on:
- **Keyword presence**: Does your answer contain the exact module declaration string `module go.etcd.io/etcd/client/v3`?
- **Provenance**: Does your answer correctly cite the authoritative repository (`etcd-io/etcd`) and the module declaration file (`client/v3/go.mod`)?
