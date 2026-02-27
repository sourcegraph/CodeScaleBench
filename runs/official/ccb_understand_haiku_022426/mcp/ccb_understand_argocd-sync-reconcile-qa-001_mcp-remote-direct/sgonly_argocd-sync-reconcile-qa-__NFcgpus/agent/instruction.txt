# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/argo-cd--206a6eec`
- Use `repo:^github.com/sg-evals/argo-cd--206a6eec$` filter in keyword_search
- Use `github.com/sg-evals/argo-cd--206a6eec` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Data Flow Q&A: Argo CD Sync Reconciliation

**Repository:** github.com/sg-evals/argo-cd--206a6eec (mirror of argoproj/argo-cd)
**Task Type:** Data Flow Q&A (investigation only — no code changes)

## Background

Argo CD is a declarative GitOps continuous delivery tool for Kubernetes. At its core is the sync reconciliation process, which continuously compares desired state (from Git) with live state (in the Kubernetes cluster) and applies changes to eliminate drift. Understanding this pipeline — from Git fetch through manifest generation, diff computation, and cluster synchronization — is essential for working with Argo CD's architecture.

## Task

Trace the complete data flow of how an Application resource is synchronized from initial detection of drift through to cluster state update. Identify every key transformation point, component boundary crossing, and data structure change.

## Questions

Answer ALL of the following questions about Argo CD's sync reconciliation pipeline:

### Q1: Reconciliation Triggering and Git Fetch

When the ApplicationController detects that an Application needs reconciliation, how does it request manifest generation?

- What triggers a reconciliation cycle (periodic refresh, resource change events, manual sync)?
- How does the ApplicationController communicate with the RepoServer to request manifest generation?
- What data structure is passed from controller to reposerver (request format)?
- How does the RepoServer fetch and cache the Git repository at the specified revision?

### Q2: Manifest Generation and Rendering

After the RepoServer fetches the Git repository, how are raw files transformed into Kubernetes manifests?

- How does `GenerateManifests()` identify which config management tool to use (Helm, Kustomize, CMP plugin)?
- What is the sequence of operations that renders raw manifests from the repository?
- What caching mechanisms exist for generated manifests, and what invalidates the cache?
- What data structure is returned from the RepoServer to the controller (response format)?

### Q3: Diff Computation Between Desired and Live State

Once manifests are generated, how does Argo CD compute the diff between desired (Git) and live (cluster) state?

- Which component is responsible for fetching live state from the Kubernetes cluster?
- How does the diff engine normalize resources before comparison?
- What are the different diff strategies (legacy 3-way, structured merge, server-side), and when is each used?
- What data structure represents the diff result, and how does it indicate out-of-sync resources?

### Q4: Sync Operation Execution

When out-of-sync resources are detected, how does Argo CD apply changes to the cluster?

- How are sync phases (PreSync, Sync, PostSync) and waves orchestrated?
- What is the difference between client-side apply (kubectl apply) and server-side apply in Argo CD?
- How does Argo CD determine the order in which resources are applied?
- How is sync status tracked and propagated back to the Application resource status?

## Output Requirements

Write your answer to `/logs/agent/investigation.md` with the following structure:

```
# Argo CD Sync Reconciliation Pipeline

## Q1: Reconciliation Triggering and Git Fetch
<answer with specific file paths, type/interface names, and method references>

## Q2: Manifest Generation and Rendering
<answer with specific file paths, type/interface names, and method references>

## Q3: Diff Computation Between Desired and Live State
<answer with specific file paths, type/interface names, and method references>

## Q4: Sync Operation Execution
<answer with specific file paths, type/interface names, and method references>

## Data Flow Summary
<ordered list of transformation points from Git fetch to cluster sync with data structures at each step>

## Evidence
<consolidated list of supporting file paths and line references>
```

## Constraints

- Do NOT modify any source files
- Cite specific files, packages, types, and methods — avoid vague or speculative answers
- Focus on the core sync reconciliation path, not error handling or edge cases
- Trace a standard automated sync with no special sync options or hooks
