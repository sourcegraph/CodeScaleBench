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

# Incident Debugging: Trace Production Error to Authoritative Source

## Incident Report

Your on-call pager just fired. Your Kubernetes cluster's watch stream is failing
with the following error appearing in the kube-apiserver logs:

```
rpc error: code = OutOfRange desc = etcdserver: mvcc: required revision has been compacted
```

The SRE team needs to file a bug report against the correct upstream component
and link to the exact source functions that generate this error.

## Your Task

Identify the **authoritative** Go source files in the **distributed etcd service**
that define and return the error string `"mvcc: required revision has been compacted"`.

Specifically, find:
1. The file where the `ErrCompacted` error variable is defined (not a vendor copy)
2. The file containing the core function `rangeKeys` that returns this error when
   a client requests a revision that has been garbage-collected by compaction

## Important: Avoiding Decoys

The `kubernetes/kubernetes` repository contains
vendored copies of etcd code under `vendor/go.etcd.io/etcd/`. These vendored
files look identical to the real source but are **not** the authoritative location.

The Kubernetes apiserver also has its own error-mapping layer at
`staging/src/k8s.io/apiserver/pkg/storage/etcd3/errors.go` that translates
the etcd error into Kubernetes error types — this is also **not** the authoritative
source of the original error.

Your answer must cite the **upstream etcd repository**, not the vendored copies
or the Kubernetes error-mapping layer.

## Available Resources

Your ecosystem includes the following repositories:
- `kubernetes/kubernetes` at v1.32.0
- `etcd-io/etcd` at v3.5.17 (this is where the error originates)

## Output Format

Create a file at `/workspace/answer.json` with your findings:

```json
{
  "files": [
    {
      "repo": "etcd-io/etcd",
      "path": "relative/path/to/file.go",
      "function": "FunctionName"
    }
  ],
  "text": "Narrative explaining: which repo and files contain the authoritative error definition and the function that returns it, and why the kubernetes/kubernetes vendored copies are NOT the correct answer."
}
```

**Important**: Use `etcd-io/etcd` as the exact `repo` identifier in your answer. The oracle checks for files `server/mvcc/kvstore.go` and `server/mvcc/kvstore_txn.go` in `etcd-io/etcd`. Do not cite vendored copies in `kubernetes/kubernetes`.
**Note**: Sourcegraph MCP tools return repo names with a `github.com/` prefix (e.g., `github.com/sg-evals/kubernetes-client-go`). Strip this prefix in your answer — use `sg-evals/kubernetes-client-go`, NOT `github.com/sg-evals/kubernetes-client-go`.

## Evaluation

Your answer will be scored on:
- **File recall and precision**: Did you find the two Go files in etcd-io/etcd that are the authoritative source (not vendor copies)?
- **Keyword coverage**: Does your answer mention the specific error constant (`ErrCompacted`) and function name (`rangeKeys`) by name?
