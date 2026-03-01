# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/rust--01f6ddf7`
- Use `repo:^github.com/sg-evals/rust--01f6ddf7$` filter in keyword_search
- Use `github.com/sg-evals/rust--01f6ddf7` as the `repo` parameter for go_to_definition/find_references/read_file


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

# big-code-rust-refac-001: Rename SubtypePredicate to SubtypeRelation in the Rust Compiler

## Task

Rename the `SubtypePredicate` struct to `SubtypeRelation` and its fields `a`/`b` to `sub_ty`/`super_ty` throughout the Rust compiler. The current `SubtypePredicate<I: Interner>` struct in `compiler/rustc_type_ir/src/predicate.rs` uses opaque field names `a` and `b` for what are semantically the subtype and supertype in a subtype relation. This refactoring improves clarity across 9 compiler crates.

The refactoring includes:
1. Rename the struct `SubtypePredicate` to `SubtypeRelation` in both `rustc_type_ir` and `rustc_public`
2. Rename fields `a` to `sub_ty` and `b` to `super_ty`
3. Update all type aliases (`SubtypePredicate<'tcx>`, `PolySubtypePredicate<'tcx>`) in `rustc_middle`
4. Update all re-exports, imports, and `IrPrint` bounds
5. Update all construction sites (struct literal expressions) in `rustc_infer`, `rustc_type_ir`, `rustc_next_trait_solver`
6. Update all destructure/pattern-match sites across `rustc_hir_typeck`, `rustc_trait_selection`, `rustc_type_ir`, `rustc_infer`
7. Update the `PredicateKind::Subtype` variant's data type annotation

## Context

- **Repository**: github.com/sg-evals/rust--01f6ddf7 (mirror of rust-lang/rust) (Rust, ~2.2M LOC)
- **Category**: Cross-File Refactoring
- **Difficulty**: hard
- **Subsystem Focus**: compiler/rustc_type_ir, rustc_middle, rustc_infer, rustc_trait_selection, rustc_hir_typeck, rustc_next_trait_solver, rustc_public

## Requirements

1. Identify ALL files that need modification for this refactoring
2. Document the complete dependency chain showing why each file is affected (respect the crate DAG)
3. Implement the changes (or describe them precisely if the scope is too large)
4. Verify that no references to the old names remain

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — why this file needs changes
- path/to/file2.ext — why this file needs changes
...

## Dependency Chain
1. Definition: path/to/definition.ext (original definition)
2. Direct usage: path/to/user1.ext (imports/references the symbol)
3. Transitive: path/to/user2.ext (uses a type that depends on the symbol)
...

## Code Changes
### path/to/file1.ext
```diff
- old code
+ new code
```

### path/to/file2.ext
```diff
- old code
+ new code
```

## Analysis
[Explanation of the refactoring strategy, affected areas, and verification approach]
```

## Evaluation Criteria

- File coverage: Did you identify ALL files that need modification?
- Completeness: Were all references updated (no stale references)?
- Compilation: Does the code still compile after changes?
- Correctness: Do the changes preserve the intended behavior?
