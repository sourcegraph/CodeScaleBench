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

# Cross-Org Interface Implementation Discovery

## Your Task

Your platform team is conducting a cross-organization audit to find all implementations
of a core Kubernetes storage abstraction. The `k8s.io/apiserver/pkg/storage.Interface`
is the standard backend abstraction used by the Kubernetes API server — any project that
embeds a Kubernetes-compatible API layer must implement it.

**Specific question**: Find all Go source files across the repos in this ecosystem that
contain an explicit interface compliance check for `storage.Interface` using the
Go pattern `var _ storage.Interface = (*StructName)(nil)`. For each match, report
the repo, file path, and the struct name that implements the interface.

## Context

This pattern (`var _ InterfaceName = (*TypeName)(nil)`) is used in Go to verify at
compile time that a type implements an interface. Finding all such declarations across
repos from different organizations reveals who has independently implemented the same
storage abstraction — a key signal for platform compatibility audits.

The search should be **exhaustive across all repos in the ecosystem**, not just a
single repo. The interface is defined in the Kubernetes ecosystem but can be implemented
by projects from entirely different organizations.

## Available Resources

Your ecosystem includes the following repositories:
- `kubernetes/kubernetes` at v1.32.0
- `etcd-io/etcd` at v3.5.17
- `grafana/grafana` at v11.4.0

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "symbols": [
    {
      "repo": "kubernetes/kubernetes",
      "path": "relative/path/to/file.go",
      "symbol": "StructName"
    }
  ],
  "text": "Narrative explanation citing which repos and orgs implement storage.Interface and where."
}
```

**Important**: Use exact repo identifiers as they appear in Sourcegraph. The oracle expects entries for `kubernetes/kubernetes` and `grafana/grafana`. The `repo` field must match these exactly.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-evals/kubernetes-client-go`). Strip this prefix in your answer — use `sg-evals/kubernetes-client-go`, NOT `github.com/sg-evals/kubernetes-client-go`.

## Evaluation

Your answer is evaluated on:
- **Symbol recall and precision**: Did you find all structs that explicitly implement `storage.Interface` via the `var _` pattern?
- The oracle expects implementations from at least 2 different GitHub organizations.
