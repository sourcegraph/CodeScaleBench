# SubtypePredicate → SubtypeRelation Refactoring Analysis

## Summary

This refactoring renames `SubtypePredicate` to `SubtypeRelation` and its fields `a`/`b` to `sub_ty`/`super_ty` throughout the Rust compiler. The change improves clarity by making the semantic meaning of the fields explicit (subtype vs supertype in a subtype relation).

**Scope**: 19 files across 9 compiler crates
- `rustc_type_ir` (core IR definitions)
- `rustc_middle` (tcx type aliases)
- `rustc_public` (public API)
- `rustc_infer` (inference engine)
- `rustc_trait_selection` (trait solver)
- `rustc_hir_typeck` (type checker)
- `rustc_next_trait_solver` (new solver)

## Files Examined

### Core Definitions (rustc_type_ir)
1. **compiler/rustc_type_ir/src/predicate.rs** — Definition of `SubtypePredicate` struct (lines 918-922)
   - Struct with fields: `a_is_expected: bool`, `a: I::Ty`, `b: I::Ty`
   - Derives: Clone, Copy, Hash, PartialEq, Debug, TypeVisitable, TypeFoldable, Lift
   - Eq impl provided

2. **compiler/rustc_type_ir/src/predicate_kind.rs** — Use in `PredicateKind` enum variant
   - Line 78: `Subtype(ty::SubtypePredicate<I>)` variant

3. **compiler/rustc_type_ir/src/ir_print.rs** — IrPrint bound/impl
   - Line 6: import `SubtypePredicate`
   - Line 16: in explicit impl list

4. **compiler/rustc_type_ir/src/interner.rs** — IrPrint trait bound
   - Requires `IrPrint<ty::SubtypePredicate<Self>>`

5. **compiler/rustc_type_ir/src/flags.rs** — Destructuring in TypeFlags calculation
   - Line 394: Pattern matching `ty::SubtypePredicate { a_is_expected: _, a, b }`

6. **compiler/rustc_type_ir/src/relate/solver_relating.rs** — Construction sites
   - Lines 200, 213: Creating `SubtypePredicate` in `PredicateKind::Subtype` variant

### Type Aliases (rustc_middle)
7. **compiler/rustc_middle/src/ty/predicate.rs** — Type alias definitions
   - Line 24: `pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;`
   - Line 32: `pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;`

8. **compiler/rustc_middle/src/ty/mod.rs** — Re-exports
   - Exports `SubtypePredicate` and `PolySubtypePredicate`

9. **compiler/rustc_middle/src/ty/print/pretty.rs** — Display/Debug impl
   - Pattern matching on `ty::SubtypePredicate<'tcx> { a, b, a_is_expected }`

### Trait Solver Usage (rustc_trait_selection)
10. **compiler/rustc_trait_selection/src/solve/delegate.rs** — Destructuring
    - Line 127: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })`

11. **compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs** — Error reporting
    - Line 93: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ })`

12. **compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs** — Error reporting
    - Line 503: `let ty::SubtypePredicate { a_is_expected: _, a, b } = data;`

13. **compiler/rustc_trait_selection/src/traits/mod.rs** — Comment reference
    - References `SubtypePredicate` in trait error documentation

### Type Inference (rustc_infer)
14. **compiler/rustc_infer/src/infer/mod.rs** — Construction and destructuring
    - Line 719: Creates `ty::SubtypePredicate { a_is_expected, a: ..., b: ... }`
    - Line 756: Pattern matching `ty::SubtypePredicate { a_is_expected, a, b }`

15. **compiler/rustc_infer/src/infer/relate/type_relating.rs** — Construction in type relating
    - Lines 141, 155: Creating `SubtypePredicate` variants

### Type Checking (rustc_hir_typeck)
16. **compiler/rustc_hir_typeck/src/fallback.rs** — Fallback type inference
    - Line 353: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b })`

### New Trait Solver (rustc_next_trait_solver)
17. **compiler/rustc_next_trait_solver/src/solve/mod.rs** — Subtype goal computation
    - Line 112: Creating `predicate: ty::SubtypePredicate { a_is_expected, sub_ty, super_ty }`
    - Function `compute_subtype_goal` expects `Goal<I, ty::SubtypePredicate<I>>`

### Public API (rustc_public)
18. **compiler/rustc_public/src/ty.rs** — Public struct definition
    - Line 1485: Enum variant `SubType(SubtypePredicate)`
    - Lines 1511-1514: Struct definition with fields `a` and `b`

19. **compiler/rustc_public/src/unstable/convert/stable/ty.rs** — Stable conversion impl
    - Lines 779-788: `Stable<'tcx>` impl converting `ty::SubtypePredicate<'tcx>`

## Dependency Chain

```
1. DEFINITION:
   compiler/rustc_type_ir/src/predicate.rs (line 918)
   └─ SubtypePredicate<I: Interner> struct

2. USED IN TYPE_IR:
   compiler/rustc_type_ir/src/predicate_kind.rs (line 78)
   └─ PredicateKind::Subtype variant

   compiler/rustc_type_ir/src/ir_print.rs (lines 6, 16)
   └─ IrPrint impl list

   compiler/rustc_type_ir/src/interner.rs
   └─ IrPrint bound requirement

   compiler/rustc_type_ir/src/flags.rs (line 394)
   └─ TypeFlags computation

   compiler/rustc_type_ir/src/relate/solver_relating.rs (lines 200, 213)
   └─ Subtype goal construction

3. ALIASED IN MIDDLE:
   compiler/rustc_middle/src/ty/predicate.rs (lines 24, 32)
   └─ Type aliases for use with TyCtxt

   compiler/rustc_middle/src/ty/mod.rs
   └─ Re-exports from predicate.rs

   compiler/rustc_middle/src/ty/print/pretty.rs
   └─ Display impl for predicates

4. USED IN CRATES:
   compiler/rustc_trait_selection/src/
   ├─ solve/delegate.rs (line 127)
   ├─ error_reporting/traits/overflow.rs (line 93)
   ├─ error_reporting/traits/ambiguity.rs (line 503)
   └─ traits/mod.rs (comment)

   compiler/rustc_infer/src/
   ├─ infer/mod.rs (lines 719, 756)
   └─ infer/relate/type_relating.rs (lines 141, 155)

   compiler/rustc_hir_typeck/src/
   └─ fallback.rs (line 353)

   compiler/rustc_next_trait_solver/src/
   └─ solve/mod.rs (line 112)

5. PUBLIC API:
   compiler/rustc_public/src/
   ├─ ty.rs (lines 1485, 1511)
   └─ unstable/convert/stable/ty.rs (lines 779-788)
```

## Field Renaming Strategy

The struct has three fields:
- `a_is_expected: bool` — Keep as is (not changing field names per requirements)
- `a: I::Ty` → `sub_ty: I::Ty` (the subtype)
- `b: I::Ty` → `super_ty: I::Ty` (the supertype)

This aligns with the semantic meaning: in a subtype relation `a <: b`, `a` is the subtype and `b` is the supertype.

## Code Changes Required

### 1. Core Definition (rustc_type_ir/src/predicate.rs)

**Lines 909-922:**
```rust
// OLD
/// Encodes that `a` must be a subtype of `b`. The `a_is_expected` flag indicates
/// whether the `a` type is the type that we should label as "expected" when
/// presenting user diagnostics.
#[derive_where(Clone, Copy, Hash, PartialEq, Debug; I: Interner)]
#[derive(TypeVisitable_Generic, TypeFoldable_Generic, Lift_Generic)]
#[cfg_attr(
    feature = "nightly",
    derive(Decodable_NoContext, Encodable_NoContext, HashStable_NoContext)
)]
pub struct SubtypePredicate<I: Interner> {
    pub a_is_expected: bool,
    pub a: I::Ty,
    pub b: I::Ty,
}

impl<I: Interner> Eq for SubtypePredicate<I> {}

// NEW
/// Encodes that `sub_ty` must be a subtype of `super_ty`. The `a_is_expected` flag indicates
/// whether the `sub_ty` type is the type that we should label as "expected" when
/// presenting user diagnostics.
#[derive_where(Clone, Copy, Hash, PartialEq, Debug; I: Interner)]
#[derive(TypeVisitable_Generic, TypeFoldable_Generic, Lift_Generic)]
#[cfg_attr(
    feature = "nightly",
    derive(Decodable_NoContext, Encodable_NoContext, HashStable_NoContext)
)]
pub struct SubtypeRelation<I: Interner> {
    pub a_is_expected: bool,
    pub sub_ty: I::Ty,
    pub super_ty: I::Ty,
}

impl<I: Interner> Eq for SubtypeRelation<I> {}
```

### 2. Type Aliases (rustc_middle/src/ty/predicate.rs)

**Line 24:**
```rust
// OLD
pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;

// NEW
pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;

// Keep alias for compatibility if needed (but should be removed eventually):
// pub type SubtypePredicate<'tcx> = SubtypeRelation<'tcx>;
```

**Line 32:**
```rust
// OLD
pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;

// NEW
pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;
```

### 3. Public API (rustc_public/src/ty.rs)

**Lines 1485, 1511-1514:**
```rust
// OLD
pub enum PredicateKind {
    ...
    SubType(SubtypePredicate),
    ...
}

pub struct SubtypePredicate {
    pub a: Ty,
    pub b: Ty,
}

// NEW
pub enum PredicateKind {
    ...
    SubType(SubtypeRelation),
    ...
}

pub struct SubtypeRelation {
    pub sub_ty: Ty,
    pub super_ty: Ty,
}
```

### 4. Destructuring Sites

All pattern matches need to be updated. Example:

**OLD Pattern:**
```rust
ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ })
```

**NEW Pattern:**
```rust
ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ })
```

**Files affected:**
- `compiler/rustc_trait_selection/src/solve/delegate.rs:127`
- `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs:93`
- `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs:503`
- `compiler/rustc_hir_typeck/src/fallback.rs:353`
- `compiler/rustc_type_ir/src/flags.rs:394`
- `compiler/rustc_middle/src/ty/print/pretty.rs`
- `compiler/rustc_infer/src/infer/mod.rs:756`

### 5. Construction Sites

All `SubtypePredicate { ... }` constructions need field names updated:

**OLD Construction:**
```rust
ty::SubtypePredicate { a_is_expected, a: ..., b: ... }
```

**NEW Construction:**
```rust
ty::SubtypeRelation { a_is_expected, sub_ty: ..., super_ty: ... }
```

**Files affected:**
- `compiler/rustc_type_ir/src/relate/solver_relating.rs:200, 213`
- `compiler/rustc_infer/src/infer/mod.rs:719`
- `compiler/rustc_infer/src/infer/relate/type_relating.rs:141, 155`
- `compiler/rustc_next_trait_solver/src/solve/mod.rs:112`

### 6. Stable Conversion (rustc_public/src/unstable/convert/stable/ty.rs)

**Lines 779-788:**
```rust
// OLD
impl<'tcx> Stable<'tcx> for ty::SubtypePredicate<'tcx> {
    type T = crate::ty::SubtypePredicate;
    ...
    fn stable(...) -> Self::T {
        let ty::SubtypePredicate { a, b, a_is_expected: _ } = self;
        crate::ty::SubtypePredicate { a: a.stable(tables, cx), b: b.stable(tables, cx) }
    }
}

// NEW
impl<'tcx> Stable<'tcx> for ty::SubtypeRelation<'tcx> {
    type T = crate::ty::SubtypeRelation;
    ...
    fn stable(...) -> Self::T {
        let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ } = self;
        crate::ty::SubtypeRelation { sub_ty: sub_ty.stable(tables, cx), super_ty: super_ty.stable(tables, cx) }
    }
}
```

### 7. Imports and Re-exports

**rustc_middle/src/ty/mod.rs:**
```rust
// OLD
pub use self::predicate::{
    ...
    PolyProjectionPredicate, PolyRegionOutlivesPredicate, PolySubtypePredicate, PolyTraitPredicate,
    ...
    RegionOutlivesPredicate, SubtypePredicate, TraitPredicate, TraitRef,
    ...
};

// NEW
pub use self::predicate::{
    ...
    PolyProjectionPredicate, PolyRegionOutlivesPredicate, PolySubtypeRelation, PolyTraitPredicate,
    ...
    RegionOutlivesPredicate, SubtypeRelation, TraitPredicate, TraitRef,
    ...
};
```

**rustc_type_ir/src/ir_print.rs:**
```rust
// OLD
use crate::{
    ...,
    SubtypePredicate,
    ...
};

// NEW
use crate::{
    ...,
    SubtypeRelation,
    ...
};
```

### 8. IrPrint Bounds (rustc_type_ir/src/interner.rs)

```rust
// OLD
+ IrPrint<ty::SubtypePredicate<Self>>

// NEW
+ IrPrint<ty::SubtypeRelation<Self>>
```

## Verification Steps

1. **Compilation Check**: `cargo check --all` should pass without errors
2. **No Stale References**: `grep -r "SubtypePredicate" compiler/` should return only comments/doc references
3. **Field Access**: All `a` field accesses become `sub_ty`, all `b` become `super_ty` in predicate context
4. **Type Aliases**: Both old and new names should resolve correctly (verify through imports)
5. **Error Messages**: Compiler error messages should reference `SubtypeRelation` not `SubtypePredicate`

## Implementation Notes

1. **Backward Compatibility**: The change is internal to the compiler, so no external API is broken (rustc_public is updated)
2. **Field Rename Implications**: Any code that accessed `.a` or `.b` directly must be updated to use `.sub_ty` or `.super_ty`
3. **Comment Updates**: All comments/doc comments referencing the old field names should be updated
4. **Semantic Clarity**: The new field names make it immediately clear which is the subtype and which is the supertype

## Summary of Changes

| Item | Type | Old Name | New Name | Files |
|------|------|----------|----------|-------|
| Struct | Definition | `SubtypePredicate` | `SubtypeRelation` | 1 (predicate.rs) + 1 public (ty.rs) |
| Field | Rename | `.a` | `.sub_ty` | ~7 destructure, ~4 construct |
| Field | Rename | `.b` | `.super_ty` | ~7 destructure, ~4 construct |
| Type Alias | Rename | `SubtypePredicate<'tcx>` | `SubtypeRelation<'tcx>` | 1 (predicate.rs) |
| Type Alias | Rename | `PolySubtypePredicate<'tcx>` | `PolySubtypeRelation<'tcx>` | 1 (predicate.rs) |
| Enum Variant | Keep | `PredicateKind::Subtype(...)` | `PredicateKind::Subtype(...)` | no change (data type updates) |

## Total Files to Modify: 19

Core IR + definitions: 6 files
Type aliases and re-exports: 3 files
Compiler crate usage: 7 files
Public API: 2 files
Stable conversion: 1 file
