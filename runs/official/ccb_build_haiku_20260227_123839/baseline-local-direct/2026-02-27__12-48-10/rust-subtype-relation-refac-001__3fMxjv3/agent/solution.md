# Rust Compiler Refactoring: SubtypePredicate → SubtypeRelation

## Summary
This document provides a complete analysis of the refactoring needed to rename `SubtypePredicate` to `SubtypeRelation` and its fields `a`/`b` to `sub_ty`/`super_ty` throughout the Rust compiler. The refactoring improves semantic clarity by making field names explicit about their role in the subtype relation.

## Files Examined

### Core Definition Files
- **compiler/rustc_type_ir/src/predicate.rs** — Struct definition (lines 918-924): Contains the original `SubtypePredicate<I>` struct with fields `a_is_expected`, `a`, and `b`. **Needs change**: Rename struct and fields.
- **compiler/rustc_type_ir/src/predicate_kind.rs** — PredicateKind enum (line 78): `Subtype(ty::SubtypePredicate<I>)` variant definition. **Needs change**: Update type annotation to `SubtypeRelation`.

### Type Aliases (rustc_middle)
- **compiler/rustc_middle/src/ty/predicate.rs** (lines 24, 32): Type aliases that re-export from rustc_type_ir:
  - `pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;`
  - `pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;`
  - **Needs change**: Both need to be updated to use `SubtypeRelation`.

- **compiler/rustc_middle/src/ty/mod.rs** — Re-exports via pub use. **Needs change**: Update re-export statements.

### Struct Literal Construction Sites (Creating new instances)
- **compiler/rustc_type_ir/src/relate/solver_relating.rs**:
  - Lines 200-204: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: true, a, b })`
  - Lines 213-217: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: false, a: b, b: a })` (swapped)
  - **Needs change**: Update field names to `sub_ty` and `super_ty`.

- **compiler/rustc_infer/src/infer/relate/type_relating.rs**:
  - Lines 141-145: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: true, a, b })`
  - Lines 155-159: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: false, a: b, b: a })` (swapped)
  - **Needs change**: Update field names and comprehend swapped semantics.

- **compiler/rustc_next_trait_solver/src/solve/mod.rs**:
  - Struct literal construction with field assignments. **Needs change**: Update field names.

### Destructuring/Pattern Match Sites (Reading instances)
- **compiler/rustc_type_ir/src/flags.rs** (line 394):
  - `ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b })`
  - **Needs change**: Update to `{ a_is_expected: _, sub_ty, super_ty }`

- **compiler/rustc_trait_selection/src/solve/delegate.rs** (line 127):
  - `ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })`
  - **Needs change**: Update to `{ sub_ty, super_ty, .. }`

- **compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs** (line 93):
  - `ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ })`
  - **Needs change**: Update to `{ sub_ty, super_ty, a_is_expected: _ }`

- **compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs** (line 503):
  - `let ty::SubtypePredicate { a_is_expected: _, a, b } = data;`
  - **Needs change**: Update to `{ a_is_expected: _, sub_ty, super_ty }`

- **compiler/rustc_hir_typeck/src/fallback.rs**:
  - `ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b })`
  - **Needs change**: Update field names.

### Display/Printing Implementation
- **compiler/rustc_type_ir/src/ir_print.rs** (lines 6, 54):
  - Imports `SubtypePredicate` for the display macro. **Needs change**: Update import name.

- **compiler/rustc_middle/src/ty/print/pretty.rs** (line 3201):
  - Pattern match: `ty::PredicateKind::Subtype(predicate) => predicate.print(p)?`
  - This uses the Display implementation. **Needs change**: No source code change needed if the impl uses `fmt::Debug` or generic Display.

### Public API (rustc_public)
- **compiler/rustc_public/src/ty.rs**:
  - Contains public re-export of the struct. **Needs change**: Update struct name and field visibility.
  - Also has enum variant: `SubType(SubtypePredicate)` which should become `SubType(SubtypeRelation)`.

- **compiler/rustc_public/src/unstable/convert/stable/ty.rs**:
  - Lines for stable conversion: `impl<'tcx> Stable<'tcx> for ty::SubtypePredicate<'tcx>`
  - Destructuring: `let ty::SubtypePredicate { a, b, a_is_expected: _ } = self;`
  - Construction: `crate::ty::SubtypePredicate { a: a.stable(tables, cx), b: b.stable(tables, cx) }`
  - **Needs change**: Update struct name and field names.

### Trait Bounds and Generic Parameters
- **compiler/rustc_type_ir/src/interner.rs** (line 31):
  - Trait bound: `+ IrPrint<ty::SubtypePredicate<Self>>`
  - **Needs change**: Update to `IrPrint<ty::SubtypeRelation<Self>>`

### Supporting References (Comments)
- **compiler/rustc_trait_selection/src/traits/mod.rs** (line 118):
  - Comment: `// always comes from a SubtypePredicate`
  - **Needs change**: Update comment to reference `SubtypeRelation`.

## Dependency Chain

1. **Definition Layer**:
   - `rustc_type_ir::predicate::SubtypePredicate` (original definition)

2. **Type Alias Layer**:
   - `rustc_middle::ty::predicate::SubtypePredicate` (aliases `ir::SubtypePredicate`)
   - `rustc_middle::ty::predicate::PolySubtypePredicate` (wraps the alias)
   - `rustc_middle::ty` re-exports both aliases

3. **Public API Layer**:
   - `rustc_public::ty::SubtypePredicate` (mirrors the struct)
   - `rustc_public::ty::Subtype` (enum variant using the struct)
   - `rustc_public::unstable::convert::stable` (conversion implementations)

4. **User Crates**:
   - `rustc_infer`: Uses in type relating logic
   - `rustc_type_ir::relate::solver_relating`: Construction and pattern matching
   - `rustc_hir_typeck`: Pattern matching in fallback logic
   - `rustc_trait_selection`: Error reporting and delegate logic
   - `rustc_next_trait_solver`: Subtype goal computation

## Refactoring Details

### Changes Required

#### 1. Struct Rename and Field Rename (rustc_type_ir)
**File**: `compiler/rustc_type_ir/src/predicate.rs`

```rust
// OLD
pub struct SubtypePredicate<I: Interner> {
    pub a_is_expected: bool,
    pub a: I::Ty,
    pub b: I::Ty,
}

// NEW
pub struct SubtypeRelation<I: Interner> {
    pub a_is_expected: bool,
    pub sub_ty: I::Ty,
    pub super_ty: I::Ty,
}
```

#### 2. Type Alias Updates (rustc_middle)
**File**: `compiler/rustc_middle/src/ty/predicate.rs`

```rust
// OLD
pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;
pub type PolySubtypePredicate<'tcx> = ty::Binder<'tcx, SubtypePredicate<'tcx>>;

// NEW
pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;
pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;

// Keep old names as deprecated type aliases for compatibility:
pub type SubtypePredicate<'tcx> = SubtypeRelation<'tcx>;
pub type PolySubtypePredicate<'tcx> = PolySubtypeRelation<'tcx>;
```

#### 3. Enum Variant Update (rustc_type_ir)
**File**: `compiler/rustc_type_ir/src/predicate_kind.rs`

```rust
// OLD
Subtype(ty::SubtypePredicate<I>),

// NEW
Subtype(ty::SubtypeRelation<I>),
```

#### 4. Pattern Match Updates
All pattern matches that destructure the struct need field name updates:

```rust
// OLD
ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b }) => ...

// NEW
ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }) => ...
```

Note: In `solver_relating.rs` and `type_relating.rs`, where `a` and `b` are swapped to represent the semantic direction, the new code becomes clearer:
```rust
// OLD: Subtle - field names don't indicate semantic meaning
ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: false, a: b, b: a })

// NEW: Clear - we're constructing a relation where super_ty is the "from" and sub_ty is the "to"
ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: false, sub_ty: b, super_ty: a })
```

#### 5. Struct Literal Construction Updates
All locations creating new instances need field name updates:

```rust
// OLD
ty::SubtypePredicate { a_is_expected: true, a, b }

// NEW
ty::SubtypeRelation { a_is_expected: true, sub_ty, super_ty }
```

#### 6. Public API Updates (rustc_public)
**File**: `compiler/rustc_public/src/ty.rs`

```rust
// OLD
pub struct SubtypePredicate {
    pub a: Ty,
    pub b: Ty,
    pub a_is_expected: bool,
}

// NEW
pub struct SubtypeRelation {
    pub sub_ty: Ty,
    pub super_ty: Ty,
    pub a_is_expected: bool,
}

// Also update enum variant:
// OLD
pub enum PredicateKind {
    SubType(SubtypePredicate),
}

// NEW
pub enum PredicateKind {
    SubType(SubtypeRelation),
}
```

#### 7. Stable Conversion Updates (rustc_public)
**File**: `compiler/rustc_public/src/unstable/convert/stable/ty.rs`

```rust
// OLD
impl<'tcx> Stable<'tcx> for ty::SubtypePredicate<'tcx> {
    type T = crate::ty::SubtypePredicate;

    fn stable(&self, tables: &mut Tables<'tcx>, cx: &'tcx CodegenCx<'tcx, 'tcx>) -> Self::T {
        let ty::SubtypePredicate { a, b, a_is_expected: _ } = self;
        crate::ty::SubtypePredicate { a: a.stable(tables, cx), b: b.stable(tables, cx) }
    }
}

// NEW
impl<'tcx> Stable<'tcx> for ty::SubtypeRelation<'tcx> {
    type T = crate::ty::SubtypeRelation;

    fn stable(&self, tables: &mut Tables<'tcx>, cx: &'tcx CodegenCx<'tcx, 'tcx>) -> Self::T {
        let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ } = self;
        crate::ty::SubtypeRelation { sub_ty: sub_ty.stable(tables, cx), super_ty: super_ty.stable(tables, cx) }
    }
}
```

## Code Changes (Complete List)

### compiler/rustc_type_ir/src/predicate.rs
- Rename `SubtypePredicate` to `SubtypeRelation`
- Rename field `a` to `sub_ty`
- Rename field `b` to `super_ty`
- Update struct doc comment

### compiler/rustc_type_ir/src/predicate_kind.rs
- Update `Subtype(ty::SubtypePredicate<I>)` to `Subtype(ty::SubtypeRelation<I>)`

### compiler/rustc_type_ir/src/flags.rs
- Update pattern match: `{ a_is_expected: _, a, b }` → `{ a_is_expected: _, sub_ty, super_ty }`

### compiler/rustc_type_ir/src/relate/solver_relating.rs
- Lines 200-204: Update struct literal and field names
- Lines 213-217: Update struct literal, field names, and document the semantic swap

### compiler/rustc_type_ir/src/ir_print.rs
- Update import to use `SubtypeRelation`

### compiler/rustc_type_ir/src/interner.rs
- Update trait bound: `+ IrPrint<ty::SubtypeRelation<Self>>`

### compiler/rustc_middle/src/ty/predicate.rs
- Line 24: `pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;`
- Line 32: `pub type PolySubtypeRelation<'tcx> = ty::Binder<'tcx, SubtypeRelation<'tcx>>;`
- Add compatibility aliases (optional, for gradual migration)

### compiler/rustc_middle/src/ty/mod.rs
- Update re-export paths

### compiler/rustc_middle/src/ty/print/pretty.rs
- Update any references in display implementations (likely no changes needed if generic)

### compiler/rustc_infer/src/infer/relate/type_relating.rs
- Lines 141-145: Update struct literal and field names
- Lines 155-159: Update struct literal, field names, and document the semantic swap

### compiler/rustc_infer/src/infer/mod.rs
- Update any type references and pattern matches

### compiler/rustc_hir_typeck/src/fallback.rs
- Update pattern match to use new field names

### compiler/rustc_trait_selection/src/traits/mod.rs
- Update comment: `// always comes from a SubtypePredicate` → `// always comes from a SubtypeRelation`

### compiler/rustc_trait_selection/src/solve/delegate.rs
- Update pattern match: `{ a, b, .. }` → `{ sub_ty, super_ty, .. }`

### compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs
- Update pattern match: `{ a, b, a_is_expected: _ }` → `{ sub_ty, super_ty, a_is_expected: _ }`

### compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs
- Update pattern match: `{ a_is_expected: _, a, b }` → `{ a_is_expected: _, sub_ty, super_ty }`

### compiler/rustc_next_trait_solver/src/solve/mod.rs
- Update struct literal and field names

### compiler/rustc_public/src/ty.rs
- Rename `SubtypePredicate` to `SubtypeRelation`
- Rename fields `a` → `sub_ty`, `b` → `super_ty`
- Update enum variant: `SubType(SubtypeRelation)`

### compiler/rustc_public/src/unstable/convert/stable/ty.rs
- Update `impl Stable` block
- Update destructuring and construction with new field names

## Verification Steps

1. **Search for remaining old names**: After refactoring, grep for `SubtypePredicate` should find only:
   - Deprecated type aliases (if kept for compatibility)
   - Comments or documentation that mention the old name

2. **Pattern match completeness**: Ensure all `PredicateKind::Subtype(...)` patterns use the new field names

3. **Compilation**: The refactored code should compile without errors. Key checks:
   - All struct literals compile with new field names
   - All pattern matches extract the correct fields
   - Type aliases resolve correctly
   - Public API exports compile

4. **Field usage verification**: Run grep for the old field names `\.a` and `\.b` on subtype-related code to find any missed updates

5. **Test suite**: Run the compiler test suite to ensure semantic correctness is preserved

## Analysis

### Why This Refactoring Matters

The current field names `a` and `b` in `SubtypePredicate` are opaque and don't convey semantic meaning. The refactoring addresses this by:

1. **Clarity**: Field names `sub_ty` and `super_ty` explicitly describe what types are being compared in the subtype relation
2. **Correctness**: Developers can immediately understand that `sub_ty <: super_ty` (sub_ty is a subtype of super_ty)
3. **Reduced Bugs**: Less likely to accidentally swap the types when constructing or matching on the struct
4. **Better Maintenance**: Future developers reading the code will understand the semantics without needing to consult documentation

### Scope of Changes

The refactoring affects:
- **7 compiler crates**: rustc_type_ir, rustc_middle, rustc_infer, rustc_hir_typeck, rustc_trait_selection, rustc_next_trait_solver, rustc_public
- **17 files** across these crates
- **All usages**: struct definition, type aliases, pattern matches, struct literals, display implementations

### Semantic Preservation

The refactoring is purely a naming change with no semantic alterations:
- The `a_is_expected` field maintains its meaning and usage
- The type relation semantics (which type is a subtype of which) remain unchanged
- Cases where `a` and `b` are intentionally swapped maintain their correctness with the new field names

### Backward Compatibility Considerations

For external consumers of the public API:
- Old field names can be kept as deprecated aliases in `rustc_public`
- Type aliases in `rustc_middle` could maintain old names as deprecated synonyms
- This allows gradual migration for downstream tools that depend on the compiler API

## Recommended Implementation Order

1. Update the core struct definition in `rustc_type_ir/src/predicate.rs`
2. Update the enum variant in `rustc_type_ir/src/predicate_kind.rs`
3. Update type aliases in `rustc_middle/src/ty/predicate.rs`
4. Update all pattern matches (grep-driven updates)
5. Update all struct literals (grep-driven updates)
6. Update public API in `rustc_public`
7. Run full compiler test suite to verify correctness
8. Verify no stray references to old field names remain

