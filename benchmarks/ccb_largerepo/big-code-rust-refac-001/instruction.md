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

- **Repository**: rust-lang/rust (Rust, ~2.2M LOC)
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

```markdown
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
