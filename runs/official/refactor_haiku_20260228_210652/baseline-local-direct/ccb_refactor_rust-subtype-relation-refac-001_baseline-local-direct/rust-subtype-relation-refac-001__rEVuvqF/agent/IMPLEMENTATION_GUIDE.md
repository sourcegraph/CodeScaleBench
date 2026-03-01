# SubtypePredicate → SubtypeRelation Refactoring - Implementation Guide

Due to file permissions (files owned by root), the automated refactoring scripts cannot be run directly. This document provides a complete, manual implementation guide showing exactly what to change in each file.

## Prerequisites

```bash
cd /workspace
git config user.email "test@test.com"
git config user.name "Refactoring Bot"
```

## File-by-File Changes

### File 1: compiler/rustc_type_ir/src/predicate.rs

**Lines 909-924** - Replace entire block:

```diff
-/// Encodes that `a` must be a subtype of `b`. The `a_is_expected` flag indicates
-/// whether the `a` type is the type that we should label as "expected" when
+/// Encodes that `sub_ty` must be a subtype of `super_ty`. The `a_is_expected` flag indicates
+/// whether the `sub_ty` type is the type that we should label as "expected" when
 /// presenting user diagnostics.
 #[derive_where(Clone, Copy, Hash, PartialEq, Debug; I: Interner)]
 #[derive(TypeVisitable_Generic, TypeFoldable_Generic, Lift_Generic)]
@@ -918,12 +918,12 @@ impl<I: Interner> Eq for OutlivesPredicate<I, A> {}
     feature = "nightly",
     derive(Decodable_NoContext, Encodable_NoContext, HashStable_NoContext)
 )]
-pub struct SubtypePredicate<I: Interner> {
+pub struct SubtypeRelation<I: Interner> {
     pub a_is_expected: bool,
-    pub a: I::Ty,
-    pub b: I::Ty,
+    pub sub_ty: I::Ty,
+    pub super_ty: I::Ty,
 }

-impl<I: Interner> Eq for SubtypePredicate<I> {}
+impl<I: Interner> Eq for SubtypeRelation<I> {}
```

### File 2: compiler/rustc_type_ir/src/predicate_kind.rs

**Line 78** - Replace:

```diff
-    Subtype(ty::SubtypePredicate<I>),
+    Subtype(ty::SubtypeRelation<I>),
```

### File 3: compiler/rustc_type_ir/src/ir_print.rs

**Line 6** - Replace import:

```diff
 use crate::{
     AliasTerm, AliasTy, Binder, ClosureKind, CoercePredicate, ExistentialProjection,
-    ExistentialTraitRef, FnSig, HostEffectPredicate, Interner, NormalizesTo, OutlivesPredicate,
-    PatternKind, ProjectionPredicate, SubtypePredicate, TraitPredicate, TraitRef, UnevaluatedConst,
+    ExistentialTraitRef, FnSig, HostEffectPredicate, Interner, NormalizesTo, OutlivesPredicate,
+    PatternKind, ProjectionPredicate, SubtypeRelation, TraitPredicate, TraitRef, UnevaluatedConst,
 };
```

**Line 16** (in impl list) - Replace:

```diff
     TraitPredicate,
     ExistentialTraitRef,
     ExistentialProjection,
     ProjectionPredicate,
     NormalizesTo,
-    SubtypePredicate,
+    SubtypeRelation,
     CoercePredicate,
```

### File 4: compiler/rustc_type_ir/src/interner.rs

**IrPrint bound** - Replace:

```diff
-    + IrPrint<ty::SubtypePredicate<Self>>
+    + IrPrint<ty::SubtypeRelation<Self>>
```

### File 5: compiler/rustc_type_ir/src/flags.rs

**Line 394** - Replace pattern:

```diff
-            ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
+            ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
```

If there are references to `a` and `b` after this pattern, update them:
```diff
-                a.visit_with(visitor) || b.visit_with(visitor)
+                sub_ty.visit_with(visitor) || super_ty.visit_with(visitor)
```

### File 6: compiler/rustc_type_ir/src/relate/solver_relating.rs

**Lines 200, 213** - Replace constructor calls:

```diff
-                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
+                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
-                                a_is_expected: true,
+                                a_is_expected: true,
-                                a: self_ty,
-                                b: other,
+                                sub_ty: self_ty,
+                                super_ty: other,
```

### File 7: compiler/rustc_middle/src/ty/predicate.rs

**Line 24** - Replace:

```diff
-pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;
+pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;
```

**Line 32** - Replace:

```diff
-pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;
+pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;
```

### File 8: compiler/rustc_middle/src/ty/mod.rs

**In the pub use block** - Replace:

```diff
- PolySubtypePredicate,
+ PolySubtypeRelation,
 ...
- SubtypePredicate,
+ SubtypeRelation,
```

### File 9: compiler/rustc_middle/src/ty/print/pretty.rs

**In the Display impl** - Replace pattern matching:

```diff
-    ty::SubtypePredicate<'tcx> { a, b, a_is_expected }
+    ty::SubtypeRelation<'tcx> { sub_ty, super_ty, a_is_expected }
```

And update any references to use new field names:
```diff
-         write!(f, "{{ {} <: {} }}", a, b)
+         write!(f, "{{ {} <: {} }}", sub_ty, super_ty)
```

### File 10: compiler/rustc_trait_selection/src/solve/delegate.rs

**Line 127** - Replace:

```diff
-            ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })
+            ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, .. })
```

Update references:
```diff
-                Goal::new(cx, [goal.param_env.and((a, b))])
+                Goal::new(cx, [goal.param_env.and((sub_ty, super_ty))])
```

### File 11: compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs

**Line 93** - Replace:

```diff
-                    ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ }) => {
+                    ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ }) => {
```

Update references:
```diff
-                        ExpectedFound::new(a, b)
+                        ExpectedFound::new(sub_ty, super_ty)
```

### File 12: compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs

**Line 503** - Replace:

```diff
-                let ty::SubtypePredicate { a_is_expected: _, a, b } = data;
+                let ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty } = data;
```

Update references:
```diff
-                    ExpectedFound::new(a, b)
+                    ExpectedFound::new(sub_ty, super_ty)
```

### File 13: compiler/rustc_trait_selection/src/traits/mod.rs

**In doc comments** - Replace:

```diff
-    /// always comes from a SubtypePredicate
+    /// always comes from a SubtypeRelation
```

### File 14: compiler/rustc_infer/src/infer/mod.rs

**Line 719** - Replace constructor:

```diff
-        let subtype_predicate = predicate.map_bound(|p| ty::SubtypePredicate {
-            a_is_expected,
-            a: a_expected,
-            b: b_actual,
+        let subtype_predicate = predicate.map_bound(|p| ty::SubtypeRelation {
+            a_is_expected,
+            sub_ty: a_expected,
+            super_ty: b_actual,
```

**Function signature** - Replace:

```diff
-        predicate: ty::PolySubtypePredicate<'tcx>,
+        predicate: ty::PolySubtypeRelation<'tcx>,
```

**Line 756** - Replace pattern match:

```diff
-        self.enter_forall(predicate, |ty::SubtypePredicate { a_is_expected, a, b }| {
+        self.enter_forall(predicate, |ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }| {
```

Update references in the closure:
```diff
-            self.sub(a, b, a_is_expected)
+            self.sub(sub_ty, super_ty, a_is_expected)
```

### File 15: compiler/rustc_infer/src/infer/relate/type_relating.rs

**Lines 141, 155** - Replace constructors:

```diff
-                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
-                                a: self_ty,
-                                b: other,
+                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
+                                sub_ty: self_ty,
+                                super_ty: other,
```

### File 16: compiler/rustc_hir_typeck/src/fallback.rs

**Line 353** - Replace:

```diff
-                    ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
+                    ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
```

Update references:
```diff
-                        ty::relate::ExpectedFound::new(a, b)
+                        ty::relate::ExpectedFound::new(sub_ty, super_ty)
```

### File 17: compiler/rustc_next_trait_solver/src/solve/mod.rs

**Line 112** - Replace:

```diff
-            predicate: ty::SubtypePredicate {
-                a_is_expected,
-                a: lhs,
-                b: rhs,
+            predicate: ty::SubtypeRelation {
+                a_is_expected,
+                sub_ty: lhs,
+                super_ty: rhs,
```

**Function signature** - Replace:

```diff
-    fn compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypePredicate<I>>) -> QueryResult<I> {
+    fn compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypeRelation<I>>) -> QueryResult<I> {
```

### File 18: compiler/rustc_public/src/ty.rs

**Line 1485** - Replace:

```diff
-    SubType(SubtypePredicate),
+    SubType(SubtypeRelation),
```

**Lines 1511-1514** - Replace struct:

```diff
-pub struct SubtypePredicate {
-    pub a: Ty,
-    pub b: Ty,
+pub struct SubtypeRelation {
+    pub sub_ty: Ty,
+    pub super_ty: Ty,
```

### File 19: compiler/rustc_public/src/unstable/convert/stable/ty.rs

**Lines 779-788** - Replace impl:

```diff
-impl<'tcx> Stable<'tcx> for ty::SubtypePredicate<'tcx> {
-    type T = crate::ty::SubtypePredicate;
+impl<'tcx> Stable<'tcx> for ty::SubtypeRelation<'tcx> {
+    type T = crate::ty::SubtypeRelation;
     fn stable(
         &self,
         tables: &mut Tables<'_, BridgeTys>,
         cx: &CompilerCtxt<'_, BridgeTys>,
     ) -> Self::T {
-        let ty::SubtypePredicate { a, b, a_is_expected: _ } = self;
-        crate::ty::SubtypePredicate { a: a.stable(tables, cx), b: b.stable(tables, cx) }
+        let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ } = self;
+        crate::ty::SubtypeRelation { sub_ty: sub_ty.stable(tables, cx), super_ty: super_ty.stable(tables, cx) }
```

## Verification Steps

After making all changes:

```bash
# 1. Check for compilation
cargo check --all 2>&1 | head -100

# 2. Look for any remaining old names
grep -r "SubtypePredicate" compiler/ --include="*.rs" | grep -v "^[[:space:]]*///" | head -20

# 3. Look for field accesses that might be wrong
grep -r "\.a\b\|\.b\b" compiler/ --include="*.rs" | grep -i "subtype\|predicate" | head -20

# 4. View your changes
git diff | head -200

# 5. Commit the changes
git commit -am "refactor: rename SubtypePredicate to SubtypeRelation with clearer field names"
```

## Manual Change Instructions

If you prefer to make the changes manually:

1. Open each file listed above
2. Find the specific line numbers or patterns mentioned
3. Replace the old code with the new code shown in the diffs
4. Save each file
5. Run the verification steps

## Expected Compilation

After all changes, you should see:
- No "SubtypePredicate" references (except in comments/docs)
- All field accesses use `sub_ty` and `super_ty` instead of `a` and `b`
- All struct constructors use the new field names
- All pattern matches updated
- All type aliases updated

## Files Modified Summary

| # | File | Changes |
|----|------|---------|
| 1 | rustc_type_ir/src/predicate.rs | Struct definition, field names, impl |
| 2 | rustc_type_ir/src/predicate_kind.rs | Enum variant type |
| 3 | rustc_type_ir/src/ir_print.rs | Imports |
| 4 | rustc_type_ir/src/interner.rs | Trait bounds |
| 5 | rustc_type_ir/src/flags.rs | Pattern matching |
| 6 | rustc_type_ir/src/relate/solver_relating.rs | Construction |
| 7 | rustc_middle/src/ty/predicate.rs | Type aliases |
| 8 | rustc_middle/src/ty/mod.rs | Re-exports |
| 9 | rustc_middle/src/ty/print/pretty.rs | Pattern matching |
| 10 | rustc_trait_selection/src/solve/delegate.rs | Pattern matching |
| 11 | rustc_trait_selection/src/error_reporting/traits/overflow.rs | Pattern matching |
| 12 | rustc_trait_selection/src/error_reporting/traits/ambiguity.rs | Pattern matching |
| 13 | rustc_trait_selection/src/traits/mod.rs | Doc comments |
| 14 | rustc_infer/src/infer/mod.rs | Construction, pattern matching |
| 15 | rustc_infer/src/infer/relate/type_relating.rs | Construction |
| 16 | rustc_hir_typeck/src/fallback.rs | Pattern matching |
| 17 | rustc_next_trait_solver/src/solve/mod.rs | Construction, function signature |
| 18 | rustc_public/src/ty.rs | Struct definition, enum variant |
| 19 | rustc_public/src/unstable/convert/stable/ty.rs | Stable impl |
