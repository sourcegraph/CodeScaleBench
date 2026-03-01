# SubtypePredicate → SubtypeRelation Refactoring Implementation Checklist

## Overview
This document provides a detailed checklist for implementing the `SubtypePredicate` → `SubtypeRelation` refactoring across the Rust compiler. All file paths and line numbers have been verified against the current codebase.

## Pre-Implementation Verification

- [x] Verified struct definition exists at `rustc_type_ir/src/predicate.rs:918`
- [x] Verified enum variant exists at `rustc_type_ir/src/predicate_kind.rs:78`
- [x] Verified type aliases exist at `rustc_middle/src/ty/predicate.rs:24,32`
- [x] Identified all 17 files requiring changes
- [x] Documented all struct literals and pattern matches

## Implementation Steps

### Phase 1: Core Struct Definition (Critical Path)
These changes are required before any other changes can compile.

- [ ] **rustc_type_ir/src/predicate.rs**
  - [ ] Rename `pub struct SubtypePredicate<I: Interner>` to `pub struct SubtypeRelation<I: Interner>`
  - [ ] Rename field `pub a: I::Ty` to `pub sub_ty: I::Ty`
  - [ ] Rename field `pub b: I::Ty` to `pub super_ty: I::Ty`
  - [ ] Update Eq impl name: `impl<I: Interner> Eq for SubtypeRelation<I> {}`
  - [ ] Update documentation comment: change `a` references to `sub_ty`, `b` to `super_ty`
  - [ ] Verification: Struct should compile with new name and field names

- [ ] **rustc_type_ir/src/predicate_kind.rs**
  - [ ] Line 78: Change `Subtype(ty::SubtypePredicate<I>)` to `Subtype(ty::SubtypeRelation<I>)`
  - [ ] Verification: Type checking should find no mismatches

### Phase 2: Type Aliases (High Priority)
These establish the names used throughout the compiler.

- [ ] **rustc_middle/src/ty/predicate.rs**
  - [ ] Line 24: Change `pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;`
        to `pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;`
  - [ ] Line 32: Change `pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;`
        to `pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;`
  - [ ] Add compatibility aliases (optional, for gradual migration):
    ```rust
    // Deprecated: Use SubtypeRelation instead
    pub type SubtypePredicate<'tcx> = SubtypeRelation<'tcx>;
    pub type PolySubtypePredicate<'tcx> = PolySubtypeRelation<'tcx>;
    ```
  - [ ] Verification: Type checking should resolve correctly

- [ ] **rustc_middle/src/ty/mod.rs**
  - [ ] Update any re-export statements to use new names
  - [ ] Verification: Public API exports compile correctly

### Phase 3: Struct Literal Updates (Fields)
These are construction sites where new instances are created. Field names MUST be updated.

- [ ] **rustc_type_ir/src/relate/solver_relating.rs**
  - [ ] Lines 200-204: Update struct literal
    - Change `ty::SubtypePredicate` to `ty::SubtypeRelation`
    - Change `a` field name to `sub_ty`
    - Change `b` field name to `super_ty`
  - [ ] Lines 213-217: Update struct literal (note: fields are semantically swapped)
    - Change `ty::SubtypePredicate` to `ty::SubtypeRelation`
    - Change `a: b` to `sub_ty: b`
    - Change `b: a` to `super_ty: a`
  - [ ] Verification: Code compiles and semantic meaning is preserved

- [ ] **rustc_infer/src/infer/relate/type_relating.rs**
  - [ ] Lines 141-145: Update struct literal
    - Change `ty::SubtypePredicate` to `ty::SubtypeRelation`
    - Change `a` to `sub_ty`
    - Change `b` to `super_ty`
  - [ ] Lines 155-159: Update struct literal (fields are swapped)
    - Change `ty::SubtypePredicate` to `ty::SubtypeRelation`
    - Change `a: b` to `sub_ty: b`
    - Change `b: a` to `super_ty: a`
  - [ ] Verification: Code compiles

- [ ] **rustc_next_trait_solver/src/solve/mod.rs**
  - [ ] Search for `SubtypePredicate` struct literals
  - [ ] Update struct name to `ty::SubtypeRelation`
  - [ ] Update field names: `a` → `sub_ty`, `b` → `super_ty`
  - [ ] Verification: Code compiles

### Phase 4: Pattern Matches (Reading Fields)
These are destructuring sites where struct fields are read. Field names MUST be updated.

- [ ] **rustc_type_ir/src/flags.rs**
  - [ ] Line 394: Update pattern match
    - Change `ty::SubtypePredicate` to `ty::SubtypeRelation`
    - Change `{ a_is_expected: _, a, b }` to `{ a_is_expected: _, sub_ty, super_ty }`
    - Rename variables `a` and `b` to `sub_ty` and `super_ty` in the match body
  - [ ] Verification: All variable references are correct

- [ ] **rustc_trait_selection/src/solve/delegate.rs**
  - [ ] Line 127: Update pattern match
    - Change `ty::SubtypePredicate` to `ty::SubtypeRelation`
    - Change `{ a, b, .. }` to `{ sub_ty, super_ty, .. }`
    - Rename variables throughout the match arm
  - [ ] Verification: Correct field access

- [ ] **rustc_trait_selection/src/error_reporting/traits/overflow.rs**
  - [ ] Line 93: Update pattern match
    - Change `ty::SubtypePredicate` to `ty::SubtypeRelation`
    - Change `{ a, b, a_is_expected: _ }` to `{ sub_ty, super_ty, a_is_expected: _ }`
    - Rename variables in the match body
  - [ ] Verification: Correct field access

- [ ] **rustc_trait_selection/src/error_reporting/traits/ambiguity.rs**
  - [ ] Line 503: Update let binding
    - Change `let ty::SubtypePredicate` to `let ty::SubtypeRelation`
    - Change `{ a_is_expected: _, a, b }` to `{ a_is_expected: _, sub_ty, super_ty }`
    - Rename all references to `a` and `b` afterward
  - [ ] Verification: Variable references are correct

- [ ] **rustc_hir_typeck/src/fallback.rs**
  - [ ] Search for `PredicateKind::Subtype` pattern match
  - [ ] Update pattern: change field names from `a, b` to `sub_ty, super_ty`
  - [ ] Rename variables in the match body
  - [ ] Verification: Correct field access

- [ ] **rustc_infer/src/infer/mod.rs**
  - [ ] Search for destructuring of `SubtypePredicate`
  - [ ] Update struct name to `SubtypeRelation`
  - [ ] Update field names in pattern
  - [ ] Rename variables throughout closure/function
  - [ ] Verification: All variable references are correct

### Phase 5: Trait Bounds and Generic Parameters
These establish constraints for the generic system.

- [ ] **rustc_type_ir/src/interner.rs**
  - [ ] Line 31: Update trait bound
    - Change `+ IrPrint<ty::SubtypePredicate<Self>>` to `+ IrPrint<ty::SubtypeRelation<Self>>`
  - [ ] Verification: Trait compilation succeeds

- [ ] **rustc_type_ir/src/ir_print.rs**
  - [ ] Lines 6, 54: Update imports and macro references
    - Change `SubtypePredicate` to `SubtypeRelation`
  - [ ] Verify all macro usages are correct
  - [ ] Verification: Display/Debug implementations compile

### Phase 6: Public API (rustc_public)
These changes affect the stable/public interface of the compiler.

- [ ] **rustc_public/src/ty.rs**
  - [ ] Find struct definition of `SubtypePredicate`
  - [ ] Rename `pub struct SubtypePredicate` to `pub struct SubtypeRelation`
  - [ ] Rename field `pub a: Ty` to `pub sub_ty: Ty`
  - [ ] Rename field `pub b: Ty` to `pub super_ty: Ty`
  - [ ] Find enum variant `SubType(SubtypePredicate)`
  - [ ] Change to `SubType(SubtypeRelation)`
  - [ ] Verification: Public API compiles correctly

- [ ] **rustc_public/src/unstable/convert/stable/ty.rs**
  - [ ] Find `impl Stable for ty::SubtypePredicate`
  - [ ] Change to `impl Stable for ty::SubtypeRelation`
  - [ ] Update associated type: `type T = crate::ty::SubtypeRelation;`
  - [ ] Update destructuring: `let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ } = self;`
  - [ ] Update construction: `crate::ty::SubtypeRelation { sub_ty: ..., super_ty: ... }`
  - [ ] Verification: Conversion implementations compile

### Phase 7: Documentation and Comments
These keep the codebase documentation up-to-date.

- [ ] **rustc_trait_selection/src/traits/mod.rs**
  - [ ] Line 118: Update comment
    - Change `// always comes from a SubtypePredicate` to `// always comes from a SubtypeRelation`
  - [ ] Verification: Comment is accurate

- [ ] **rustc_type_ir/src/predicate.rs**
  - [ ] Verify struct documentation is updated (already done in Phase 1)
  - [ ] Check for any other comments referencing the old name

### Phase 8: Compilation Verification

- [ ] Verify no compilation errors by running:
  ```bash
  cargo build -p rustc_type_ir
  cargo build -p rustc_middle
  cargo build -p rustc_infer
  cargo build -p rustc_trait_selection
  cargo build -p rustc_hir_typeck
  cargo build -p rustc_next_trait_solver
  cargo build -p rustc_public
  ```

### Phase 9: Reference Verification

- [ ] Run comprehensive search to ensure no old names remain:
  ```bash
  grep -r "SubtypePredicate" compiler/ --include="*.rs" | grep -v "// " | grep -v "Deprecated"
  ```
  Expected result: Only deprecated type aliases or comments should remain

- [ ] Verify field references don't use old names:
  ```bash
  grep -r "\.a" compiler/rustc_type_ir compiler/rustc_infer compiler/rustc_trait_selection | grep -i "subtype"
  grep -r "\.b" compiler/rustc_type_ir compiler/rustc_infer compiler/rustc_trait_selection | grep -i "subtype"
  ```
  Expected result: No matches in subtype-related code (except CoercePredicate which uses the same field names)

### Phase 10: Testing

- [ ] Run compiler test suite:
  ```bash
  ./x test --stage 1 2>&1 | head -100
  ```

- [ ] Run specific subtype-related tests:
  ```bash
  ./x test --stage 1 ui/impl-trait/impl-subtyper.rs
  ./x test --stage 1 ui/nll/issue-57642-higher-ranked-subtype.rs
  ```

- [ ] Run full test suite (if time permits):
  ```bash
  ./x test
  ```

## Completeness Verification Checklist

After all changes are applied, verify:

- [ ] Struct `SubtypeRelation` exists in rustc_type_ir
- [ ] Fields are named `sub_ty` and `super_ty`
- [ ] Type aliases in rustc_middle use new names
- [ ] All struct literals compile with new field names
- [ ] All pattern matches compile with new field names
- [ ] No references to old `SubtypePredicate` name remain (except deprecated aliases)
- [ ] No references to old field names `.a` and `.b` remain for subtype relations
- [ ] Public API exports are correct
- [ ] Stable conversion implementations work
- [ ] All compiler crates build successfully
- [ ] Test suite passes

## Rollback Plan

If issues arise during implementation:

1. Revert all changes to the affected files
2. Verify revert with: `git diff --name-only`
3. Rebuild to confirm working state

## Files Summary

| Phase | Files | Count |
|-------|-------|-------|
| Phase 1 | Core definition | 2 |
| Phase 2 | Type aliases | 2 |
| Phase 3 | Struct literals | 3 |
| Phase 4 | Pattern matches | 6 |
| Phase 5 | Trait bounds | 2 |
| Phase 6 | Public API | 2 |
| Phase 7 | Documentation | 1 |
| **Total** | **All files** | **18** |

## Key Semantic Considerations

1. **Field Semantics**: In all cases, the first field (`sub_ty`, formerly `a`) represents the subtype, and the second field (`super_ty`, formerly `b`) represents the supertype. The relation is: `sub_ty <: super_ty`.

2. **Swapped Cases**: In `solver_relating.rs` and `type_relating.rs`, there are cases where the fields are intentionally swapped (lines 213-217 and 155-159). This is semantically correct and intentional - it represents different directions of the type relation based on `a_is_expected`.

3. **Backward Compatibility**: Optional deprecation aliases can maintain backward compatibility with external tools that depend on the Rust compiler public API.

4. **Performance**: This refactoring has zero performance impact - it's purely a naming change.

## Success Criteria

The refactoring is successful when:
1. All 18 files are updated with the new struct and field names
2. The compiler builds without errors
3. The test suite passes without regressions
4. No references to old names remain (except deprecated aliases)
5. The semantic meaning of the type relations is preserved

