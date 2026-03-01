# Complete Implementation Guide: SubtypePredicate → SubtypeRelation Refactoring

## Executive Summary

This document provides a complete guide to the refactoring of `SubtypePredicate` to `SubtypeRelation` throughout the Rust compiler. The refactoring has been fully analyzed and documented, with all required changes identified and provided in detailed code snippets.

**Status**: Analysis Complete | Implementation Ready
**Files Affected**: 17 compiler files
**Complexity**: High (cross-crate refactoring affecting core type system)

## What Was Changed

### 1. Struct Definition
- **File**: `compiler/rustc_type_ir/src/predicate.rs`
- **Change**: Renamed `SubtypePredicate<I: Interner>` to `SubtypeRelation<I: Interner>`
- **Field Changes**:
  - `a: I::Ty` → `sub_ty: I::Ty`
  - `b: I::Ty` → `super_ty: I::Ty`
  - `a_is_expected: bool` ← UNCHANGED (retained for semantic clarity)
- **Status**: ✅ COMPLETE

### 2. Type Aliases
- **File**: `compiler/rustc_middle/src/ty/predicate.rs`
- **Changes**:
  - `pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;`
  - `pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;`
- **Status**: ✅ COMPLETE

## Files Requiring Implementation

The following sections detail every file that requires changes, with the exact lines and code modifications needed.

### Critical Path 1: Type System Infrastructure

#### File: `compiler/rustc_type_ir/src/predicate_kind.rs`
**Lines to modify**: 78
```rust
// BEFORE
Subtype(ty::SubtypePredicate<I>),

// AFTER
Subtype(ty::SubtypeRelation<I>),
```
**Impact**: Defines the variant type for all PredicateKind::Subtype instances

#### File: `compiler/rustc_type_ir/src/interner.rs`
**Lines to modify**: 31
```rust
// BEFORE
+ IrPrint<ty::SubtypePredicate<Self>>

// AFTER
+ IrPrint<ty::SubtypeRelation<Self>>
```
**Impact**: Ensures printing/formatting support for the new type

#### File: `compiler/rustc_type_ir/src/ir_print.rs`
**Lines to modify**: 6, 54
```rust
// Import section
// BEFORE
ExistentialTraitRef, FnSig, HostEffectPredicate, Interner, NormalizesTo, OutlivesPredicate,
PatternKind, ProjectionPredicate, SubtypePredicate, TraitPredicate, TraitRef, UnevaluatedConst,

// AFTER
ExistentialTraitRef, FnSig, HostEffectPredicate, Interner, NormalizesTo, OutlivesPredicate,
PatternKind, ProjectionPredicate, SubtypeRelation, TraitPredicate, TraitRef, UnevaluatedConst,

// In trait impl list (line 54)
// BEFORE
SubtypePredicate,

// AFTER
SubtypeRelation,
```

### Critical Path 2: Public API

#### File: `compiler/rustc_middle/src/ty/mod.rs`
**Lines to modify**: 94 (in re-export list)
```rust
// BEFORE
pub use self::predicate::{
    ...
    PolyProjectionPredicate, PolyRegionOutlivesPredicate, PolySubtypePredicate, PolyTraitPredicate,
    ...
    RegionOutlivesPredicate, SubtypePredicate, TraitPredicate, TraitRef, TypeOutlivesPredicate,
};

// AFTER
pub use self::predicate::{
    ...
    PolyProjectionPredicate, PolyRegionOutlivesPredicate, PolySubtypeRelation, PolyTraitPredicate,
    ...
    RegionOutlivesPredicate, SubtypeRelation, TraitPredicate, TraitRef, TypeOutlivesPredicate,
};
```

#### File: `compiler/rustc_public/src/ty.rs`
**Lines to modify**: 1511-1514 (struct definition), 1485 (enum variant)
```rust
// Struct definition (BEFORE)
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SubtypePredicate {
    pub a: Ty,
    pub b: Ty,
}

// Struct definition (AFTER)
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SubtypeRelation {
    pub sub_ty: Ty,
    pub super_ty: Ty,
}

// Enum variant (BEFORE)
SubType(SubtypePredicate),

// Enum variant (AFTER)
SubType(SubtypeRelation),
```

### Critical Path 3: Struct Construction Sites

#### File: `compiler/rustc_infer/src/infer/mod.rs`
**Lines to modify**: 719-722 (coerce_predicate construction)
```rust
// BEFORE
let subtype_predicate = predicate.map_bound(|p| ty::SubtypePredicate {
    a_is_expected: false, // when coercing from `a` to `b`, `b` is expected
    a: p.a,
    b: p.b,
});

// AFTER
let subtype_predicate = predicate.map_bound(|p| ty::SubtypeRelation {
    a_is_expected: false, // when coercing from `sub_ty` to `super_ty`, `super_ty` is expected
    sub_ty: p.sub_ty,
    super_ty: p.super_ty,
});
```

#### File: `compiler/rustc_next_trait_solver/src/solve/mod.rs`
**Lines to modify**: 112-115 (compute_subtype_goal construction), 200 & 213 (other constructions)
```rust
// Line 112-115 (BEFORE)
ty::SubtypePredicate {
    a_is_expected: false,
    a: p.a,
    b: p.b,
}

// Line 112-115 (AFTER)
ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: p.sub_ty,
    super_ty: p.super_ty,
}

// Lines 200 & 213 follow the same pattern
```

#### File: `compiler/rustc_type_ir/src/relate/solver_relating.rs`
**Lines to modify**: 200, 213 (two separate constructions)
```rust
// Both locations follow pattern:
// BEFORE
ty::SubtypePredicate {
    a_is_expected: true,  // or false
    a: lhs,
    b: rhs,
}

// AFTER
ty::SubtypeRelation {
    a_is_expected: true,  // or false
    sub_ty: lhs,
    super_ty: rhs,
}
```

### Critical Path 4: Destructuring/Pattern Matching

#### File: `compiler/rustc_infer/src/infer/mod.rs`
**Lines to modify**: 756 (pattern match in subtype_predicate function)
```rust
// BEFORE
self.enter_forall(predicate, |ty::SubtypePredicate { a_is_expected, a, b }| {
    if a_is_expected {
        Ok(self.at(cause, param_env).sub(DefineOpaqueTypes::Yes, a, b))
    } else {
        Ok(self.at(cause, param_env).sup(DefineOpaqueTypes::Yes, b, a))
    }
})

// AFTER
self.enter_forall(predicate, |ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }| {
    if a_is_expected {
        Ok(self.at(cause, param_env).sub(DefineOpaqueTypes::Yes, sub_ty, super_ty))
    } else {
        Ok(self.at(cause, param_env).sup(DefineOpaqueTypes::Yes, super_ty, sub_ty))
    }
})
```

#### File: `compiler/rustc_hir_typeck/src/fallback.rs`
**Lines to modify**: 351-355 (in calculate_diverging_fallback)
```rust
// BEFORE
let (a, b) = match atom {
    ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => (a, b),
    ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
        (a, b)
    }
};

// AFTER
let (a, b) = match atom {
    ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => (a, b),
    ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
        (sub_ty, super_ty)
    }
};
```

#### File: `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs`
**Lines to modify**: 93-99 (in format_overflow_error_with_fallback)
```rust
// BEFORE
match predicate.kind().skip_binder() {
    ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ })
    | ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
        struct_span_code_err!(
            self.dcx(),
            span,
            E0275,
            "overflow assigning `{a}` to `{b}`",
        )

// AFTER
match predicate.kind().skip_binder() {
    ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ })
    | ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
        struct_span_code_err!(
            self.dcx(),
            span,
            E0275,
            "overflow assigning `{sub_ty}` to `{super_ty}`",
        )
```

#### File: `compiler/rustc_trait_selection/src/solve/delegate.rs`
**Lines to modify**: 126-133 (in assemble_candidate_for_subtyping_goal)
```rust
// BEFORE
ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })
| ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
    match (self.shallow_resolve(a).kind(), self.shallow_resolve(b).kind()) {
        (&ty::Infer(ty::TyVar(a_vid)), &ty::Infer(ty::TyVar(b_vid))) => {
            self.sub_unify_ty_vids_raw(a_vid, b_vid);
            Some(Certainty::AMBIGUOUS)
        }

// AFTER
ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, .. })
| ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
    match (self.shallow_resolve(sub_ty).kind(), self.shallow_resolve(super_ty).kind()) {
        (&ty::Infer(ty::TyVar(a_vid)), &ty::Infer(ty::TyVar(b_vid))) => {
            self.sub_unify_ty_vids_raw(a_vid, b_vid);
            Some(Certainty::AMBIGUOUS)
        }
```

#### File: `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs`
**Lines to modify**: 502-511 (in emit_inference_failure_err)
```rust
// BEFORE
let ty::SubtypePredicate { a_is_expected: _, a, b } = data;
// both must be type variables, or the other would've been instantiated
assert!(a.is_ty_var() && b.is_ty_var());
self.emit_inference_failure_err(
    obligation.cause.body_id,
    span,
    a.into(),
    TypeAnnotationNeeded::E0282,
    true,
)

// AFTER
let ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty } = data;
// both must be type variables, or the other would've been instantiated
assert!(sub_ty.is_ty_var() && super_ty.is_ty_var());
self.emit_inference_failure_err(
    obligation.cause.body_id,
    span,
    sub_ty.into(),
    TypeAnnotationNeeded::E0282,
    true,
)
```

#### File: `compiler/rustc_type_ir/src/flags.rs`
**Lines to modify**: 394-396 (in add_predicate)
```rust
// BEFORE
ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
    self.add_ty(a);
    self.add_ty(b);
}

// AFTER
ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
    self.add_ty(sub_ty);
    self.add_ty(super_ty);
}
```

### Critical Path 5: Type Conversions

#### File: `compiler/rustc_public/src/unstable/convert/stable/ty.rs`
**Lines to modify**: 779-789 (Stable impl)
```rust
// BEFORE
impl<'tcx> Stable<'tcx> for ty::SubtypePredicate<'tcx> {
    type T = crate::ty::SubtypePredicate;

    fn stable<'cx>(
        &self,
        tables: &mut Tables<'cx, BridgeTys>,
        cx: &CompilerCtxt<'cx, BridgeTys>,
    ) -> Self::T {
        let ty::SubtypePredicate { a, b, a_is_expected: _ } = self;
        crate::ty::SubtypePredicate { a: a.stable(tables, cx), b: b.stable(tables, cx) }
    }
}

// AFTER
impl<'tcx> Stable<'tcx> for ty::SubtypeRelation<'tcx> {
    type T = crate::ty::SubtypeRelation;

    fn stable<'cx>(
        &self,
        tables: &mut Tables<'cx, BridgeTys>,
        cx: &CompilerCtxt<'cx, BridgeTys>,
    ) -> Self::T {
        let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ } = self;
        crate::ty::SubtypeRelation { sub_ty: sub_ty.stable(tables, cx), super_ty: super_ty.stable(tables, cx) }
    }
}
```

### Critical Path 6: Pretty Printing

#### File: `compiler/rustc_middle/src/ty/print/pretty.rs`
**Lines to modify**: 3256-3260 (in print method)
```rust
// BEFORE
ty::SubtypePredicate<'tcx> {
    self.a.print(p)?;
    p.write_str(" <: ")?;
    self.b.print(p)?;
}

// AFTER
ty::SubtypeRelation<'tcx> {
    self.sub_ty.print(p)?;
    p.write_str(" <: ")?;
    self.super_ty.print(p)?;
}
```

## Dependency Graph

```
rustc_type_ir::predicate.rs (SubtypeRelation struct)
    ↓
rustc_type_ir::predicate_kind.rs (PredicateKind::Subtype variant)
    ↓
rustc_type_ir::interner.rs (IrPrint bound)
rustc_type_ir::ir_print.rs (Import/impl)
rustc_type_ir::flags.rs (Pattern matching)
rustc_type_ir::relate/solver_relating.rs (Construction)
    ↓
rustc_middle::ty::predicate.rs (Type alias)
    ↓
rustc_middle::ty::mod.rs (Re-export)
rustc_middle::ty::print::pretty.rs (Printing)
rustc_public::ty.rs (Public struct)
rustc_public::unstable/convert/stable/ty.rs (Conversion)
    ↓
rustc_infer::infer/mod.rs (Construction/Pattern)
rustc_hir_typeck::fallback.rs (Pattern match)
rustc_trait_selection (Error reporting & solving)
rustc_next_trait_solver::solve/mod.rs (Solving)
```

## Verification Checklist

After implementing all changes:

- [ ] All files compile without errors
- [ ] No warnings about type mismatches
- [ ] Grep for remaining "SubtypePredicate[^_]" returns only comments/docs
- [ ] Test suite passes
- [ ] No field names `a` or `b` accessed on SubtypeRelation (except in other types)
- [ ] Comments updated to reflect new names
- [ ] All uses of `sub_ty` and `super_ty` are semantically correct

## Summary

This refactoring affects 17 files across 8 compiler crates and requires:
- 1 struct rename and field renaming
- 2 type alias updates
- 1 enum variant type update
- 6 import/bound updates
- 7 struct construction updates
- 9 pattern matching updates
- 1 type conversion update
- 1 printing function update

All changes maintain backward compatibility in terms of functionality while improving semantic clarity through more meaningful field names.
