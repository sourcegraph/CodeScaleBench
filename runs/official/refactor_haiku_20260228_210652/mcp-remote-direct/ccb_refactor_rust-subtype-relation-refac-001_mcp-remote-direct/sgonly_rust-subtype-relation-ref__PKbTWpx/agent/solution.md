# SubtypePredicate → SubtypeRelation Refactoring Analysis

## Overview
This refactoring renames the `SubtypePredicate` struct to `SubtypeRelation` and its fields `a`/`b` to `sub_ty`/`super_ty` across the Rust compiler, improving semantic clarity.

## Files Examined

### Definition Files (Primary)
- **compiler/rustc_type_ir/src/predicate.rs** — Main struct definition with Interner trait
  - Line 918-922: `pub struct SubtypePredicate<I: Interner>` with fields `a_is_expected: bool`, `a: I::Ty`, `b: I::Ty`
  - Needs: Rename struct to `SubtypeRelation`, rename fields `a` → `sub_ty`, `b` → `super_ty`
  - Line 924: Eq impl for `SubtypePredicate<I>` needs update

- **compiler/rustc_public/src/ty.rs** — Public-facing struct definition
  - Line 1511-1514: `pub struct SubtypePredicate` with fields `a: Ty`, `b: Ty`
  - Needs: Rename struct to `SubtypeRelation`, rename fields similarly
  - Line 1485: Used in `PredicateKind::SubType(SubtypePredicate)` enum variant

### Type Aliases (rustc_middle)
- **compiler/rustc_middle/src/ty/predicate.rs**
  - Line 24: `pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;` → change to `ir::SubtypeRelation`
  - Line 32: `pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;` → update alias name

- **compiler/rustc_middle/src/ty/mod.rs**
  - Line 94: Re-export in public module (`SubtypePredicate` and `PolySubtypePredicate` in prelude)

### Trait and Type Definitions
- **compiler/rustc_type_ir/src/predicate_kind.rs**
  - Line 78: `Subtype(ty::SubtypePredicate<I>)` variant in `PredicateKind` enum
  - Needs: Update type annotation to `ty::SubtypeRelation<I>`

- **compiler/rustc_type_ir/src/interner.rs**
  - Line 31: `+ IrPrint<ty::SubtypePredicate<Self>>` bound in trait definition
  - Needs: Update to `IrPrint<ty::SubtypeRelation<Self>>`

- **compiler/rustc_type_ir/src/ir_print.rs**
  - Line 6: Import of `SubtypePredicate` in module
  - Line 54: Listed in trait impl list
  - Needs: Update imports and trait impl list

### Usage Sites - Construction
- **compiler/rustc_infer/src/infer/mod.rs**
  - Line 719: `ty::SubtypePredicate { a_is_expected: false, a: p.a, b: p.b }`
  - Line 756: Pattern match destructuring `|ty::SubtypePredicate { a_is_expected, a, b }|`
  - Needs: Update struct name and field names in both construction and pattern match

- **compiler/rustc_next_trait_solver/src/solve/mod.rs**
  - Line 112-115: Struct literal creation `ty::SubtypePredicate { a_is_expected: false, ... }`
  - Line 121: Function signature with `Goal<I, ty::SubtypePredicate<I>>`
  - Line 122: Pattern accessing `.a` and `.b` fields
  - Needs: Update all field accesses

- **compiler/rustc_type_ir/src/relate/solver_relating.rs**
  - Line 200, 213: Struct literal creation with `ty::SubtypePredicate { a_is_expected, a, b }`
  - Needs: Update struct name and field names

### Usage Sites - Destructuring/Pattern Matching
- **compiler/rustc_hir_typeck/src/fallback.rs**
  - Line 353-354: Pattern match `| ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) =>`
  - Needs: Update struct name and field names in pattern

- **compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs**
  - Line 93: Pattern match with struct destructuring
  - Needs: Update field accesses

- **compiler/rustc_trait_selection/src/solve/delegate.rs**
  - Line 127: Pattern match `| ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })`
  - Needs: Update struct name and field names

- **compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs**
  - Line 503: Pattern match `let ty::SubtypePredicate { a_is_expected: _, a, b } = data;`
  - Needs: Update struct name and field names

- **compiler/rustc_type_ir/src/flags.rs**
  - Line 394: Pattern match accessing `.a` and `.b` fields
  - Needs: Update field names to `.sub_ty` and `.super_ty`

### Type Conversion
- **compiler/rustc_public/src/unstable/convert/stable/ty.rs**
  - Line 779-789: Stable trait impl for `ty::SubtypePredicate<'tcx>`
  - Line 787: Pattern match `let ty::SubtypePredicate { a, b, a_is_expected: _ } = self;`
  - Line 788: Construction of public `SubtypePredicate { a:..., b:... }`
  - Needs: Update struct name, field names in pattern, and field names in construction

### Pretty Printing
- **compiler/rustc_middle/src/ty/print/pretty.rs**
  - Line 3257: Print impl for `ty::SubtypePredicate<'tcx>` - pattern matching field names
  - Needs: Update field name `.a` to `.sub_ty`

## Dependency Chain

### 1. Definition: rustc_type_ir/src/predicate.rs
   - Defines `SubtypeRelation<I: Interner>` struct
   - Required by: PredicateKind enum variant type

### 2. Direct Dependencies: Type Aliases
   - **rustc_middle/src/ty/predicate.rs**: Type alias for `SubtypeRelation<'tcx>`
   - **rustc_public/src/ty.rs**: Public struct definition
   - These provide type-safe shortcuts for usage sites

### 3. Trait Bounds
   - **rustc_type_ir/src/interner.rs**: IrPrint trait bound
   - **rustc_type_ir/src/ir_print.rs**: Concrete impl marker
   - These ensure printing support

### 4. PredicateKind Variant
   - **rustc_type_ir/src/predicate_kind.rs**: `Subtype(SubtypeRelation<I>)` variant
   - Used by all sites that create/match this predicate kind

### 5. Usage Sites (Transitive Dependencies)
   - rustc_infer (type checking & inference)
   - rustc_hir_typeck (HIR type checking)
   - rustc_trait_selection (trait solving & error reporting)
   - rustc_next_trait_solver (new trait solver)
   - rustc_type_ir/relate (type relation solving)

## Code Changes

### Change 1: rustc_type_ir/src/predicate.rs
```diff
-/// Encodes that `a` must be a subtype of `b`. The `a_is_expected` flag indicates
-/// whether the `a` type is the type that we should label as "expected" when
+/// Encodes that `sub_ty` must be a subtype of `super_ty`. The `a_is_expected` flag indicates
+/// whether the `sub_ty` type is the type that we should label as "expected" when
 /// presenting user diagnostics.
 #[derive_where(Clone, Copy, Hash, PartialEq, Debug; I: Interner)]
 #[derive(TypeVisitable_Generic, TypeFoldable_Generic, Lift_Generic)]
@@ -918,9 +918,9 @@ pub struct HostEffectPredicate<I: Interner> {
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

### Change 2: rustc_public/src/ty.rs
```diff
 #[derive(Clone, Debug, Eq, PartialEq, Serialize)]
-pub struct SubtypePredicate {
-    pub a: Ty,
-    pub b: Ty,
+pub struct SubtypeRelation {
+    pub sub_ty: Ty,
+    pub super_ty: Ty,
 }

 #[derive(Clone, Debug, Eq, PartialEq, Serialize)]
```

And in the PredicateKind enum:
```diff
     SubType(SubtypeRelation),
```

### Change 3: rustc_middle/src/ty/predicate.rs
```diff
 pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;
 pub type OutlivesPredicate<'tcx, T> = ir::OutlivesPredicate<TyCtxt<'tcx>, T>;
 pub type RegionOutlivesPredicate<'tcx> = OutlivesPredicate<'tcx, ty::Region<'tcx>>;
 pub type TypeOutlivesPredicate<'tcx> = OutlivesPredicate<'tcx, Ty<'tcx>>;
 pub type ArgOutlivesPredicate<'tcx> = OutlivesPredicate<'tcx, ty::GenericArg<'tcx>>;
 pub type PolyTraitPredicate<'tcx> = ty::Binder<'tcx, TraitPredicate<'tcx>>;
 pub type PolyRegionOutlivesPredicate<'tcx> = ty::Binder<'tcx, RegionOutlivesPredicate<'tcx>>;
 pub type PolyTypeOutlivesPredicate<'tcx> = ty::Binder<'tcx, TypeOutlivesPredicate<'tcx>>;
-pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;
+pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;
```

### Change 4: rustc_middle/src/ty/mod.rs
Re-export the new names in the prelude:
```diff
 pub use self::predicate::{
     Clause, ClauseKind, DynCompatible, HostEffectPredicate, NormalizesTo, OutlivesPredicate,
-    PolyCoercePredicate, PolyExistentialPredicate, PolyExistentialProjection, PolyExistentialTraitRef,
-    PolyProjectionPredicate, PolyRegionOutlivesPredicate, PolySubtypePredicate, PolyTraitPredicate,
-    PolyTraitRef, PolyTypeOutlivesPredicate, Predicate, PredicateKind, ProjectionPredicate,
-    RegionOutlivesPredicate, SubtypePredicate, TraitPredicate, TraitRef, TypeOutlivesPredicate,
+    PolyCoercePredicate, PolyExistentialPredicate, PolyExistentialProjection, PolyExistentialTraitRef,
+    PolyProjectionPredicate, PolyRegionOutlivesPredicate, PolySubtypeRelation, PolyTraitPredicate,
+    PolyTraitRef, PolyTypeOutlivesPredicate, Predicate, PredicateKind, ProjectionPredicate,
+    RegionOutlivesPredicate, SubtypeRelation, TraitPredicate, TraitRef, TypeOutlivesPredicate,
```

### Change 5: rustc_type_ir/src/predicate_kind.rs
```diff
     /// information to process the subtyping obligation yet.
-    Subtype(ty::SubtypePredicate<I>),
+    Subtype(ty::SubtypeRelation<I>),
```

### Change 6: rustc_type_ir/src/interner.rs
```diff
     + IrPrint<ty::ExistentialProjection<Self>>
     + IrPrint<ty::ProjectionPredicate<Self>>
     + IrPrint<ty::NormalizesTo<Self>>
-    + IrPrint<ty::SubtypePredicate<Self>>
+    + IrPrint<ty::SubtypeRelation<Self>>
     + IrPrint<ty::CoercePredicate<Self>>
```

### Change 7: rustc_type_ir/src/ir_print.rs
```diff
 use crate::{
     AliasTerm, AliasTy, Binder, ClosureKind, CoercePredicate, ExistentialProjection,
-    ExistentialTraitRef, FnSig, HostEffectPredicate, Interner, NormalizesTo, OutlivesPredicate,
-    PatternKind, ProjectionPredicate, SubtypePredicate, TraitPredicate, TraitRef, UnevaluatedConst,
+    ExistentialTraitRef, FnSig, HostEffectPredicate, Interner, NormalizesTo, OutlivesPredicate,
+    PatternKind, ProjectionPredicate, SubtypeRelation, TraitPredicate, TraitRef, UnevaluatedConst,
 };

 ...
-    SubtypePredicate,
+    SubtypeRelation,
```

### Change 8: rustc_infer/src/infer/mod.rs
```diff
         let subtype_predicate = predicate.map_bound(|p| ty::SubtypePredicate {
             a_is_expected: false, // when coercing from `a` to `b`, `b` is expected
-            a: p.a,
-            b: p.b,
+            sub_ty: p.sub_ty,
+            super_ty: p.super_ty,

         self.enter_forall(predicate, |ty::SubtypePredicate { a_is_expected, a, b }| {
             if a_is_expected {
-                Ok(self.at(cause, param_env).sub(DefineOpaqueTypes::Yes, a, b))
+                Ok(self.at(cause, param_env).sub(DefineOpaqueTypes::Yes, sub_ty, super_ty))
             } else {
-                Ok(self.at(cause, param_env).sup(DefineOpaqueTypes::Yes, b, a))
+                Ok(self.at(cause, param_env).sup(DefineOpaqueTypes::Yes, super_ty, sub_ty))
```

### Change 9: rustc_next_trait_solver/src/solve/mod.rs
```diff
-            ty::SubtypePredicate {
+            ty::SubtypeRelation {
                 a_is_expected: false,
-                a: p.a,
-                b: p.b,
+                sub_ty: p.sub_ty,
+                super_ty: p.super_ty,

-    fn compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypePredicate<I>>) -> QueryResult<I> {
-        match (goal.predicate.a.kind(), goal.predicate.b.kind()) {
+    fn compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypeRelation<I>>) -> QueryResult<I> {
+        match (goal.predicate.sub_ty.kind(), goal.predicate.super_ty.kind()) {
```

### Change 10: rustc_type_ir/src/relate/solver_relating.rs
```diff
-                ty::SubtypePredicate {
+                ty::SubtypeRelation {
                     a_is_expected: true,
-                    a: lhs,
-                    b: rhs,
+                    sub_ty: lhs,
+                    super_ty: rhs,

-                ty::SubtypePredicate {
+                ty::SubtypeRelation {
                     a_is_expected: false,
-                    a: rhs,
-                    b: lhs,
+                    sub_ty: rhs,
+                    super_ty: lhs,
```

### Change 11: rustc_hir_typeck/src/fallback.rs
```diff
                     ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => (a, b),
-                    ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
+                    ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
-                        (a, b)
+                        (sub_ty, super_ty)
```

### Change 12: rustc_trait_selection/src/error_reporting/traits/overflow.rs
```diff
                     ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ })
+                    ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ })
                     | ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
                         struct_span_code_err!(
                             self.dcx(),
                             span,
                             E0275,
-                            "overflow assigning `{a}` to `{b}`",
+                            "overflow assigning `{sub_ty}` to `{super_ty}`",
```

### Change 13: rustc_trait_selection/src/solve/delegate.rs
```diff
             ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })
+             ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, .. })
             | ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
-                match (self.shallow_resolve(a).kind(), self.shallow_resolve(b).kind()) {
+                match (self.shallow_resolve(sub_ty).kind(), self.shallow_resolve(super_ty).kind()) {
```

### Change 14: rustc_trait_selection/src/error_reporting/traits/ambiguity.rs
```diff
-                let ty::SubtypePredicate { a_is_expected: _, a, b } = data;
+                let ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty } = data;
```

### Change 15: rustc_type_ir/src/flags.rs
```diff
-            ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
-                self.add_ty(a);
-                self.add_ty(b);
+            ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
+                self.add_ty(sub_ty);
+                self.add_ty(super_ty);
```

### Change 16: rustc_public/src/unstable/convert/stable/ty.rs
```diff
-impl<'tcx> Stable<'tcx> for ty::SubtypePredicate<'tcx> {
-    type T = crate::ty::SubtypePredicate;
+impl<'tcx> Stable<'tcx> for ty::SubtypeRelation<'tcx> {
+    type T = crate::ty::SubtypeRelation;

     fn stable<'cx>(
         &self,
         tables: &mut Tables<'cx, BridgeTys>,
         cx: &CompilerCtxt<'cx, BridgeTys>,
     ) -> Self::T {
-        let ty::SubtypePredicate { a, b, a_is_expected: _ } = self;
-        crate::ty::SubtypePredicate { a: a.stable(tables, cx), b: b.stable(tables, cx) }
+        let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ } = self;
+        crate::ty::SubtypeRelation { sub_ty: sub_ty.stable(tables, cx), super_ty: super_ty.stable(tables, cx) }
```

### Change 17: rustc_middle/src/ty/print/pretty.rs
```diff
-    ty::SubtypePredicate<'tcx> {
-        self.a.print(p)?;
+    ty::SubtypeRelation<'tcx> {
+        self.sub_ty.print(p)?;
         p.write_str(" <: ")?;
-        self.b.print(p)?;
+        self.super_ty.print(p)?;
```

## Analysis

### Refactoring Strategy
1. **Phase 1 - Core Definition**: Update struct definitions in rustc_type_ir and rustc_public
2. **Phase 2 - Type Aliases**: Update all type alias declarations in rustc_middle
3. **Phase 3 - Trait Bounds**: Update IrPrint bounds and imports
4. **Phase 4 - PredicateKind**: Update enum variant type annotation
5. **Phase 5 - Usage Sites**: Systematically update construction sites (struct literals)
6. **Phase 6 - Pattern Matching**: Systematically update destructuring patterns
7. **Phase 7 - Re-exports**: Update module-level re-exports and visibility
8. **Phase 8 - Integration**: Verification across all affected crates

### Scope Complexity
- **Total files affected**: 17
- **Affected crates**: 8 (rustc_type_ir, rustc_public, rustc_middle, rustc_infer, rustc_hir_typeck, rustc_trait_selection, rustc_next_trait_solver)
- **Pattern changes required**: 30+ locations
- **Risk factors**: High interdependency on type system, potential for cascading compilation errors if any location is missed

### Verification Approach
1. **Compilation**: Run `cargo check -p rustc_type_ir` followed by affected crate checks
2. **Reference Search**: Post-refactoring grep to ensure no stale references remain
3. **Test Suite**: Run test suite to verify semantic preservation
4. **Symbol Resolution**: Verify all type aliases resolve correctly

### Notes
- The `a_is_expected` field is retained as-is (not renamed) to maintain semantic clarity that it refers to the subtype's "expected" status
- Comments are updated to reflect the new field names
- The refactoring preserves all type safety guarantees and derives
- All visibility modifiers and accessibility remain unchanged
