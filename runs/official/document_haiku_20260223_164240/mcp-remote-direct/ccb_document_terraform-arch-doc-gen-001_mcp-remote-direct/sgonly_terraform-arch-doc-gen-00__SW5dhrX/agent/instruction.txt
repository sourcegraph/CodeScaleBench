# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-benchmarks/terraform--7637a921` — use `repo:^github.com/sg-benchmarks/terraform--7637a921$` filter
- `github.com/sg-benchmarks/terraform--24236f4f` — use `repo:^github.com/sg-benchmarks/terraform--24236f4f$` filter

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

**Sourcegraph Repositories:** `github.com/sg-benchmarks/terraform--7637a921`, `github.com/sg-benchmarks/terraform--24236f4f`

# Task: Terraform Plan/Apply Pipeline Architecture Documentation

## Objective

Generate comprehensive architecture documentation for Terraform's plan/apply pipeline. Your documentation should explain how Terraform executes the plan and apply operations, covering the internal components and their interactions.

## Scope

Your documentation should cover the following architectural components:

1. **Graph Builder System**
   - How the dependency graph is constructed
   - The role of graph transformers in building the execution graph
   - How resources, providers, and modules are represented as graph nodes
   - How dependencies between resources are discovered and encoded as edges

2. **Provider Interface and Lifecycle**
   - How providers are initialized and managed during execution
   - The provider plugin architecture
   - How resource operations are delegated to providers
   - Provider configuration and instance management

3. **State Management**
   - How state is read, modified, and persisted during plan/apply
   - The role of state managers and state synchronization
   - How state snapshots enable concurrent graph evaluation
   - State locking and remote state backends

4. **Execution Flow and Hook System**
   - The overall execution flow from command invocation to completion
   - How graph nodes are evaluated (plan vs apply execution)
   - The walker pattern for graph traversal
   - Hook points for extending Terraform's behavior
   - Dynamic expansion for count/for_each resources

## Requirements

- **Component Responsibilities**: Clearly explain what each major component does
- **Data Flow**: Describe how data flows through the system during plan and apply operations
- **Extension Points**: Identify where the architecture allows for customization or extension
- **Error Handling**: Explain how errors are propagated and handled during execution

## Deliverable

Write your documentation to `/workspace/documentation.md` in Markdown format.

Your documentation should be technical and precise, aimed at developers who want to understand Terraform's internal architecture. Include specific details about component interactions, not just high-level descriptions.

## Success Criteria

Your documentation will be evaluated on:
- Coverage of all required architectural topics
- Accurate description of component responsibilities and interactions
- Clear explanation of data flow through the pipeline
- Identification of key extension points in the architecture
- Technical depth appropriate for internal architecture documentation
