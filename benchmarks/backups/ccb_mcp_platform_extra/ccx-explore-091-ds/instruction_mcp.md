# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/etcd-io-etcd` — use `repo:^github.com/sg-evals/etcd-io-etcd$` filter
- `github.com/sg-evals/kubernetes-api` — use `repo:^github.com/sg-evals/kubernetes-api$` filter
- `github.com/sg-evals/kubernetes-client-go` — use `repo:^github.com/sg-evals/kubernetes-client-go$` filter
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

**Sourcegraph Repositories:** `github.com/sg-evals/etcd-io-etcd`, `github.com/sg-evals/kubernetes-api`, `github.com/sg-evals/kubernetes-client-go`, `github.com/sg-evals/kubernetes-kubernetes`

# Service Deployment Pattern Discovery

## Your Task

You are a platform engineer onboarding new service teams to the Kubernetes ecosystem.
You need to identify and document **the canonical patterns for deploying new services**
and how these patterns are defined and documented across the Kubernetes repos.

**Your question**: Find the canonical patterns for deploying new services and how
they are documented across repos. Specifically:

1. **API type definition** — Where is the authoritative `Deployment` struct defined
   in the Kubernetes API types repo? Identify the file and the struct name.
2. **Client-side code pattern** — Where is the canonical Go code example showing
   how to create a Deployment using the client library? Identify the file with the
   programmatic create pattern.
3. **Developer documentation** — Where is the README or documentation file that
   explains the deployment workflow (Create, Update, List, Delete)?

For each, cite the specific repository, file path, and the key type/function/document.

## Context

You are working with the Kubernetes ecosystem in a cross-org environment:

- `kubernetes/kubernetes` (core orchestrator)
- `sg-evals/kubernetes-client-go` (go-client-library)
- `sg-evals/kubernetes-api` (api-type-definitions)
- `etcd-io/etcd` (distributed-kv-store)

This question is specifically designed to benefit from cross-repo synthesis. The
deployment pattern spans the API types repo, the client library repo, and documentation
— none of which is fully visible from any single repo.

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "files": [
    {
      "repo": "sg-evals/kubernetes-api",
      "path": "relative/path/to/file.go",
      "description": "What this file contains and its role in the deployment pattern"
    }
  ],
  "text": "Comprehensive narrative explaining the canonical deployment patterns, citing specific files, types, and functions from each repo. Mention the deploymentsClient pattern, the Deployment struct with its replicas field, and the documented workflow."
}
```

**Important**: Use exact repo identifiers as they appear in Sourcegraph. The oracle expects entries for `sg-evals/kubernetes-api` (API type definitions) and `sg-evals/kubernetes-client-go` (client examples and docs). The `repo` field must match these exactly.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-evals/kubernetes-client-go`). Strip this prefix in your answer — use `sg-evals/kubernetes-client-go`, NOT `github.com/sg-evals/kubernetes-client-go`.

The `files` list should include at least 3 files across 2+ repos that together define
the canonical service deployment pattern.

## Evaluation

Your answer will be scored on:
- **File coverage**: Does the answer identify the key files from the API types repo and client-go examples?
- **Keyword accuracy**: Does your narrative mention `deploymentsClient`, `Deployment`, `replicas`, and `Create`?
- **Provenance**: Does your narrative reference the specific repos and file paths?
- **Synthesis quality** (supplementary): Does the explanation synthesize these into a cohesive deployment pattern a new team could follow?
