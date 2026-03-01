# Rust Compiler Refactoring: Rename SubtypePredicate to SubtypeRelation

## Executive Summary

This refactoring renames `SubtypePredicate` to `SubtypeRelation` and renames its fields `a` → `sub_ty` and `b` → `super_ty` across the Rust compiler. The changes span 28+ files across 9 compiler crates and the rust-analyzer tool.

## Files Examined

### Definition Files (2)
1. **compiler/rustc_type_ir/src/predicate.rs** — MAIN definition of `SubtypePredicate<I: Interner>` struct with fields: `a_is_expected`, `a`, `b`
2. **compiler/rustc_public/src/ty.rs** — PUBLIC definition of `SubtypePredicate` struct with fields: `a`, `b`

### Type Alias Files (3)
3. **compiler/rustc_middle/src/ty/predicate.rs** — Defines type aliases `SubtypePredicate<'tcx>` and `PolySubtypePredicate<'tcx>` pointing to IR types
4. **src/tools/rust-analyzer/crates/hir-ty/src/next_solver/predicate.rs** — rust-analyzer type aliases
5. **src/tools/rust-analyzer/crates/hir-ty/src/next_solver/infer/mod.rs** — rust-analyzer infer type aliases

### Re-Export Files (1)
6. **compiler/rustc_middle/src/ty/mod.rs** — Re-exports `SubtypePredicate` and `PolySubtypePredicate`

### Field Access/Pattern Matching Files (13)
7. **compiler/rustc_type_ir/src/flags.rs** — Pattern matching: `PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b })`
8. **compiler/rustc_type_ir/src/relate/solver_relating.rs** — Struct construction with 3 fields: `a_is_expected`, `a`, `b`
9. **compiler/rustc_infer/src/infer/mod.rs** — Struct construction and pattern matching with all 3 fields
10. **compiler/rustc_infer/src/infer/relate/type_relating.rs** — Struct construction with 3 fields
11. **compiler/rustc_next_trait_solver/src/solve/mod.rs** — Struct construction with 3 fields, field access on `a` and `b`
12. **compiler/rustc_hir_typeck/src/fallback.rs** — Pattern matching: `PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b })`
13. **compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs** — Pattern matching with `a`, `b` fields
14. **compiler/rustc_trait_selection/src/solve/delegate.rs** — Pattern matching: `PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })`
15. **compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs** — Pattern matching: `SubtypePredicate { a_is_expected: _, a, b }`
16. **compiler/rustc_trait_selection/src/traits/fulfill.rs** — References to `PredicateKind::Subtype` predicate handling
17. **compiler/rustc_trait_selection/src/traits/select/mod.rs** — References to `PredicateKind::Subtype` in goal processing
18. **compiler/rustc_trait_selection/src/traits/auto_trait.rs** — Pattern matching on `PredicateKind::Subtype`
19. **compiler/rustc_traits/src/normalize_erasing_regions.rs** — Pattern matching on `PredicateKind::Subtype`
20. **compiler/rustc_middle/src/ty/print/pretty.rs** — Print impl: `self.a.print(p)?; ... self.b.print(p)?;`

### Type System Infrastructure Files (5)
21. **compiler/rustc_type_ir/src/interner.rs** — IrPrint bound: `IrPrint<ty::SubtypePredicate<Self>>`
22. **compiler/rustc_type_ir/src/ir_print.rs** — Imports and trait bounds for IrPrint
23. **compiler/rustc_type_ir/src/predicate_kind.rs** — PredicateKind enum: `Subtype(ty::SubtypePredicate<I>)` variant
24. **compiler/rustc_public/src/unstable/convert/stable/ty.rs** — Stable conversion: pattern matches on `ty::SubtypePredicate`, constructs `crate::ty::SubtypePredicate`

### Rust-Analyzer Tool Files (4)
25. **src/tools/rust-analyzer/crates/hir-ty/src/next_solver/solver.rs** — Pattern matching: `PredicateKind::Subtype(SubtypePredicate { a, b, .. })`
26. **src/tools/rust-analyzer/crates/hir-ty/src/infer/fallback.rs** — Pattern matching: `PredicateKind::Subtype(SubtypePredicate { a_is_expected: _, a, b })`
27. **src/tools/rust-analyzer/crates/hir-ty/src/infer/unify.rs** — Pattern matching on `PredicateKind::Subtype`

### Test Files (1)
28. **tests/rustdoc-js/auxiliary/interner.rs** — Test auxiliary with `type SubtypePredicate` associated type

---

## Dependency Chain

The refactoring follows this dependency chain:

```
1. CORE DEFINITIONS:
   - compiler/rustc_type_ir/src/predicate.rs (defines SubtypePredicate<I>)
   - compiler/rustc_public/src/ty.rs (defines public SubtypePredicate)

2. IMMEDIATE CONSUMERS:
   - compiler/rustc_type_ir/src/predicate_kind.rs (uses in PredicateKind::Subtype variant)
   - compiler/rustc_middle/src/ty/predicate.rs (type aliases)

3. RE-EXPORTS:
   - compiler/rustc_middle/src/ty/mod.rs (re-exports from predicate.rs)
   - compiler/rustc_type_ir/src/interner.rs (IrPrint bounds)
   - compiler/rustc_type_ir/src/ir_print.rs (IrPrint traits)

4. DIRECT USAGE:
   - compiler/rustc_type_ir/src/flags.rs
   - compiler/rustc_type_ir/src/relate/solver_relating.rs
   - compiler/rustc_infer/src/infer/mod.rs
   - compiler/rustc_infer/src/infer/relate/type_relating.rs
   - compiler/rustc_next_trait_solver/src/solve/mod.rs
   - compiler/rustc_hir_typeck/src/fallback.rs
   - compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs
   - compiler/rustc_trait_selection/src/solve/delegate.rs
   - compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs
   - compiler/rustc_trait_selection/src/traits/fulfill.rs
   - compiler/rustc_trait_selection/src/traits/select/mod.rs
   - compiler/rustc_trait_selection/src/traits/auto_trait.rs
   - compiler/rustc_traits/src/normalize_erasing_regions.rs
   - compiler/rustc_middle/src/ty/print/pretty.rs
   - compiler/rustc_public/src/unstable/convert/stable/ty.rs

5. RUST-ANALYZER EQUIVALENTS:
   - src/tools/rust-analyzer/crates/hir-ty/src/next_solver/predicate.rs
   - src/tools/rust-analyzer/crates/hir-ty/src/next_solver/infer/mod.rs
   - src/tools/rust-analyzer/crates/hir-ty/src/next_solver/solver.rs
   - src/tools/rust-analyzer/crates/hir-ty/src/infer/fallback.rs
   - src/tools/rust-analyzer/crates/hir-ty/src/infer/unify.rs

6. TESTS:
   - tests/rustdoc-js/auxiliary/interner.rs
```

---

## Change Categories

### Category 1: Rename Struct & Fields in Definitions
**Files:** 2
- `compiler/rustc_type_ir/src/predicate.rs` - Rename struct, rename fields `a` → `sub_ty`, `b` → `super_ty`
- `compiler/rustc_public/src/ty.rs` - Rename struct, rename fields `a` → `sub_ty`, `b` → `super_ty`

### Category 2: Update Type Aliases (Rename References)
**Files:** 3
- `compiler/rustc_middle/src/ty/predicate.rs` - Update alias names and field accesses
- `src/tools/rust-analyzer/crates/hir-ty/src/next_solver/predicate.rs` - Update alias
- `src/tools/rust-analyzer/crates/hir-ty/src/next_solver/infer/mod.rs` - Update alias

### Category 3: Update Re-Exports & Imports
**Files:** 1
- `compiler/rustc_middle/src/ty/mod.rs` - Update re-exported names

### Category 4: Update Pattern Matching
**Files:** 8
- `compiler/rustc_type_ir/src/flags.rs` - Change pattern: `{ a_is_expected: _, a, b }` → `{ a_is_expected: _, sub_ty, super_ty }`
- `compiler/rustc_hir_typeck/src/fallback.rs` - Same pattern match changes
- `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs` - Same changes
- `compiler/rustc_trait_selection/src/solve/delegate.rs` - Update patterns
- `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs` - Update patterns
- `src/tools/rust-analyzer/crates/hir-ty/src/next_solver/solver.rs` - Update patterns
- `src/tools/rust-analyzer/crates/hir-ty/src/infer/fallback.rs` - Update patterns
- `src/tools/rust-analyzer/crates/hir-ty/src/infer/unify.rs` - Update patterns

### Category 5: Update Struct Construction
**Files:** 5
- `compiler/rustc_type_ir/src/relate/solver_relating.rs` - Change `SubtypePredicate { a_is_expected: ..., a, b }` → `SubtypeRelation { a_is_expected: ..., sub_ty, super_ty }`
- `compiler/rustc_infer/src/infer/mod.rs` - Same changes
- `compiler/rustc_infer/src/infer/relate/type_relating.rs` - Same changes
- `compiler/rustc_next_trait_solver/src/solve/mod.rs` - Same changes
- `compiler/rustc_public/src/unstable/convert/stable/ty.rs` - Update struct construction

### Category 6: Update Print Implementations
**Files:** 1
- `compiler/rustc_middle/src/ty/print/pretty.rs` - Update field accesses in print: `self.a` → `self.sub_ty`, `self.b` → `self.super_ty`

### Category 7: Update Type System Boundaries (IrPrint)
**Files:** 2
- `compiler/rustc_type_ir/src/interner.rs` - Update IrPrint bounds
- `compiler/rustc_type_ir/src/ir_print.rs` - Update IrPrint imports/trait bounds

### Category 8: Update Enum Variant Data Type
**Files:** 1
- `compiler/rustc_type_ir/src/predicate_kind.rs` - Update variant type reference: `Subtype(ty::SubtypeRelation<I>)`

### Category 9: Update Test Helpers
**Files:** 1
- `tests/rustdoc-js/auxiliary/interner.rs` - Update type name if used

---

## Refactoring Strategy

### Phase 1: Core Definition Changes
1. Modify `compiler/rustc_type_ir/src/predicate.rs` — rename struct, rename fields
2. Modify `compiler/rustc_public/src/ty.rs` — rename struct, rename fields

### Phase 2: Type System Infrastructure
3. Modify `compiler/rustc_type_ir/src/predicate_kind.rs` — update variant type reference
4. Modify `compiler/rustc_type_ir/src/interner.rs` — update IrPrint bounds
5. Modify `compiler/rustc_type_ir/src/ir_print.rs` — update imports

### Phase 3: Re-exports & Type Aliases
6. Modify `compiler/rustc_middle/src/ty/predicate.rs` — update type aliases
7. Modify `compiler/rustc_middle/src/ty/mod.rs` — update re-exports

### Phase 4: Direct Usage in Core Crates
8. Modify `compiler/rustc_type_ir/src/flags.rs` — pattern matching
9. Modify `compiler/rustc_type_ir/src/relate/solver_relating.rs` — struct construction
10. Modify `compiler/rustc_infer/src/infer/mod.rs` — struct construction & pattern matching
11. Modify `compiler/rustc_infer/src/infer/relate/type_relating.rs` — struct construction
12. Modify `compiler/rustc_next_trait_solver/src/solve/mod.rs` — struct construction & field access

### Phase 5: Type Checking & Error Handling
13. Modify `compiler/rustc_hir_typeck/src/fallback.rs` — pattern matching
14. Modify `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs` — pattern matching
15. Modify `compiler/rustc_trait_selection/src/solve/delegate.rs` — pattern matching
16. Modify `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs` — pattern matching
17. Modify `compiler/rustc_trait_selection/src/traits/fulfill.rs` — predicate handling
18. Modify `compiler/rustc_trait_selection/src/traits/select/mod.rs` — goal processing
19. Modify `compiler/rustc_trait_selection/src/traits/auto_trait.rs` — pattern matching
20. Modify `compiler/rustc_traits/src/normalize_erasing_regions.rs` — pattern matching

### Phase 6: Display & Conversion
21. Modify `compiler/rustc_middle/src/ty/print/pretty.rs` — print impl
22. Modify `compiler/rustc_public/src/unstable/convert/stable/ty.rs` — stable conversion

### Phase 7: Rust-Analyzer Tool
23. Modify `src/tools/rust-analyzer/crates/hir-ty/src/next_solver/predicate.rs` — type aliases
24. Modify `src/tools/rust-analyzer/crates/hir-ty/src/next_solver/infer/mod.rs` — type aliases
25. Modify `src/tools/rust-analyzer/crates/hir-ty/src/next_solver/solver.rs` — pattern matching
26. Modify `src/tools/rust-analyzer/crates/hir-ty/src/infer/fallback.rs` — pattern matching
27. Modify `src/tools/rust-analyzer/crates/hir-ty/src/infer/unify.rs` — pattern matching

### Phase 8: Tests
28. Modify `tests/rustdoc-js/auxiliary/interner.rs` — test helper types

---

## Code Changes Summary

The refactoring involves three types of changes:

### Change Type A: Field Renames in Struct Definitions
```
pub struct SubtypePredicate<I: Interner> {
    pub a_is_expected: bool,      // UNCHANGED
-   pub a: I::Ty,
+   pub sub_ty: I::Ty,
-   pub b: I::Ty,
+   pub super_ty: I::Ty,
}
```

### Change Type B: Field Renames in Pattern Matches
```
// Before:
match thing {
    PredicateKind::Subtype(SubtypePredicate { a_is_expected: _, a, b }) => { ... }
}

// After:
match thing {
    PredicateKind::Subtype(SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => { ... }
}
```

### Change Type C: Field Renames in Struct Construction
```
// Before:
ty::SubtypePredicate {
    a_is_expected: false,
    a: goal.predicate.a,
    b: goal.predicate.b,
}

// After:
ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: goal.predicate.sub_ty,
    super_ty: goal.predicate.super_ty,
}
```

### Change Type D: Field Access Updates
```
// Before:
let r_a = self.shallow_resolve(predicate.skip_binder().a);
let r_b = self.shallow_resolve(predicate.skip_binder().b);

// After:
let r_a = self.shallow_resolve(predicate.skip_binder().sub_ty);
let r_b = self.shallow_resolve(predicate.skip_binder().super_ty);
```

---

## Implementation Notes

### Important Details
1. **Field Naming Strategy:** The field names `a` and `b` are renamed to `sub_ty` and `super_ty` respectively, making the semantic relationship explicit (subtype <: supertype).

2. **Semantic Preservation:** The renaming preserves all semantic relationships:
   - `a` (the subtype) is renamed to `sub_ty`
   - `b` (the supertype) is renamed to `super_ty`
   - The `a_is_expected` field remains unchanged as it's a metadata flag

3. **Cross-Crate Consistency:** The same field names must be used consistently across all crates, ensuring that pattern matching and struct construction work correctly.

4. **Print Representation:** The pretty-printer will need to access the renamed fields. The print representation remains the same (`<:`) but uses `sub_ty` and `super_ty` internally.

5. **Type Aliases:** Type aliases in `rustc_middle` and `rust-analyzer` only rename the type reference; they don't introduce new names for fields (fields are accessible only on the struct itself).

---

## Verification Strategy

After implementation, verify:
1. **Compilation:** Ensure the entire compiler builds without errors
2. **Test Suite:** Run the full test suite to verify no behavioral changes
3. **Search & Replace Verification:** Confirm no stale references to the old field names remain
4. **Pattern Matching:** Verify all pattern matches correctly destructure the renamed fields
5. **Struct Construction:** Verify all struct literals use the new field names

### Verification Commands
```bash
# Verify no references to SubtypePredicate (should find only comments/docs)
cargo grep "pub struct SubtypePredicate"

# Verify new name is present
cargo grep "pub struct SubtypeRelation"

# Verify field rename - should only find new name
cargo grep "\.a\>" | grep -i subtype  # should be minimal
cargo grep "\.sub_ty" | grep -i subtype  # should be many

# Build specific crate with the changes
cargo build -p rustc_type_ir
cargo build -p rustc_middle
cargo test -p rustc_type_ir
```

---

## Analysis Complete

This refactoring requires modifications to **28 files** across **9 compiler crates** and the **rust-analyzer** tool. The changes are mechanical but comprehensive, requiring careful attention to:
- Struct field names in definitions
- Pattern matching destructuring
- Struct literal construction
- Field access expressions
- Type signatures and bounds

The dependency chain ensures that once the core definitions are changed, all dependent code will fail to compile until updated, making it a safe refactoring with no risk of incomplete updates being missed.

---

## Detailed Code Changes

A complete file-by-file implementation of all required changes is provided in `/workspace/IMPLEMENTATION_CHANGES.md`. This document includes:

1. **Phase 1: Core Definitions** (2 files)
   - Struct definition renaming
   - Field name updates

2. **Phase 2: Type System Infrastructure** (3 files)
   - Variant type annotations
   - IrPrint trait bounds
   - Import updates

3. **Phase 3: Type Aliases & Re-exports** (2 files)
   - Type alias renaming
   - Re-export updates

4. **Phase 4-8: Direct Usage, Construction, Printing** (15 files)
   - Pattern matching updates
   - Struct construction updates
   - Field access updates
   - Print implementation updates

5. **Phase 9: Tests** (1 file)
   - Test helper type updates

Each section includes:
- Exact file path and line numbers
- Before/After code with `diff` syntax
- Clear explanation of change type

---

## Implementation Guide

To implement this refactoring:

1. **Start with Phase 1** - Update core struct definitions first
2. **Proceed through Phases 2-3** - Update type system infrastructure and aliases
3. **Execute Phases 4-8 in order** - Update all usage sites
4. **Finally Phase 9** - Update tests

At each phase, ensure:
- All files in that phase compile before moving to the next
- No stale references to old names remain
- Pattern matching destructures correctly with new field names
- Struct construction uses new field names

---

## File Coverage Summary

### Files Modified: 28 Total

| Category | Count | Files |
|----------|-------|-------|
| Core Definitions | 2 | rustc_type_ir, rustc_public |
| Type Aliases | 3 | rustc_middle, rust-analyzer (2x) |
| Re-exports | 1 | rustc_middle |
| Pattern Matching | 8 | rustc_type_ir, rustc_hir_typeck, rustc_trait_selection (3x), rust-analyzer (2x), rustc_traits |
| Struct Construction | 5 | rustc_type_ir, rustc_infer (2x), rustc_next_trait_solver, rustc_public |
| Print Implementations | 1 | rustc_middle |
| Type System Bounds | 2 | rustc_type_ir |
| Trait Selection | 4 | rustc_trait_selection (3x), rustc_traits |
| Tests | 1 | tests |
| **Total** | **28** | |

### Crates Affected (9)

1. rustc_type_ir - Definition, flags, relate, interner, ir_print, predicate_kind
2. rustc_public - Definition, stable conversion
3. rustc_middle - Type aliases, re-exports, print
4. rustc_infer - Subtype predicate handling (2 files)
5. rustc_next_trait_solver - Subtype goal computation
6. rustc_hir_typeck - Fallback type inference
7. rustc_trait_selection - Error reporting, solving, trait selection (4 files)
8. rustc_traits - Normalization
9. rust-analyzer tool - Similar refactoring in analyzer codebase (5 files)

---

## Analysis and Correctness

### Why This Refactoring Is Safe

1. **Struct Field Visibility**: Both `a` and `b` are public fields, so renaming them everywhere is required and detectable by the compiler.
2. **Type-Directed Changes**: All usages are bound to the type system, so missing a reference will result in a compilation error.
3. **Mechanical Transformation**: All changes follow a consistent pattern (field name swapping).
4. **Semantic Preservation**: The field semantics remain unchanged; only their names become more explicit.

### Verification Checklist

- [ ] All 28 files identified and modified
- [ ] No references to old names remain (grep for `SubtypePredicate<I>` returns empty, except in docs)
- [ ] All struct constructions updated with new field names
- [ ] All pattern matches updated with new field names
- [ ] All field accesses (`.a`, `.b`) updated to (`.sub_ty`, `.super_ty`)
- [ ] Type aliases updated with new names
- [ ] IrPrint bounds updated with new type names
- [ ] Compiler builds successfully: `cargo build -p rustc_type_ir rustc_middle`
- [ ] Test suite passes: `cargo test`
- [ ] No stale references in documentation/comments
