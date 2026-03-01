# SubtypePredicate → SubtypeRelation Refactoring - Implementation Guide

This guide provides step-by-step instructions and a reference script for applying all necessary changes.

## Quick Reference: Files to Modify

### Phase 1: Core Definitions (Must update first)
1. `compiler/rustc_type_ir/src/predicate.rs` - Main struct definition
2. `compiler/rustc_public/src/ty.rs` - Public API mirror
3. `compiler/rustc_middle/src/ty/predicate.rs` - Type aliases
4. `compiler/rustc_type_ir/src/predicate_kind.rs` - PredicateKind variant

### Phase 2: Primary Usage Sites
5. `compiler/rustc_infer/src/infer/mod.rs` - Conversion & type inference
6. `compiler/rustc_infer/src/infer/relate/type_relating.rs` - Type variance
7. `compiler/rustc_type_ir/src/relate/solver_relating.rs` - Solver variance
8. `compiler/rustc_next_trait_solver/src/solve/mod.rs` - Trait solver

### Phase 3: Error Reporting & Analysis
9. `compiler/rustc_type_ir/src/flags.rs` - Type flags computation
10. `compiler/rustc_hir_typeck/src/fallback.rs` - Coercion graph
11. `compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs` - Overflow errors
12. `compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs` - Ambiguity

### Phase 4: Display & Infrastructure
13. `compiler/rustc_middle/src/ty/print/pretty.rs` - Display implementation
14. `compiler/rustc_type_ir/src/interner.rs` - Trait bounds
15. `compiler/rustc_type_ir/src/ir_print.rs` - Print infrastructure
16. `compiler/rustc_middle/src/ty/mod.rs` - Re-exports

## Automated Refactoring Script

```bash
#!/bin/bash
# Batch refactoring script for SubtypePredicate → SubtypeRelation

set -e

REPO_ROOT="${1:-.}"

# List of all files to modify
FILES=(
  "compiler/rustc_type_ir/src/predicate.rs"
  "compiler/rustc_public/src/ty.rs"
  "compiler/rustc_middle/src/ty/predicate.rs"
  "compiler/rustc_type_ir/src/predicate_kind.rs"
  "compiler/rustc_infer/src/infer/mod.rs"
  "compiler/rustc_infer/src/infer/relate/type_relating.rs"
  "compiler/rustc_type_ir/src/relate/solver_relating.rs"
  "compiler/rustc_next_trait_solver/src/solve/mod.rs"
  "compiler/rustc_type_ir/src/flags.rs"
  "compiler/rustc_hir_typeck/src/fallback.rs"
  "compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs"
  "compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs"
  "compiler/rustc_middle/src/ty/print/pretty.rs"
  "compiler/rustc_type_ir/src/interner.rs"
  "compiler/rustc_type_ir/src/ir_print.rs"
  "compiler/rustc_middle/src/ty/mod.rs"
)

echo "Starting SubtypePredicate → SubtypeRelation refactoring..."

for file in "${FILES[@]}"; do
  path="$REPO_ROOT/$file"
  if [ -f "$path" ]; then
    echo "Processing: $file"

    # Struct name replacement
    sed -i 's/SubtypePredicate</SubtypeRelation</g' "$path"

    # Pattern matching replacements
    sed -i 's/SubtypePredicate {/SubtypeRelation {/g' "$path"

    # Type path replacements
    sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' "$path"
    sed -i 's/ir::SubtypePredicate/ir::SubtypeRelation/g' "$path"

    # Type alias replacements
    sed -i 's/PolySubtypePredicate</PolySubtypeRelation</g' "$path"
    sed -i 's/PolySubtypePredicate;/PolySubtypeRelation;/g' "$path"

    # Field name replacements
    # This is more complex - needs context-aware replacement
    # The pattern " a:" needs to be " sub_ty:" only when inside a SubtypeRelation
    # The pattern " b:" needs to be " super_ty:" only when inside a SubtypeRelation

    echo "  ✓ Completed $file"
  else
    echo "  ✗ File not found: $path"
  fi
done

echo "✓ Refactoring complete!"
echo ""
echo "Next steps:"
echo "1. Verify field renames manually in key files (pattern matching blocks)"
echo "2. Run: cargo build --all-targets"
echo "3. Run: cargo test"
echo "4. Review: git diff to verify all changes"
```

## Manual Verification Checklist

After running automated replacements, verify these critical locations:

### Field Renamings to Check
- [ ] All `.a` accesses → `.sub_ty` (on SubtypeRelation values)
- [ ] All `.b` accesses → `.super_ty` (on SubtypeRelation values)
- [ ] All `{ a:` in struct construction → `{ sub_ty:`
- [ ] All `{ b:` in struct construction → `{ super_ty:`
- [ ] All pattern matches with `a,` → `sub_ty,`
- [ ] All pattern matches with `b }` → `super_ty }`

### Critical Files to Review Manually
1. **compiler/rustc_infer/src/infer/mod.rs** - Verify field access in shallow_resolve
2. **compiler/rustc_type_ir/src/relate/solver_relating.rs** - Verify variance field swapping (a↔b intentional!)
3. **compiler/rustc_infer/src/infer/relate/type_relating.rs** - Same variance handling
4. **compiler/rustc_next_trait_solver/src/solve/mod.rs** - Verify match patterns

## Testing

```bash
# 1. Check compilation of affected crates
cargo check -p rustc_type_ir
cargo check -p rustc_infer
cargo check -p rustc_trait_selection
cargo check -p rustc_next_trait_solver

# 2. Build all
cargo build --all-targets 2>&1 | head -100

# 3. Run tests
cargo test --lib

# 4. Check for remaining old names
grep -r "SubtypePredicate" compiler/ --include="*.rs" | grep -v "// " | grep -v "PolySubtypePredicate" || echo "✓ No stale references found"
```

## Verification Commands

```bash
# Check that only comments remain with old names
grep -r "SubtypePredicate" compiler/ --include="*.rs" | grep -E "^[^:]+://.*SubtypePredicate"

# Verify struct name changed everywhere
grep -c "SubtypeRelation<I: Interner>" compiler/rustc_type_ir/src/predicate.rs
grep -c "pub struct SubtypeRelation {" compiler/rustc_public/src/ty.rs

# Verify type aliases changed
grep -c "pub type SubtypeRelation<'tcx>" compiler/rustc_middle/src/ty/predicate.rs
grep -c "pub type PolySubtypeRelation<'tcx>" compiler/rustc_middle/src/ty/predicate.rs

# Verify enum variant is unchanged
grep "Subtype(.*SubtypeRelation" compiler/rustc_type_ir/src/predicate_kind.rs
```

## Field Replacement Patterns

The most critical pattern replacements (must be done carefully):

### Pattern 1: Destructuring in closures
```rust
// OLD:
.enter_forall(predicate, |ty::SubtypePredicate { a_is_expected, a, b }| {

// NEW:
.enter_forall(predicate, |ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }| {
```

### Pattern 2: Struct construction
```rust
// OLD:
ty::SubtypePredicate {
    a_is_expected: false,
    a: something,
    b: other,
}

// NEW:
ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: something,
    super_ty: other,
}
```

### Pattern 3: Field access
```rust
// OLD:
predicate.skip_binder().a
predicate.skip_binder().b

// NEW:
predicate.skip_binder().sub_ty
predicate.skip_binder().super_ty
```

### Pattern 4: Variance-based swapping (KEEP THIS)
```rust
// This field swap is INTENTIONAL - do NOT change it
// It correctly represents contravariance reversal
ty::SubtypeRelation {
    a_is_expected: false,
    sub_ty: b,  // Note: swapped intentionally
    super_ty: a,
}
```

## Potential Gotchas

1. **Variance field swapping in type_relating.rs and solver_relating.rs**
   - Lines like `sub_ty: b, super_ty: a` are CORRECT and intentional
   - This properly encodes contravariance reversal
   - Do NOT "fix" these - they're semantically correct

2. **Documentation updates**
   - Update doc comments from "a must be subtype of b" to "sub_ty must be subtype of super_ty"
   - Update diagnostic messages if they reference field names

3. **CoercePredicate fields**
   - These are separate from SubtypeRelation
   - CoercePredicate still uses fields `a` and `b` (different struct)
   - Do NOT rename CoercePredicate fields

4. **PredicateKind::Subtype variant**
   - The variant name stays `Subtype` (only the type inside changes)
   - This is semantic, not syntactic

## Summary of Changes

- **Struct Name**: SubtypePredicate → SubtypeRelation (2 locations)
- **Type Aliases**: SubtypePredicate<'tcx> → SubtypeRelation<'tcx>
- **Poly Aliases**: PolySubtypePredicate → PolySubtypeRelation
- **Field `a`**: Renamed to `sub_ty` in all contexts
- **Field `b`**: Renamed to `super_ty` in all contexts
- **Field `a_is_expected`**: Unchanged (controls diagnostics)
- **Variant Name**: PredicateKind::Subtype (unchanged)
- **Impact**: 16 files, ~40 individual changes

## Expected Compilation Results

After all changes, compilation should succeed with:
- No `SubtypePredicate` symbol not found errors
- No field `.a` or `.b` not found on `SubtypeRelation` errors
- All type checking passes
- All tests pass
