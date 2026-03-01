# SubtypePredicate → SubtypeRelation Refactoring Checklist

## Implementation Status

### Phase 1: Core Definitions ✅
- [x] `compiler/rustc_type_ir/src/predicate.rs` - Struct renamed to `SubtypeRelation`, fields renamed to `sub_ty`/`super_ty`
- [x] `compiler/rustc_middle/src/ty/predicate.rs` - Type alias updated to use `SubtypeRelation`

### Phase 2: Type Aliases and Re-exports (In Progress)
- [ ] `compiler/rustc_middle/src/ty/mod.rs` - Update re-exports in prelude
- [ ] `compiler/rustc_public/src/ty.rs` - Update public struct definition and enum variant

### Phase 3: Trait Bounds and Imports
- [ ] `compiler/rustc_type_ir/src/predicate_kind.rs` - Update `PredicateKind::Subtype` variant type
- [ ] `compiler/rustc_type_ir/src/interner.rs` - Update `IrPrint<ty::SubtypeRelation<Self>>` bound
- [ ] `compiler/rustc_type_ir/src/ir_print.rs` - Update imports and trait impl list

### Phase 4: Struct Construction Sites
Construction sites that create `SubtypeRelation` instances with field assignments:

- [ ] `compiler/rustc_infer/src/infer/mod.rs` (line 719)
  - Pattern: `ty::SubtypePredicate { a_is_expected: false, a: p.a, b: p.b }`
  - Update to: `ty::SubtypeRelation { a_is_expected: false, sub_ty: p.sub_ty, super_ty: p.super_ty }`

- [ ] `compiler/rustc_next_trait_solver/src/solve/mod.rs` (lines 112-115, 200, 213)
  - Pattern: `ty::SubtypePredicate { a_is_expected: ..., a: ..., b: ... }`
  - Update to: `ty::SubtypeRelation { a_is_expected: ..., sub_ty: ..., super_ty: ... }`

- [ ] `compiler/rustc_type_ir/src/relate/solver_relating.rs` (lines 200, 213)
  - Pattern: `ty::SubtypePredicate { a_is_expected, a, b }`
  - Update to: `ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }`

### Phase 5: Pattern Matching and Field Access
Pattern matching sites that destructure `SubtypeRelation`:

- [ ] `compiler/rustc_infer/src/infer/mod.rs` (line 756)
  - Pattern: `|ty::SubtypePredicate { a_is_expected, a, b }|`
  - Update to: `|ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }|`

- [ ] `compiler/rustc_hir_typeck/src/fallback.rs` (line 353-354)
  - Pattern: `| ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b })`
  - Update to: `| ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty })`

- [ ] `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs` (line 93)
  - Pattern: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, a_is_expected: _ })`
  - Update to: `ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ })`

- [ ] `compiler/rustc_trait_selection/src/solve/delegate.rs` (line 127)
  - Pattern: `| ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })`
  - Update to: `| ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, .. })`

- [ ] `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs` (line 503)
  - Pattern: `let ty::SubtypePredicate { a_is_expected: _, a, b } = data;`
  - Update to: `let ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty } = data;`

- [ ] `compiler/rustc_type_ir/src/flags.rs` (line 394)
  - Pattern: `ty::PredicateKind::Subtype(ty::SubtypePredicate { a_is_expected: _, a, b })`
  - Update to: `ty::PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty })`

### Phase 6: Type Conversions and Printing
- [ ] `compiler/rustc_public/src/unstable/convert/stable/ty.rs` (lines 779-789)
  - Stable impl for `ty::SubtypeRelation<'tcx>`
  - Update struct name and field names

- [ ] `compiler/rustc_middle/src/ty/print/pretty.rs` (line 3257+)
  - Print impl for `ty::SubtypeRelation<'tcx>`
  - Update field accesses from `.a` to `.sub_ty` and `.b` to `.super_ty`

## Verification Plan

### Step 1: Compile Individual Crates
```bash
# Compile rustc_type_ir first (the root definition)
cargo check -p rustc_type_ir 2>&1 | tee /tmp/rustc_type_ir_check.log

# Then compile dependent crates in order
cargo check -p rustc_middle 2>&1 | tee /tmp/rustc_middle_check.log
cargo check -p rustc_public 2>&1 | tee /tmp/rustc_public_check.log
cargo check -p rustc_infer 2>&1 | tee /tmp/rustc_infer_check.log
cargo check -p rustc_hir_typeck 2>&1 | tee /tmp/rustc_hir_typeck_check.log
cargo check -p rustc_trait_selection 2>&1 | tee /tmp/rustc_trait_selection_check.log
cargo check -p rustc_next_trait_solver 2>&1 | tee /tmp/rustc_next_trait_solver_check.log
```

### Step 2: Check for Stale References
```bash
# Search for any remaining "SubtypePredicate" references that should have been updated
grep -r "SubtypePredicate[^_]" compiler/rustc_type_ir --include="*.rs" | grep -v test
grep -r "SubtypePredicate[^_]" compiler/rustc_middle --include="*.rs" | grep -v test
grep -r "SubtypePredicate[^_]" compiler/rustc_public --include="*.rs" | grep -v test
grep -r "SubtypePredicate[^_]" compiler/rustc_infer --include="*.rs" | grep -v test
grep -r "SubtypePredicate[^_]" compiler/rustc_hir_typeck --include="*.rs" | grep -v test
grep -r "SubtypePredicate[^_]" compiler/rustc_trait_selection --include="*.rs" | grep -v test
```

### Step 3: Run Test Suite
```bash
# Run subset of tests relevant to type checking and inference
./x.py test compiler/rustc_type_ir --stage 1 2>&1 | tee /tmp/rustc_type_ir_tests.log
./x.py test compiler/rustc_middle --stage 1 2>&1 | tee /tmp/rustc_middle_tests.log
```

### Step 4: Manual Verification Checkpoints

1. **Struct Definition Check**
   - Verify `SubtypeRelation` struct exists in `rustc_type_ir/src/predicate.rs`
   - Verify fields are named `sub_ty` and `super_ty`
   - Verify `a_is_expected` field is preserved

2. **Type Alias Check**
   - Verify `SubtypeRelation<'tcx>` type alias in `rustc_middle/src/ty/predicate.rs`
   - Verify `PolySubtypeRelation<'tcx>` type alias exists

3. **PredicateKind Check**
   - Verify `PredicateKind::Subtype(ty::SubtypeRelation<I>)` variant is correct

4. **Pattern Match Check**
   - Sample verification: `rustc_infer/src/infer/mod.rs` line 756 should destructure `sub_ty, super_ty`
   - Sample verification: `rustc_hir_typeck/src/fallback.rs` line 354 should return `(sub_ty, super_ty)`

5. **Field Access Check**
   - Search for any remaining `.a` or `.b` field accesses on `SubtypeRelation` values
   - All should be changed to `.sub_ty` or `.super_ty`

## Success Criteria

The refactoring is complete when:

1. ✓ All code compiles without errors
2. ✓ All code compiles without warnings related to the refactored types
3. ✓ No stale references to the old field names `a` or `b` remain (outside of unrelated code)
4. ✓ All test suites pass
5. ✓ The semantic meaning is preserved (subtype relations still work as expected)
6. ✓ Documentation and comments are updated to reflect new field names

## Files Modified Summary

**Total files to modify: 17**

| File | Type | Status |
|------|------|--------|
| rustc_type_ir/src/predicate.rs | Definition | ✅ Modified |
| rustc_type_ir/src/predicate_kind.rs | Type annotation | ⏳ Pending |
| rustc_type_ir/src/interner.rs | Trait bound | ⏳ Pending |
| rustc_type_ir/src/ir_print.rs | Import | ⏳ Pending |
| rustc_type_ir/src/flags.rs | Pattern match | ⏳ Pending |
| rustc_type_ir/src/relate/solver_relating.rs | Construction | ⏳ Pending |
| rustc_middle/src/ty/predicate.rs | Type alias | ✅ Modified |
| rustc_middle/src/ty/mod.rs | Re-export | ⏳ Pending |
| rustc_middle/src/ty/print/pretty.rs | Printing | ⏳ Pending |
| rustc_public/src/ty.rs | Definition | ⏳ Pending |
| rustc_public/src/unstable/convert/stable/ty.rs | Conversion | ⏳ Pending |
| rustc_infer/src/infer/mod.rs | Construction/Pattern | ⏳ Pending |
| rustc_hir_typeck/src/fallback.rs | Pattern match | ⏳ Pending |
| rustc_trait_selection/src/error_reporting/traits/overflow.rs | Pattern match | ⏳ Pending |
| rustc_trait_selection/src/error_reporting/traits/ambiguity.rs | Pattern match | ⏳ Pending |
| rustc_trait_selection/src/solve/delegate.rs | Pattern match | ⏳ Pending |
| rustc_next_trait_solver/src/solve/mod.rs | Construction/Pattern | ⏳ Pending |

## Implementation Notes

### Key Points to Remember
1. The `a_is_expected` field is NOT renamed - it stays as-is since it's a separate concern
2. Only the main type fields `a` and `b` are renamed to `sub_ty` and `super_ty`
3. All derives and attributes must be preserved
4. Comments mentioning `a` and `b` should be updated to mention `sub_ty` and `super_ty`
5. The semantic meaning must be preserved: `sub_ty` is the subtype, `super_ty` is the supertype

### Potential Issues to Watch For
1. Macro expansion might hide some references - run full cargo check
2. Test code might have hardcoded references - may need updating
3. Documentation/error messages might reference the old names
4. Comments in code should be updated for clarity
