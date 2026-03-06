# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/TypeScript--v5.7.2`
- Use `repo:^github.com/sg-evals/TypeScript--v5.7.2$` filter in keyword_search
- Use `github.com/sg-evals/TypeScript--v5.7.2` as the `repo` parameter for go_to_definition/find_references/read_file


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

**Sourcegraph Repository:** `github.com/sg-evals/TypeScript--v5.7.2`

# Task: Security Review of TypeScript Type Narrowing

## Objective
Review the TypeScript compiler's type narrowing implementation for patterns that could lead to unsound type assertions, enabling developers to bypass type safety unknowingly.

## Steps
1. Find the type narrowing implementation in `src/compiler/checker.ts`
2. Identify the narrowing functions (narrowType, narrowTypeByGuard, narrowTypeByTypeof, etc.)
3. Analyze potential unsoundness in:
   - typeof narrowing with user-defined type guards
   - Discriminated union narrowing edge cases
   - Control flow analysis across function boundaries
   - Type assertion vs type narrowing interaction
4. Create `security_review.md` in `/workspace/` documenting:
   - Overview of the narrowing architecture (file paths and functions)
   - At least 3 patterns where narrowing could produce unsound types
   - TypeScript code examples demonstrating each pattern
   - Severity assessment for each finding
   - Recommendations for stricter narrowing

## Key Reference Files
- `src/compiler/checker.ts` — main type checker with narrowing
- `src/compiler/types.ts` — type system definitions
- `src/compiler/utilities.ts` — helper functions

## Success Criteria
- security_review.md exists
- Identifies specific narrowing functions
- Documents at least 3 unsound patterns
- Includes TypeScript code examples
