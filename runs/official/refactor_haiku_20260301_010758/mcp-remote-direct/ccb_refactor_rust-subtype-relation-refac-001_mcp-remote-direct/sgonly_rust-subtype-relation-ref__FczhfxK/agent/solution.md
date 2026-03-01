# SubtypePredicate → SubtypeRelation Refactoring - Complete Analysis

## Executive Summary

This refactoring renames `SubtypePredicate` to `SubtypeRelation` and renames its fields `a` → `sub_ty` and `b` → `super_ty` across 13 core files in the Rust compiler to improve semantic clarity. The change affects type system definitions, predicate handling, and error reporting across 9 compiler crates.

---

## Files Examined

### 1. Core Definition Files (Must Change First)
- **compiler/rustc_type_ir/src/predicate.rs** — Original struct definition: `pub struct SubtypePredicate<I: Interner>` with fields `a_is_expected`, `a`, `b`
- **compiler/rustc_public/src/ty.rs** — Public API mirror: simplified `pub struct SubtypePredicate` with fields `a`, `b`
- **compiler/rustc_middle/src/ty/predicate.rs** — Type aliases: `SubtypePredicate<'tcx>` and `PolySubtypePredicate<'tcx>`
- **compiler/rustc_type_ir/src/predicate_kind.rs** — Enum variant: `PredicateKind::Subtype(ty::SubtypePredicate<I>)`

### 2. Pattern Matching/Destructuring Sites (All Usages Must Update)
- **compiler/rustc_infer/src/infer/mod.rs** — Lines 719-723, 746-747, 756-759
  - Conversion from `CoercePredicate`, field access via `.a`/`.b`, destructuring in closures
- **compiler/rustc_type_ir/src/flags.rs** — Line 394
  - Pattern match: `SubtypePredicate { a_is_expected: _, a, b }`
- **compiler/rustc_hir_typeck/src/fallback.rs** — Line 353
  - Pattern match: `SubtypePredicate { a_is_expected: _, a, b }`
- **compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs** — Line 93
  - Pattern match: `SubtypePredicate { a, b, a_is_expected: _ }`
- **compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs** — Line 503
  - Destructuring: `let ty::SubtypePredicate { a_is_expected: _, a, b } = data;`
- **compiler/rustc_next_trait_solver/src/solve/mod.rs** — Lines 112-115, 121-128
  - Construction with struct literal, field access `.a`/`.b`
- **compiler/rustc_type_ir/src/relate/solver_relating.rs** — Lines 200-203, 213-216
  - Construction with variance-based field ordering
- **compiler/rustc_infer/src/infer/relate/type_relating.rs** — Lines 141-145, 155-159
  - Construction with variance-based field ordering (Covariant vs Contravariant)

### 3. Display/Printing Implementations
- **compiler/rustc_middle/src/ty/print/pretty.rs** — Lines 3257-3262
  - Prints fields `self.a` and `self.b` with `<:` operator

### 4. Supporting Infrastructure (Re-exports, Traits, Bounds)
- **compiler/rustc_type_ir/src/interner.rs** — Trait bounds referencing `SubtypePredicate`
- **compiler/rustc_type_ir/src/ir_print.rs** — Print trait bounds for `SubtypePredicate`
- **compiler/rustc_middle/src/ty/mod.rs** — Re-exports from rustc_type_ir

---

## Dependency Chain

### Layer 1: Definitions (Foundation)
1. `compiler/rustc_type_ir/src/predicate.rs` (Generic `SubtypePredicate<I>`)
2. `compiler/rustc_public/src/ty.rs` (Public API version)
3. `compiler/rustc_type_ir/src/predicate_kind.rs` (Uses in `PredicateKind::Subtype`)

### Layer 2: Type Aliases & Re-exports (Convenience)
4. `compiler/rustc_middle/src/ty/predicate.rs` (Aliases for `'tcx` version)
5. `compiler/rustc_middle/src/ty/mod.rs` (Re-exports public definitions)

### Layer 3: Trait Bounds & Infrastructure
6. `compiler/rustc_type_ir/src/interner.rs` (IrPrint bounds)
7. `compiler/rustc_type_ir/src/ir_print.rs` (Printing trait definitions)

### Layer 4: Usage Sites (All must update field names)
8. `compiler/rustc_infer/src/infer/mod.rs` (Type inference, field access)
9. `compiler/rustc_type_ir/src/flags.rs` (Type flags computation)
10. `compiler/rustc_hir_typeck/src/fallback.rs` (Coercion graph)
11. `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs` (Error reporting)
12. `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs` (Ambiguity handling)
13. `compiler/rustc_next_trait_solver/src/solve/mod.rs` (Next-gen trait solver)
14. `compiler/rustc_type_ir/src/relate/solver_relating.rs` (Type relating, variance)
15. `compiler/rustc_infer/src/infer/relate/type_relating.rs` (Type relating, variance)
16. `compiler/rustc_middle/src/ty/print/pretty.rs` (Display implementation)

---

## Code Changes Required

### Change Type Summary
- **Struct/Type Name Changes**: 2 (in two locations: rustc_type_ir, rustc_public)
- **Field Name Changes**: 4+ per file × 13-16 files (all destructuring and construction sites)
- **Type Alias Updates**: 2 (names stay same, struct name changes)
- **Pattern Match Updates**: 8 files with pattern matching expressions
- **Constructor Call Updates**: 6 files with struct construction

### Change Pattern Categories

#### Pattern 1: Struct Definition (2 files)
```diff
# OLD:
pub struct SubtypePredicate<I: Interner> {
    pub a_is_expected: bool,
    pub a: I::Ty,
    pub b: I::Ty,
}

# NEW:
pub struct SubtypeRelation<I: Interner> {
    pub a_is_expected: bool,
    pub sub_ty: I::Ty,
    pub super_ty: I::Ty,
}
```

#### Pattern 2: Pattern Matching (8 files)
```diff
# OLD:
let ty::SubtypePredicate { a_is_expected, a, b } = ...;

# NEW:
let ty::SubtypeRelation { a_is_expected, sub_ty, super_ty } = ...;
```

#### Pattern 3: Field Construction (6 files)
```diff
# OLD:
ty::SubtypePredicate {
    a_is_expected: false,
    a: some_type,
    b: other_type,
}

# NEW:
ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: some_type,
    super_ty: other_type,
}
```

#### Pattern 4: Field Access (4 files)
```diff
# OLD:
let r_a = self.shallow_resolve(predicate.skip_binder().a);
let r_b = self.shallow_resolve(predicate.skip_binder().b);

# NEW:
let r_a = self.shallow_resolve(predicate.skip_binder().sub_ty);
let r_b = self.shallow_resolve(predicate.skip_binder().super_ty);
```

#### Pattern 5: Display/Printing (1 file)
```diff
# OLD:
ty::SubtypePredicate<'tcx> {
    self.a.print(p)?;
    write!(p, " <: ")?;
    p.reset_type_limit();
    self.b.print(p)?;
}

# NEW:
ty::SubtypeRelation<'tcx> {
    self.sub_ty.print(p)?;
    write!(p, " <: ")?;
    p.reset_type_limit();
    self.super_ty.print(p)?;
}
```

---

## Analysis: Refactoring Strategy

### Why This Change?
The current naming (`a` and `b`) is semantically opaque. The new naming (`sub_ty` for subtype, `super_ty` for supertype) immediately clarifies that:
- `sub_ty <: super_ty` (subtype relation)
- The `a_is_expected` flag controls which is presented as "expected" in diagnostics
- This matches the documentation: "Encodes that `a` must be a subtype of `b`" — but now it's explicit in code

### Affected Crates (9 total)
1. `rustc_type_ir` — Core type IR definitions
2. `rustc_public` — Public API layer
3. `rustc_middle` — Mid-level type system
4. `rustc_infer` — Type inference engine
5. `rustc_type_ir` (relate module) — Type relation algorithms
6. `rustc_hir_typeck` — HIR type checking
7. `rustc_trait_selection` — Trait solver and error reporting
8. `rustc_next_trait_solver` — Next-generation solver
9. (Implicit) All downstream users get the new names via re-exports

### Scope & Complexity
- **Total files to modify**: 13 core files + supporting infrastructure
- **Line count affected**: ~25 distinct code sections
- **Breaking changes**: None within the same crate (all internal to Rust compiler)
- **Cross-crate impact**: Minimal — mostly internal compiler-only APIs
- **Test coverage**: Existing tests validate functionality; naming changes don't alter logic

### Verification Approach
1. **Compilation check**: `cargo check` on affected crates
2. **Type safety**: Rust compiler ensures all pattern matches are exhaustive
3. **Functional tests**: Existing test suite validates behavior
4. **Grep verification**: Search for residual `SubtypePredicate` (should only find in Subtype variant name or comments)

---

## Implementation Notes

### Field Renaming Rationale
- `a` → `sub_ty`: The type that must be a **sub**type
- `b` → `super_ty`: The type that must be a **super**type
- `a_is_expected` → (unchanged): Flag controlling diagnostic presentation, distinct semantic meaning

### Variance-Based Field Swapping
Files `type_relating.rs` and `solver_relating.rs` have special handling:
```rust
// Contravariant case swaps the fields:
ty::SubtypeRelation { a_is_expected: false, sub_ty: b, super_ty: a }
```
This is intentional and correct — contravariance reverses the subtype relationship. Verify comments are preserved.

### Enum Variant Name
The `PredicateKind::Subtype` variant **name stays as-is** (only the struct type inside changes). This is intentional because:
- The variant name `Subtype` is a semantic label (not a struct name)
- Only the type parameter changes: `PredicateKind::Subtype(SubtypeRelation<I>)` vs `PredicateKind::Subtype(SubtypePredicate<I>)`

---

## Complete Code Changes

### 1. compiler/rustc_type_ir/src/predicate.rs (Lines 909-924)

```diff
-/// Encodes that `a` must be a subtype of `b`. The `a_is_expected` flag indicates
-/// whether the `a` type is the type that we should label as "expected" when
+/// Encodes that `sub_ty` must be a subtype of `super_ty`. The `a_is_expected` flag indicates
+/// whether the `sub_ty` type is the type that we should label as "expected" when
 /// presenting user diagnostics.
 #[derive_where(Clone, Copy, Hash, PartialEq, Debug; I: Interner)]
 #[derive(TypeVisitable_Generic, TypeFoldable_Generic, Lift_Generic)]
 #[cfg_attr(
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

### 2. compiler/rustc_public/src/ty.rs (Lines 1510-1513)

```diff
-#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
-pub struct SubtypePredicate {
-    pub a: Ty,
-    pub b: Ty,
+#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
+pub struct SubtypeRelation {
+    pub sub_ty: Ty,
+    pub super_ty: Ty,
 }
```

### 3. compiler/rustc_middle/src/ty/predicate.rs (Lines 24, 32)

```diff
-pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;
+pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;
```

```diff
-pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;
+pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;
 pub type PolyCoercePredicate<'tcx> = ty::Binder<'tcx, CoercePredicate<'tcx>>;
```

**Note**: Update all references to `PolySubtypePredicate` to `PolySubtypeRelation` throughout compiler

### 4. compiler/rustc_type_ir/src/predicate_kind.rs (Line 78)

```diff
     /// This obligation is created most often when we have two
     /// unresolved type variables and hence don't have enough
     /// information to process the subtyping obligation yet.
-    Subtype(ty::SubtypePredicate<I>),
+    Subtype(ty::SubtypeRelation<I>),
```

### 5. compiler/rustc_infer/src/infer/mod.rs

```diff
# Lines 719-723:
-        let subtype_predicate = predicate.map_bound(|p| ty::SubtypePredicate {
+        let subtype_predicate = predicate.map_bound(|p| ty::SubtypeRelation {
             a_is_expected: false, // when coercing from `a` to `b`, `b` is expected
-            a: p.a,
-            b: p.b,
+            sub_ty: p.sub_ty,
+            super_ty: p.super_ty,
         });

# Lines 746-747:
-        let r_a = self.shallow_resolve(predicate.skip_binder().a);
-        let r_b = self.shallow_resolve(predicate.skip_binder().b);
+        let r_a = self.shallow_resolve(predicate.skip_binder().sub_ty);
+        let r_b = self.shallow_resolve(predicate.skip_binder().super_ty);

# Lines 756-759:
-        self.enter_forall(predicate, |ty::SubtypePredicate { a_is_expected, a, b }| {
+        self.enter_forall(predicate, |ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }| {
             if a_is_expected {
-                Ok(self.at(cause, param_env).sub(DefineOpaqueTypes::Yes, a, b))
+                Ok(self.at(cause, param_env).sub(DefineOpaqueTypes::Yes, sub_ty, super_ty))
             } else {
-                Ok(self.at(cause, param_env).sup(DefineOpaqueTypes::Yes, b, a))
+                Ok(self.at(cause, param_env).sup(DefineOpaqueTypes::Yes, super_ty, sub_ty))
             }
         })
```

### 6. compiler/rustc_type_ir/src/flags.rs (Line 394)

```diff
-            ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
+            ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
-                self.add_ty(a);
-                self.add_ty(b);
+                self.add_ty(sub_ty);
+                self.add_ty(super_ty);
```

### 7. compiler/rustc_hir_typeck/src/fallback.rs (Line 353)

```diff
-                    ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => {
+                    ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
-                        (a, b)
+                        (sub_ty, super_ty)
```

### 8. compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs (Line 93)

```diff
-                    ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ })
+                    ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ })
-                    | ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
+                    | ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
```

### 9. compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs (Line 503)

```diff
-                let ty::SubtypePredicate { a_is_expected: _, a, b } = data;
+                let ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty } = data;
```

### 10. compiler/rustc_next_trait_solver/src/solve/mod.rs

```diff
# Lines 112-115:
                 predicate: ty::SubtypeRelation {
                     a_is_expected: false,
-                    a: goal.predicate.a,
-                    b: goal.predicate.b,
+                    sub_ty: goal.predicate.sub_ty,
+                    super_ty: goal.predicate.super_ty,
                 },

# Lines 121-128:
-    fn compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypePredicate<I>>) -> QueryResult<I> {
-        match (goal.predicate.a.kind(), goal.predicate.b.kind()) {
+    fn compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypeRelation<I>>) -> QueryResult<I> {
+        match (goal.predicate.sub_ty.kind(), goal.predicate.super_ty.kind()) {
```

### 11. compiler/rustc_type_ir/src/relate/solver_relating.rs

```diff
# Lines 200-203:
                             self.param_env,
-                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
+                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
                                 a_is_expected: true,
-                                a,
-                                b,
+                                sub_ty: a,
+                                super_ty: b,

# Lines 213-216:
                             self.param_env,
-                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
+                            ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
                                 a_is_expected: false,
-                                a: b,
-                                b: a,
+                                sub_ty: b,
+                                super_ty: a,
```

### 12. compiler/rustc_infer/src/infer/relate/type_relating.rs

Similar changes to solver_relating.rs at lines 141-145 and 155-159

### 13. compiler/rustc_middle/src/ty/print/pretty.rs (Lines 3257-3262)

```diff
-    ty::SubtypePredicate<'tcx> {
-        self.a.print(p)?;
+    ty::SubtypeRelation<'tcx> {
+        self.sub_ty.print(p)?;
         write!(p, " <: ")?;
         p.reset_type_limit();
-        self.b.print(p)?;
+        self.super_ty.print(p)?;
     }
```

### Global Replacements Needed

**In multiple files** (interner.rs, ir_print.rs, mod.rs):
- Replace all `SubtypePredicate` with `SubtypeRelation` (struct name references)
- Keep `PolySubtypePredicate` → `PolySubtypeRelation` for type aliases
- Keep `PredicateKind::Subtype` variant name (only the type parameter changes)

---

## Files Requiring Changes - Complete Checklist

- [x] Core definitions prepared (4 files: predicate.rs, ty.rs in public, predicate.rs in middle, predicate_kind.rs)
- [ ] `compiler/rustc_infer/src/infer/mod.rs` (5 occurrences: construction + field access + destructuring)
- [ ] `compiler/rustc_type_ir/src/flags.rs` (1 occurrence: pattern match)
- [ ] `compiler/rustc_hir_typeck/src/fallback.rs` (1 occurrence: pattern match)
- [ ] `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs` (1 occurrence: pattern match)
- [ ] `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs` (1 occurrence: destructuring)
- [ ] `compiler/rustc_next_trait_solver/src/solve/mod.rs` (3 occurrences: construction + field access)
- [ ] `compiler/rustc_type_ir/src/relate/solver_relating.rs` (2 occurrences: construction with variance)
- [ ] `compiler/rustc_infer/src/infer/relate/type_relating.rs` (2 occurrences: construction with variance)
- [ ] `compiler/rustc_middle/src/ty/print/pretty.rs` (1 occurrence: field access in printing)
- [ ] Supporting files (interner.rs, ir_print.rs, mod.rs)

**Total: 13 files, ~25 code sections**

---

## Expected Outcome

After this refactoring:
1. The struct is named `SubtypeRelation<I>` instead of `SubtypePredicate<I>`
2. Fields are `sub_ty` and `super_ty` instead of `a` and `b`
3. All pattern matches, destructuring, and field accesses are updated
4. The code compiles without errors
5. All existing tests pass (behavior unchanged, only naming improved)
6. Documentation comments and variant names remain appropriate
