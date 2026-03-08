# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

- `github.com/sg-evals/envoy--v1.33.0` — use `repo:^github.com/sg-evals/envoy--v1.33.0$` filter

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

**Sourcegraph Repositories:** `github.com/sg-evals/envoy--v1.33.0`

# Task: Rename ListenerManagerImpl to ListenerOrchestrator

## Objective
Rename `ListenerManagerImpl` to `ListenerOrchestrator` in Envoy to better
describe the class's role as an orchestrator of listener lifecycle operations.

## Requirements

1. **Rename the class definition**:
   - `class ListenerManagerImpl` → `class ListenerOrchestrator`
   - Update header file and implementation file

2. **Update all references** (20+ call sites):
   - Constructor calls
   - Type declarations and pointers
   - Test files
   - Factory registrations

3. **Update header guards and includes**

## Key Reference Files
- `source/common/listener_manager/listener_manager_impl.h` — class declaration
- `source/common/listener_manager/listener_manager_impl.cc` — implementation
- `source/server/server.h` — uses ListenerManagerImpl
- `test/common/listener_manager/listener_manager_impl_test.cc` — tests

## Success Criteria
- `class ListenerManagerImpl` no longer exists
- `class ListenerOrchestrator` exists
- 80%+ of references updated
- Tests still reference the class correctly
