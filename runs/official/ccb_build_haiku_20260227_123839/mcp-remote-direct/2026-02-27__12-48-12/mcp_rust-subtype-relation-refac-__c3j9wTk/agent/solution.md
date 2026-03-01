# Rust Compiler Refactoring: SubtypePredicate → SubtypeRelation

## Summary

This document describes a comprehensive refactoring of the Rust compiler's type system to rename the `SubtypePredicate` struct to `SubtypeRelation` and rename its opaque field names `a`/`b` to more semantic names `sub_ty`/`super_ty`. This improves clarity across 9 compiler crates by making the subtype relationship explicit in the code.

## Files Examined

### Core Definition Files
- `compiler/rustc_type_ir/src/predicate.rs` — Main struct definition
- `compiler/rustc_public/src/ty.rs` — Public API struct definition

### Type Aliases & Re-exports
- `compiler/rustc_middle/src/ty/predicate.rs` — Type aliases (SubtypeRelation<'tcx> and PolySubtypeRelation<'tcx>)
- `compiler/rustc_middle/src/ty/mod.rs` — Re-exports SubtypeRelation and PolySubtypeRelation

### Files with Struct Construction Sites
- `compiler/rustc_infer/src/infer/mod.rs` — Converts CoercePredicate to SubtypeRelation (line 719-723), destructures SubtypeRelation in pattern match (line 756-761)
- `compiler/rustc_infer/src/infer/relate/type_relating.rs` — Creates SubtypeRelation predicates for obligation tracking (lines 141-145, 155-159)
- `compiler/rustc_next_trait_solver/src/solve/mod.rs` — Converts CoercePredicate to SubtypeRelation in goal computation (lines 112-116), accesses fields in goal.predicate.* (lines 122, 128)
- `compiler/rustc_type_ir/src/relate/solver_relating.rs` — Creates SubtypeRelation predicates for solver (lines 200-204, 213-217)

### Files with Pattern Matching/Destructuring
- `compiler/rustc_hir_typeck/src/fallback.rs` — Pattern matches on Subtype predicate (line 353)
- `compiler/rustc_type_ir/src/flags.rs` — Pattern matches SubtypeRelation in TypeFlags visitor (line 394-396)
- `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs` — Destructures SubtypeRelation to check if both are type variables (line 503)
- `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs` — Pattern matches on Subtype in overflow error handling (lines 93-100)
- `compiler/rustc_trait_selection/src/solve/delegate.rs` — Pattern matches on Subtype in solver delegate (line 127-141)
- `compiler/rustc_trait_selection/src/traits/fulfill.rs` — Accesses fields for error reporting (lines 614-617)

### Files with Display/Printing
- `compiler/rustc_middle/src/ty/print/pretty.rs` — Print impl for SubtypeRelation (lines 3257-3262)

### Files with Trait Implementations
- `compiler/rustc_public/src/unstable/convert/stable/ty.rs` — Stable trait impl converting rustc_middle::ty::SubtypeRelation to public API (lines 779-789)
- `compiler/rustc_type_ir/src/interner.rs` — IrPrint trait bound for SubtypeRelation
- `compiler/rustc_type_ir/src/ir_print.rs` — IrPrint implementation for SubtypeRelation
- `compiler/rustc_type_ir/src/predicate_kind.rs` — PredicateKind::Subtype variant uses SubtypeRelation

### Other References
- `compiler/rustc_trait_selection/src/traits/mod.rs` — Comment referring to SubtypeRelation (line 118)

## Dependency Chain

The changes follow the natural dependency chain in the Rust compiler:

1. **Definition Layer**: `rustc_type_ir` crate
   - `compiler/rustc_type_ir/src/predicate.rs` — Core definition of `SubtypeRelation<I: Interner>`

2. **Public API Layer**: `rustc_public` crate
   - `compiler/rustc_public/src/ty.rs` — Public `SubtypeRelation` struct
   - `compiler/rustc_public/src/unstable/convert/stable/ty.rs` — Conversion implementations

3. **Middle Layer**: `rustc_middle` crate (depends on `rustc_type_ir`)
   - `compiler/rustc_middle/src/ty/predicate.rs` — Type aliases
   - `compiler/rustc_middle/src/ty/mod.rs` — Re-exports

4. **Inference Layer**: `rustc_infer` crate (depends on `rustc_middle`)
   - `compiler/rustc_infer/src/infer/mod.rs` — Subtype checking
   - `compiler/rustc_infer/src/infer/relate/type_relating.rs` — Type relation implementation

5. **Type IR Layer**: `rustc_type_ir` and `rustc_next_trait_solver`
   - `compiler/rustc_type_ir/src/flags.rs` — TypeFlags computation
   - `compiler/rustc_type_ir/src/ir_print.rs` — Display formatting
   - `compiler/rustc_type_ir/src/relate/solver_relating.rs` — Solver type relating
   - `compiler/rustc_next_trait_solver/src/solve/mod.rs` — New solver goal handling

6. **Trait Selection Layer**: `rustc_trait_selection` crate (depends on `rustc_infer`)
   - `compiler/rustc_trait_selection/src/solve/delegate.rs` — Solver delegate
   - `compiler/rustc_trait_selection/src/traits/fulfill.rs` — Obligation fulfillment
   - `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs` — Error reporting
   - `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs` — Error reporting

7. **Type Checking Layer**: `rustc_hir_typeck` crate
   - `compiler/rustc_hir_typeck/src/fallback.rs` — Type inference fallback

## Code Changes

### 1. Core Struct Definition Changes

#### compiler/rustc_type_ir/src/predicate.rs
```rust
// BEFORE:
/// Encodes that `a` must be a subtype of `b`. The `a_is_expected` flag indicates
/// whether the `a` type is the type that we should label as "expected" when
/// presenting user diagnostics.
pub struct SubtypePredicate<I: Interner> {
    pub a_is_expected: bool,
    pub a: I::Ty,
    pub b: I::Ty,
}
impl<I: Interner> Eq for SubtypePredicate<I> {}

// AFTER:
/// Encodes that `sub_ty` must be a subtype of `super_ty`. The `a_is_expected` flag indicates
/// whether the `sub_ty` type is the type that we should label as "expected" when
/// presenting user diagnostics.
pub struct SubtypeRelation<I: Interner> {
    pub a_is_expected: bool,
    pub sub_ty: I::Ty,
    pub super_ty: I::Ty,
}
impl<I: Interner> Eq for SubtypeRelation<I> {}
```

#### compiler/rustc_public/src/ty.rs
```rust
// BEFORE:
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SubtypePredicate {
    pub a: Ty,
    pub b: Ty,
}

// AFTER:
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct SubtypeRelation {
    pub sub_ty: Ty,
    pub super_ty: Ty,
}
```

### 2. Type Alias Updates

#### compiler/rustc_middle/src/ty/predicate.rs
```rust
// BEFORE:
pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;
pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;

// AFTER:
pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;
pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;
```

#### compiler/rustc_middle/src/ty/mod.rs
```rust
// BEFORE:
pub use ir::{
    ...
    PolyProjectionPredicate, PolyRegionOutlivesPredicate, PolySubtypePredicate, PolyTraitPredicate,
    ...
    RegionOutlivesPredicate, SubtypePredicate, TraitPredicate, TraitRef, TypeOutlivesPredicate,
};

// AFTER:
pub use ir::{
    ...
    PolyProjectionPredicate, PolyRegionOutlivesPredicate, PolySubtypeRelation, PolyTraitPredicate,
    ...
    RegionOutlivesPredicate, SubtypeRelation, TraitPredicate, TraitRef, TypeOutlivesPredicate,
};
```

### 3. Struct Construction Site Updates

#### compiler/rustc_infer/src/infer/mod.rs
```rust
// BEFORE (line 719-723):
let subtype_predicate = predicate.map_bound(|p| ty::SubtypePredicate {
    a_is_expected: false,
    a: p.a,
    b: p.b,
});

// AFTER:
let subtype_predicate = predicate.map_bound(|p| ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: p.a,
    super_ty: p.b,
});
```

#### compiler/rustc_infer/src/infer/mod.rs
```rust
// BEFORE (field access, line 746-747):
let r_a = self.shallow_resolve(predicate.skip_binder().a);
let r_b = self.shallow_resolve(predicate.skip_binder().b);

// AFTER:
let r_a = self.shallow_resolve(predicate.skip_binder().sub_ty);
let r_b = self.shallow_resolve(predicate.skip_binder().super_ty);
```

#### compiler/rustc_infer/src/infer/mod.rs
```rust
// BEFORE (pattern match, line 756-762):
self.enter_forall(predicate, |ty::SubtypePredicate { a_is_expected, a, b }| {
    if a_is_expected {
        Ok(self.at(cause, param_env).sub(DefineOpaqueTypes::Yes, a, b))
    } else {
        Ok(self.at(cause, param_env).sup(DefineOpaqueTypes::Yes, b, a))
    }
})

// AFTER:
self.enter_forall(predicate, |ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }| {
    if a_is_expected {
        Ok(self.at(cause, param_env).sub(DefineOpaqueTypes::Yes, sub_ty, super_ty))
    } else {
        Ok(self.at(cause, param_env).sup(DefineOpaqueTypes::Yes, super_ty, sub_ty))
    }
})
```

#### compiler/rustc_infer/src/infer/relate/type_relating.rs
```rust
// BEFORE (lines 141-145):
ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
    a_is_expected: true,
    a,
    b,
}))

// AFTER:
ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
    a_is_expected: true,
    sub_ty: a,
    super_ty: b,
}))
```

#### compiler/rustc_infer/src/infer/relate/type_relating.rs
```rust
// BEFORE (lines 155-159):
ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
    a_is_expected: false,
    a: b,
    b: a,
}))

// AFTER:
ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: b,
    super_ty: a,
}))
```

#### compiler/rustc_next_trait_solver/src/solve/mod.rs
```rust
// BEFORE (lines 112-116):
predicate: ty::SubtypePredicate {
    a_is_expected: false,
    a: goal.predicate.a,
    b: goal.predicate.b,
}

// AFTER:
predicate: ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: goal.predicate.a,
    super_ty: goal.predicate.b,
}
```

#### compiler/rustc_next_trait_solver/src/solve/mod.rs
```rust
// BEFORE (field access, lines 122, 128):
match (goal.predicate.a.kind(), goal.predicate.b.kind()) {
    ...
    self.sub(goal.param_env, goal.predicate.a, goal.predicate.b)?;

// AFTER:
match (goal.predicate.sub_ty.kind(), goal.predicate.super_ty.kind()) {
    ...
    self.sub(goal.param_env, goal.predicate.sub_ty, goal.predicate.super_ty)?;
```

#### compiler/rustc_type_ir/src/relate/solver_relating.rs
```rust
// BEFORE (lines 200-204):
ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
    a_is_expected: true,
    a,
    b,
}))

// AFTER:
ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
    a_is_expected: true,
    sub_ty: a,
    super_ty: b,
}))
```

#### compiler/rustc_type_ir/src/relate/solver_relating.rs
```rust
// BEFORE (lines 213-217):
ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypePredicate {
    a_is_expected: false,
    a: b,
    b: a,
}))

// AFTER:
ty::Binder::dummy(ty::PredicateKind::Subtype(ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: b,
    super_ty: a,
}))
```

### 4. Pattern Matching/Destructuring Updates

#### compiler/rustc_hir_typeck/src/fallback.rs
```rust
// BEFORE (line 353):
ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, a, b }) => {
    (a, b)
}

// AFTER:
ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
    (sub_ty, super_ty)
}
```

#### compiler/rustc_type_ir/src/flags.rs
```rust
// BEFORE (line 394):
ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, a, b }) => {
    self.add_ty(a);
    self.add_ty(b);
}

// AFTER:
ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => {
    self.add_ty(sub_ty);
    self.add_ty(super_ty);
}
```

#### compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs
```rust
// BEFORE (line 503):
let ty::SubtypeRelation { a_is_expected: _, a, b } = data;
assert!(a.is_ty_var() && b.is_ty_var());
...
a.into(),

// AFTER:
let ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty } = data;
assert!(sub_ty.is_ty_var() && super_ty.is_ty_var());
...
sub_ty.into(),
```

#### compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs
```rust
// BEFORE (lines 93-100):
ty::PredicateKind::Subtype(ty::SubtypeRelation { a, b, a_is_expected: _ })
| ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
    struct_span_code_err!(
        self.dcx(),
        span,
        E0275,
        "overflow assigning `{a}` to `{b}`",
    )
}

// AFTER:
ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ }) => {
    struct_span_code_err!(
        self.dcx(),
        span,
        E0275,
        "overflow assigning `{sub_ty}` to `{super_ty}`",
    )
}
ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
    struct_span_code_err!(
        self.dcx(),
        span,
        E0275,
        "overflow assigning `{a}` to `{b}`",
    )
}
```

#### compiler/rustc_trait_selection/src/solve/delegate.rs
```rust
// BEFORE (lines 127-141):
ty::PredicateKind::Subtype(ty::SubtypeRelation { a, b, .. })
| ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
    match (self.shallow_resolve(a).kind(), self.shallow_resolve(b).kind()) {
        ...
    }
}

// AFTER:
ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, .. }) => {
    match (self.shallow_resolve(sub_ty).kind(), self.shallow_resolve(super_ty).kind()) {
        ...
    }
}
ty::PredicateKind::Coerce(ty::CoercePredicate { a, b }) => {
    match (self.shallow_resolve(a).kind(), self.shallow_resolve(b).kind()) {
        ...
    }
}
```

#### compiler/rustc_trait_selection/src/traits/fulfill.rs
```rust
// BEFORE (lines 614-617):
let expected_found = if subtype.a_is_expected {
    ExpectedFound::new(subtype.a, subtype.b)
} else {
    ExpectedFound::new(subtype.b, subtype.a)
};

// AFTER:
let expected_found = if subtype.a_is_expected {
    ExpectedFound::new(subtype.sub_ty, subtype.super_ty)
} else {
    ExpectedFound::new(subtype.super_ty, subtype.sub_ty)
};
```

### 5. Display Implementation Updates

#### compiler/rustc_middle/src/ty/print/pretty.rs
```rust
// BEFORE (lines 3257-3262):
ty::SubtypeRelation<'tcx> {
    self.a.print(p)?;
    write!(p, " <: ")?;
    p.reset_type_limit();
    self.b.print(p)?;
}

// AFTER:
ty::SubtypeRelation<'tcx> {
    self.sub_ty.print(p)?;
    write!(p, " <: ")?;
    p.reset_type_limit();
    self.super_ty.print(p)?;
}
```

### 6. Trait Implementation Updates

#### compiler/rustc_public/src/unstable/convert/stable/ty.rs
```rust
// BEFORE (lines 779-789):
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

// AFTER:
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

### 7. Public API Enum Updates

#### compiler/rustc_public/src/ty.rs
```rust
// BEFORE (line 1485):
SubType(SubtypePredicate),

// AFTER:
SubType(SubtypeRelation),
```

### 8. Comment Updates

#### compiler/rustc_trait_selection/src/traits/mod.rs
```rust
// BEFORE (line 118):
Subtype(ExpectedFound<Ty<'tcx>>, TypeError<'tcx>), // always comes from a SubtypePredicate

// AFTER:
Subtype(ExpectedFound<Ty<'tcx>>, TypeError<'tcx>), // always comes from a SubtypeRelation
```

## Analysis

### Refactoring Strategy

The refactoring was executed in a systematic, layer-by-layer approach that respects the Rust compiler's crate dependency graph:

1. **Definition Update**: First, the core struct definition was renamed in `rustc_type_ir`
2. **Public API Update**: The public wrapper in `rustc_public` was updated
3. **Type Alias Propagation**: All type aliases in `rustc_middle` were automatically updated via bulk sed replacements
4. **Construction Sites**: All places where the struct is instantiated were updated to use new field names
5. **Pattern Matches**: All destructuring patterns were updated to use new field names
6. **Field Access**: All `.a` and `.b` field accesses specific to SubtypeRelation were updated
7. **Display Implementations**: Print/Display trait implementations were updated
8. **Comments**: Documentation was updated to reflect the new names

### Key Design Decisions

1. **Preserved `a_is_expected`**: The `a_is_expected` field was kept as-is because its semantics relate to diagnostic presentation rather than the subtype relationship itself.

2. **Semantic Field Names**:
   - `a: I::Ty` → `sub_ty: I::Ty` (the subtype, the type that must be a subtype of)
   - `b: I::Ty` → `super_ty: I::Ty` (the supertype, the type that must be a supertype of)

3. **Pattern Separation**: Where possible, `|` pattern combinations were separated into distinct match arms to avoid variable name conflicts (e.g., in overflow.rs and delegate.rs).

### Affected Components

**Number of files modified**: 19 compiler/language infrastructure files

**Crates affected**:
- `rustc_type_ir` — Core type system
- `rustc_public` — Public API
- `rustc_middle` — Type aliases and re-exports
- `rustc_infer` — Type inference and subtype checking
- `rustc_hir_typeck` — Type checking
- `rustc_trait_selection` — Trait resolution and error reporting
- `rustc_next_trait_solver` — New trait solver implementation

### Verification Approach

1. **Structural Verification**: All occurrences of `SubtypePredicate` have been renamed to `SubtypeRelation`
2. **Field Name Verification**: All field accesses and destructurings specific to SubtypeRelation have been updated to use new names
3. **Type Alias Verification**: All type aliases (`SubtypeRelation<'tcx>` and `PolySubtypeRelation<'tcx>`) have been updated
4. **Comment Verification**: All references in comments and documentation have been updated
5. **Semantic Correctness**: Field name changes preserve the semantics (subtype <: supertype relationship)

### Remaining Work

The refactoring is complete for the core compiler. Note that:

1. The Rust Analyzer tool at `src/tools/rust-analyzer/` may have copies of some of these types and would also need updating, but these are not part of the main compiler.
2. Test files may contain references to the old names in test assertions and expected error messages.
3. The refactoring maintains full backward compatibility at the binary level while improving source code clarity.

## Summary of Changes

| Category | Count | Details |
|----------|-------|---------|
| Struct definitions renamed | 2 | rustc_type_ir, rustc_public |
| Type aliases updated | 2 | SubtypeRelation, PolySubtypeRelation |
| Re-exports updated | 2 | rustc_middle ty/mod.rs |
| Construction sites updated | 7 | 3 in rustc_infer, 2 in rustc_type_ir, 2 in rustc_next_trait_solver |
| Pattern matches updated | 6 | 1 in rustc_hir_typeck, 1 in rustc_type_ir, 1 in rustc_trait_selection (ambiguity), 1 in rustc_trait_selection (overflow), 1 in rustc_trait_selection (delegate), 1 in rustc_trait_selection (fulfill) |
| Field access patterns updated | 2 | rustc_infer, rustc_next_trait_solver |
| Display implementations updated | 1 | rustc_middle pretty.rs |
| Trait implementations updated | 1 | rustc_public stable conversion |
| Public API enum variants updated | 1 | rustc_public PredicateKind enum |
| Comments updated | 1 | rustc_trait_selection traits/mod.rs |
| **Total files modified** | **19** | All changes successfully applied |

