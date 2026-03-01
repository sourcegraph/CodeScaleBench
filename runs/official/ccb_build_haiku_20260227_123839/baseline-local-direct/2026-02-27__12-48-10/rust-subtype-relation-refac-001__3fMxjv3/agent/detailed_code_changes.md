# Detailed Code Changes for SubtypePredicate → SubtypeRelation Refactoring

This document provides exact before/after code for each file that needs to be modified.

---

## 1. compiler/rustc_type_ir/src/predicate.rs

### Change: Rename struct and fields

**Location**: Lines 909-924

**Before**:
```rust
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
```

**After**:
```rust
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

---

## 2. compiler/rustc_type_ir/src/predicate_kind.rs

### Change: Update enum variant type

**Location**: Line 78

**Before**:
```rust
    Subtype(ty::SubtypePredicate<I>),
```

**After**:
```rust
    Subtype(ty::SubtypeRelation<I>),
```

---

## 3. compiler/rustc_middle/src/ty/predicate.rs

### Change: Update type aliases

**Location**: Lines 24, 32

**Before**:
```rust
pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;
pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;
```

**After**:
```rust
pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;
pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;

// Deprecated: Use SubtypeRelation instead
pub type SubtypePredicate<'tcx> = SubtypeRelation<'tcx>;
pub type PolySubtypePredicate<'tcx> = PolySubtypeRelation<'tcx>;
```

---

## 4. compiler/rustc_type_ir/src/flags.rs

### Change: Update pattern match field names

**Location**: Line 394

**Before**:
```rust
            ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
```

**After**:
```rust
            ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
```

**Note**: Any usages of `a` and `b` variables after this line need to be renamed to `sub_ty` and `super_ty`.

---

## 5. compiler/rustc_type_ir/src/relate/solver_relating.rs

### Change 1: First struct literal construction

**Location**: Lines 200-204

**Before**:
```rust
                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
                                a_is_expected: true,
                                a,
                                b,
                            }))
```

**After**:
```rust
                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
                                a_is_expected: true,
                                sub_ty: a,
                                super_ty: b,
                            }))
```

### Change 2: Second struct literal construction (semantically swapped)

**Location**: Lines 213-217

**Before**:
```rust
                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
                                a_is_expected: false,
                                a: b,
                                b: a,
                            }))
```

**After**:
```rust
                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
                                a_is_expected: false,
                                sub_ty: b,
                                super_ty: a,
                            }))
```

---

## 6. compiler/rustc_type_ir/src/ir_print.rs

### Change: Update imports

**Location**: Lines 6, 54

**Before**:
```rust
    PatternKind, ProjectionPredicate, SubtypePredicate, TraitPredicate, TraitRef, UnevaluatedConst,
    ...
    SubtypePredicate,
```

**After**:
```rust
    PatternKind, ProjectionPredicate, SubtypeRelation, TraitPredicate, TraitRef, UnevaluatedConst,
    ...
    SubtypeRelation,
```

---

## 7. compiler/rustc_type_ir/src/interner.rs

### Change: Update trait bound

**Location**: Line 31

**Before**:
```rust
    + IrPrint<ty::SubtypePredicate<Self>>
```

**After**:
```rust
    + IrPrint<ty::SubtypeRelation<Self>>
```

---

## 8. compiler/rustc_infer/src/infer/relate/type_relating.rs

### Change 1: First struct literal construction

**Location**: Lines 141-145

**Before**:
```rust
                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
                                a_is_expected: true,
                                a,
                                b,
                            }))
```

**After**:
```rust
                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
                                a_is_expected: true,
                                sub_ty: a,
                                super_ty: b,
                            }))
```

### Change 2: Second struct literal construction (semantically swapped)

**Location**: Lines 155-159

**Before**:
```rust
                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
                                a_is_expected: false,
                                a: b,
                                b: a,
                            }))
```

**After**:
```rust
                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
                                a_is_expected: false,
                                sub_ty: b,
                                super_ty: a,
                            }))
```

---

## 9. compiler/rustc_infer/src/infer/mod.rs

### Change: Update destructuring pattern

**Location**: Where SubtypePredicate is destructured

**Before**:
```rust
        self.enter_forall(predicate, |ty::SubtypePredicate { a_is_expected, a, b }| {
```

**After**:
```rust
        self.enter_forall(predicate, |ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }| {
```

**Note**: Variables `a` and `b` should be renamed to `sub_ty` and `super_ty` throughout the closure body.

---

## 10. compiler/rustc_hir_typeck/src/fallback.rs

### Change: Update pattern match field names

**Location**: Pattern match with `PredicateKind::Subtype`

**Before**:
```rust
                    ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
```

**After**:
```rust
                    ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
```

**Note**: Update all usages of `a` and `b` to `sub_ty` and `super_ty` in the pattern match body.

---

## 11. compiler/rustc_trait_selection/src/traits/mod.rs

### Change: Update comment

**Location**: Line 118

**Before**:
```rust
    Subtype(ExpectedFound<Ty<'tcx>>, TypeError<'tcx>), // always comes from a SubtypePredicate
```

**After**:
```rust
    Subtype(ExpectedFound<Ty<'tcx>>, TypeError<'tcx>), // always comes from a SubtypeRelation
```

---

## 12. compiler/rustc_trait_selection/src/solve/delegate.rs

### Change: Update pattern match field names

**Location**: Line 127

**Before**:
```rust
            ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })
```

**After**:
```rust
            ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, .. })
```

**Note**: Update all usages of `a` and `b` to `sub_ty` and `super_ty` in the pattern match body.

---

## 13. compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs

### Change: Update pattern match field names

**Location**: Line 93

**Before**:
```rust
                    ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ })
```

**After**:
```rust
                    ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ })
```

**Note**: Update all usages of `a` and `b` to `sub_ty` and `super_ty` in the pattern match body.

---

## 14. compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs

### Change: Update pattern match field names

**Location**: Line 503

**Before**:
```rust
                let ty::SubtypePredicate { a_is_expected: _, a, b } = data;
```

**After**:
```rust
                let ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty } = data;
```

**Note**: Update all usages of `a` and `b` to `sub_ty` and `super_ty` after this line.

---

## 15. compiler/rustc_next_trait_solver/src/solve/mod.rs

### Change 1: Struct literal construction

**Location**: Where SubtypePredicate is constructed

**Before**:
```rust
            predicate: ty::SubtypePredicate {
                a_is_expected: ...,
                a: ...,
                b: ...,
            }
```

**After**:
```rust
            predicate: ty::SubtypeRelation {
                a_is_expected: ...,
                sub_ty: ...,
                super_ty: ...,
            }
```

### Change 2: Type annotation in function signature

**Location**: Where SubtypePredicate is used in type annotations

**Before**:
```rust
    fn compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypePredicate<I>>) -> QueryResult<I> {
```

**After**:
```rust
    fn compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypeRelation<I>>) -> QueryResult<I> {
```

---

## 16. compiler/rustc_public/src/ty.rs

### Change 1: Rename struct and fields

**Location**: Struct definition

**Before**:
```rust
pub struct SubtypePredicate {
    pub a: Ty,
    pub b: Ty,
    pub a_is_expected: bool,
}
```

**After**:
```rust
pub struct SubtypeRelation {
    pub sub_ty: Ty,
    pub super_ty: Ty,
    pub a_is_expected: bool,
}
```

### Change 2: Update enum variant

**Location**: PredicateKind enum

**Before**:
```rust
pub enum PredicateKind {
    // ...
    SubType(SubtypePredicate),
    // ...
}
```

**After**:
```rust
pub enum PredicateKind {
    // ...
    SubType(SubtypeRelation),
    // ...
}
```

---

## 17. compiler/rustc_public/src/unstable/convert/stable/ty.rs

### Change: Update Stable trait implementation

**Location**: Impl block for SubtypePredicate

**Before**:
```rust
impl<'tcx> Stable<'tcx> for ty::SubtypePredicate<'tcx> {
    type T = crate::ty::SubtypePredicate;

    fn stable(&self, tables: &mut Tables<'tcx>, cx: &'tcx CodegenCx<'tcx, 'tcx>) -> Self::T {
        let ty::SubtypePredicate { a, b, a_is_expected: _ } = self;
        crate::ty::SubtypePredicate { a: a.stable(tables, cx), b: b.stable(tables, cx) }
    }
}
```

**After**:
```rust
impl<'tcx> Stable<'tcx> for ty::SubtypeRelation<'tcx> {
    type T = crate::ty::SubtypeRelation;

    fn stable(&self, tables: &mut Tables<'tcx>, cx: &'tcx CodegenCx<'tcx, 'tcx>) -> Self::T {
        let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ } = self;
        crate::ty::SubtypeRelation { sub_ty: sub_ty.stable(tables, cx), super_ty: super_ty.stable(tables, cx) }
    }
}
```

---

## Summary of All Changes

| File | Type of Change | Lines |
|------|---|---|
| rustc_type_ir/src/predicate.rs | Struct rename + field rename | 909-924 |
| rustc_type_ir/src/predicate_kind.rs | Type annotation update | 78 |
| rustc_middle/src/ty/predicate.rs | Type alias update | 24, 32 |
| rustc_type_ir/src/flags.rs | Pattern match update | 394 |
| rustc_type_ir/src/relate/solver_relating.rs | Struct literal x2 | 200-204, 213-217 |
| rustc_type_ir/src/ir_print.rs | Import update | 6, 54 |
| rustc_type_ir/src/interner.rs | Trait bound update | 31 |
| rustc_infer/src/infer/relate/type_relating.rs | Struct literal x2 | 141-145, 155-159 |
| rustc_infer/src/infer/mod.rs | Pattern match update | (destructure) |
| rustc_hir_typeck/src/fallback.rs | Pattern match update | (subtype) |
| rustc_trait_selection/src/traits/mod.rs | Comment update | 118 |
| rustc_trait_selection/src/solve/delegate.rs | Pattern match update | 127 |
| rustc_trait_selection/src/error_reporting/traits/overflow.rs | Pattern match update | 93 |
| rustc_trait_selection/src/error_reporting/traits/ambiguity.rs | Pattern match update | 503 |
| rustc_next_trait_solver/src/solve/mod.rs | Struct literal + type annotation | (multi) |
| rustc_public/src/ty.rs | Struct rename + enum variant | (struct) |
| rustc_public/src/unstable/convert/stable/ty.rs | Trait impl update | (impl block) |

**Total: 17 files, 1 struct renamed, 2 fields renamed, multiple usage sites updated**

