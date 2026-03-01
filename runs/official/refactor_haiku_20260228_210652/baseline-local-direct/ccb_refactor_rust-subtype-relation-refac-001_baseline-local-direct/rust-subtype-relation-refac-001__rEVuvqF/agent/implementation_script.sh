#!/bin/bash
# Implementation script for SubtypePredicate → SubtypeRelation refactoring
# This script applies all necessary changes across the Rust compiler codebase

set -e

WORKSPACE="/workspace"
cd "$WORKSPACE"

echo "Starting SubtypePredicate → SubtypeRelation refactoring..."

# File 1: Core definition in rustc_type_ir
echo "[1/19] Updating compiler/rustc_type_ir/src/predicate.rs (struct definition)"
sed -i '909,924s/SubtypePredicate/SubtypeRelation/g' compiler/rustc_type_ir/src/predicate.rs
sed -i 's/pub a: I::Ty,/pub sub_ty: I::Ty,/' compiler/rustc_type_ir/src/predicate.rs
sed -i 's/pub b: I::Ty,/pub super_ty: I::Ty,/' compiler/rustc_type_ir/src/predicate.rs

# File 2: Predicate kind variant
echo "[2/19] Updating compiler/rustc_type_ir/src/predicate_kind.rs"
sed -i 's/Subtype(ty::SubtypePredicate/Subtype(ty::SubtypeRelation/' compiler/rustc_type_ir/src/predicate_kind.rs

# File 3: IR print imports
echo "[3/19] Updating compiler/rustc_type_ir/src/ir_print.rs"
sed -i 's/SubtypePredicate/SubtypeRelation/g' compiler/rustc_type_ir/src/ir_print.rs

# File 4: Interner trait bound
echo "[4/19] Updating compiler/rustc_type_ir/src/interner.rs"
sed -i 's/IrPrint<ty::SubtypePredicate/IrPrint<ty::SubtypeRelation/g' compiler/rustc_type_ir/src/interner.rs

# File 5: Flags.rs destructuring
echo "[5/19] Updating compiler/rustc_type_ir/src/flags.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_type_ir/src/flags.rs
sed -i 's/{ a_is_expected: _, a, b }/{ a_is_expected: _, sub_ty, super_ty }/g' compiler/rustc_type_ir/src/flags.rs

# File 6: Solver relating
echo "[6/19] Updating compiler/rustc_type_ir/src/relate/solver_relating.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_type_ir/src/relate/solver_relating.rs
# Update field names in constructors
sed -i 's/a_is_expected, a, b/a_is_expected, sub_ty, super_ty/g' compiler/rustc_type_ir/src/relate/solver_relating.rs

# File 7: Type aliases in rustc_middle
echo "[7/19] Updating compiler/rustc_middle/src/ty/predicate.rs"
sed -i 's/pub type SubtypePredicate/pub type SubtypeRelation/' compiler/rustc_middle/src/ty/predicate.rs
sed -i 's/ir::SubtypePredicate/ir::SubtypeRelation/' compiler/rustc_middle/src/ty/predicate.rs
sed -i 's/pub type PolySubtypePredicate/pub type PolySubtypeRelation/' compiler/rustc_middle/src/ty/predicate.rs
sed -i 's/<'tcx, SubtypePredicate<'tcx>>/<'\''tcx, SubtypeRelation<'\''tcx>>/' compiler/rustc_middle/src/ty/predicate.rs

# File 8: Re-exports in rustc_middle
echo "[8/19] Updating compiler/rustc_middle/src/ty/mod.rs"
sed -i 's/PolySubtypePredicate/PolySubtypeRelation/g' compiler/rustc_middle/src/ty/mod.rs
sed -i 's/SubtypePredicate([^,]*),/SubtypeRelation,/' compiler/rustc_middle/src/ty/mod.rs

# File 9: Pretty printer
echo "[9/19] Updating compiler/rustc_middle/src/ty/print/pretty.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_middle/src/ty/print/pretty.rs
sed -i 's/{ a, b, a_is_expected }/{ sub_ty, super_ty, a_is_expected }/' compiler/rustc_middle/src/ty/print/pretty.rs

# File 10: Trait selection delegate
echo "[10/19] Updating compiler/rustc_trait_selection/src/solve/delegate.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_trait_selection/src/solve/delegate.rs
sed -i 's/{ a, b, .. }/{ sub_ty, super_ty, .. }/' compiler/rustc_trait_selection/src/solve/delegate.rs

# File 11: Overflow error reporting
echo "[11/19] Updating compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs
sed -i 's/{ a, b, a_is_expected: _ }/{ sub_ty, super_ty, a_is_expected: _ }/' compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs

# File 12: Ambiguity error reporting
echo "[12/19] Updating compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs
sed -i 's/{ a_is_expected: _, a, b }/{ a_is_expected: _, sub_ty, super_ty }/' compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs

# File 13: Trait mod
echo "[13/19] Updating compiler/rustc_trait_selection/src/traits/mod.rs"
sed -i 's/SubtypePredicate/SubtypeRelation/g' compiler/rustc_trait_selection/src/traits/mod.rs

# File 14: Infer mod
echo "[14/19] Updating compiler/rustc_infer/src/infer/mod.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_infer/src/infer/mod.rs
sed -i 's/PolySubtypePredicate/PolySubtypeRelation/g' compiler/rustc_infer/src/infer/mod.rs
# Update constructor pattern
sed -i 's/p| ty::SubtypePredicate { a_is_expected, a, b }/p| ty::SubtypeRelation { a_is_expected, sub_ty, sub_ty_expected, super_ty }/' compiler/rustc_infer/src/infer/mod.rs

# File 15: Type relating
echo "[15/19] Updating compiler/rustc_infer/src/infer/relate/type_relating.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_infer/src/infer/relate/type_relating.rs

# File 16: HIR type checker fallback
echo "[16/19] Updating compiler/rustc_hir_typeck/src/fallback.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_hir_typeck/src/fallback.rs
sed -i 's/{ a_is_expected: _, a, b }/{ a_is_expected: _, sub_ty, super_ty }/' compiler/rustc_hir_typeck/src/fallback.rs

# File 17: Next trait solver
echo "[17/19] Updating compiler/rustc_next_trait_solver/src/solve/mod.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_next_trait_solver/src/solve/mod.rs
sed -i 's/compute_subtype_goal(&mut self, goal: Goal<I, ty::SubtypePredicate/compute_subtype_goal(\&mut self, goal: Goal<I, ty::SubtypeRelation/' compiler/rustc_next_trait_solver/src/solve/mod.rs

# File 18: Public API
echo "[18/19] Updating compiler/rustc_public/src/ty.rs"
sed -i 's/SubType(SubtypePredicate)/SubType(SubtypeRelation)/' compiler/rustc_public/src/ty.rs
sed -i 's/pub struct SubtypePredicate/pub struct SubtypeRelation/' compiler/rustc_public/src/ty.rs
sed -i 's/pub a: Ty,/pub sub_ty: Ty,/' compiler/rustc_public/src/ty.rs
sed -i 's/pub b: Ty,/pub super_ty: Ty,/' compiler/rustc_public/src/ty.rs

# File 19: Stable conversion
echo "[19/19] Updating compiler/rustc_public/src/unstable/convert/stable/ty.rs"
sed -i 's/ty::SubtypePredicate/ty::SubtypeRelation/g' compiler/rustc_public/src/unstable/convert/stable/ty.rs
sed -i 's/let ty::SubtypeRelation { a, b, a_is_expected: _ }/let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ }/' compiler/rustc_public/src/unstable/convert/stable/ty.rs
sed -i 's/crate::ty::SubtypeRelation { a: a\.stable/crate::ty::SubtypeRelation { sub_ty: sub_ty.stable/' compiler/rustc_public/src/unstable/convert/stable/ty.rs
sed -i 's/b\.stable/super_ty.stable/' compiler/rustc_public/src/unstable/convert/stable/ty.rs

echo "✓ Refactoring complete!"
echo ""
echo "Verifying changes..."
echo ""
echo "Checking for remaining 'SubtypePredicate' references (should be none or only in comments):"
grep -r "SubtypePredicate" compiler/ --include="*.rs" | grep -v "//" | grep -v "^[[:space:]]*///" || echo "✓ No uncommmented references found"

echo ""
echo "Next steps:"
echo "1. Run: cargo check --lib --workspace"
echo "2. Run: cargo test --lib --workspace"
echo "3. Review changes with: git diff"
echo "4. Commit with: git commit -am 'refactor: rename SubtypePredicate to SubtypeRelation'"
