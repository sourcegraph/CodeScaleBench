# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/cilium--ad6b298d`
- Use `repo:^github.com/sg-evals/cilium--ad6b298d$` filter in keyword_search
- Use `github.com/sg-evals/cilium--ad6b298d` as the `repo` parameter for go_to_definition/find_references/read_file


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

**Sourcegraph Repository:** `github.com/sg-evals/cilium--ad6b298d`

# Task: Document Cilium eBPF Map API

## Objective

Generate comprehensive API reference documentation for Cilium's eBPF map API in the `pkg/bpf` package. The documentation should serve as a complete reference for developers working with eBPF maps in Cilium.

## Scope

Focus on the Go wrappers in `pkg/bpf` that provide user-space interaction with kernel eBPF maps. Document:

1. **Core Map Type and Creation**
   - `Map` struct and its primary methods
   - Map creation functions (`NewMap`, `OpenMap`, `OpenOrCreate`)
   - Map lifecycle operations (Open, Create, Close, Recreate)

2. **CRUD Operations**
   - Lookup, Update, Delete operations
   - Batch operations (BatchLookup, DeleteAll)
   - Per-CPU map operations
   - Locked operations (DeleteLocked)

3. **Iteration and Dumping**
   - Dump methods and callbacks
   - BatchIterator type and usage
   - DumpStats for tracking iteration

4. **Pinning and Persistence**
   - Pin/Unpin operations
   - BPF filesystem paths (BPFFSRoot, CiliumPath, MapPath)
   - Map persistence behavior

5. **Key/Value Interfaces**
   - MapKey, MapValue, MapPerCPUValue interfaces
   - EndpointKey as concrete example

6. **Event System**
   - Event types (MapUpdate, MapDelete)
   - DumpAndSubscribe for event streaming
   - Event callbacks and handles

7. **Collection Loading**
   - LoadCollection and LoadAndAssign functions
   - CollectionOptions

## Requirements

Your documentation must include:

1. **API Method Signatures**: Complete signatures with parameter types and return values
2. **Behavioral Semantics**:
   - When maps are pinned vs unpinned
   - Difference between Create() and CreateUnpinned()
   - OpenOrCreate() behavior on existing maps
   - How deletion works within DumpCallback (requires DeleteLocked)
   - Event subscription lifecycle
   - Batch iterator retry behavior on ENOSPC
3. **Usage Examples**: Code snippets showing:
   - Basic map creation and CRUD
   - Iteration with BatchIterator
   - Event subscription and cleanup
   - Pinning and unpinning maps
   - Real-world patterns from Cilium internals
4. **Documentation Structure**: Organize clearly with sections for each category above

## Deliverable

Write your documentation to `/workspace/documentation.md` in Markdown format.

## Constraints

- Do NOT include file paths or specific implementation locations in the documentation
- Focus on API contracts and behavior, not internal implementation details
- Include enough behavioral detail that users can correctly use the API without reading source code
- Provide accurate examples that would compile and work correctly
