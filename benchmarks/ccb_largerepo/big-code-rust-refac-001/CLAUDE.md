# big-code-rust-refac-001: Rename SubtypePredicate to SubtypeRelation

This repository is large (~2.2M LOC). Use comprehensive search to find ALL references before making changes.

## Task Type: Cross-File Refactoring

Your goal is to rename the `SubtypePredicate` struct to `SubtypeRelation` and its fields `a`/`b` to `sub_ty`/`super_ty` across 9 compiler crates. Focus on:

1. **Complete identification**: Find ALL files that reference `SubtypePredicate` — the struct definition in `rustc_type_ir`, its mirror in `rustc_public`, type aliases in `rustc_middle`, and all usage sites across the compiler
2. **Dependency ordering**: Follow the crate DAG bottom-up: `rustc_type_ir` → `rustc_middle`/`rustc_next_trait_solver` → `rustc_infer`/`rustc_public` → `rustc_trait_selection` → `rustc_hir_typeck`
3. **Consistency**: Ensure no stale references to `SubtypePredicate`, `.a`, or `.b` remain
4. **Compilation**: The Rust compiler must still build after changes

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — why this file needs changes

## Dependency Chain
1. path/to/definition.ext (original definition)
2. path/to/user1.ext (direct reference)
3. path/to/user2.ext (transitive dependency)

## Code Changes
### path/to/file1.ext
\`\`\`diff
- old code
+ new code
\`\`\`

## Analysis
[Refactoring strategy and verification approach]
```

## Search Strategy

- Start with `compiler/rustc_type_ir/src/predicate.rs` — primary definition of `SubtypePredicate`
- Use `find_references` on `SubtypePredicate` to find ALL usages
- Check `compiler/rustc_type_ir/src/predicate_kind.rs` for the `PredicateKind::Subtype` variant
- Check `compiler/rustc_middle/src/ty/predicate.rs` for type aliases
- Search `compiler/rustc_infer/src/infer/` for construction and pattern-match sites
- Search `compiler/rustc_trait_selection/src/` for error reporting and solving uses
- Check `compiler/rustc_public/src/ty.rs` for the public API mirror
- After changes, grep for `SubtypePredicate` to verify no stale references remain
