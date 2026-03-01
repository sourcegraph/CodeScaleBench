#!/usr/bin/env python3
"""
SubtypePredicate → SubtypeRelation Refactoring Implementation

This script performs the complete refactoring of SubtypePredicate to SubtypeRelation
across all 19 affected files in the Rust compiler codebase.
"""

import re
import os
import sys
from pathlib import Path

# Color codes for output
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
RESET = '\033[0m'

def replace_in_file(filepath, replacements):
    """Apply a list of regex replacements to a file."""
    filepath = Path(filepath)

    if not filepath.exists():
        print(f"{RED}✗{RESET} File not found: {filepath}")
        return False

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

        for pattern, replacement in replacements:
            content = re.sub(pattern, replacement, content)

        if content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"{GREEN}✓{RESET} {filepath.relative_to('/workspace')}")
            return True
        else:
            print(f"{YELLOW}⊘{RESET} {filepath.relative_to('/workspace')} (no changes)")
            return False

    except Exception as e:
        print(f"{RED}✗{RESET} Error processing {filepath}: {e}")
        return False

def main():
    os.chdir('/workspace')

    files_changed = 0
    total_files = 0

    # File 1: Core definition
    print("\n[1/19] compiler/rustc_type_ir/src/predicate.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_type_ir/src/predicate.rs', [
        (r'pub struct SubtypePredicate<I: Interner>', 'pub struct SubtypeRelation<I: Interner>'),
        (r'impl<I: Interner> Eq for SubtypePredicate<I>', 'impl<I: Interner> Eq for SubtypeRelation<I>'),
        (r'Encodes that `a` must be a subtype of `b`', 'Encodes that `sub_ty` must be a subtype of `super_ty`'),
        (r'whether the `a` type is the type that we should label', 'whether the `sub_ty` type is the type that we should label'),
        (r'\s+pub a: I::Ty,', '    pub sub_ty: I::Ty,'),
        (r'\s+pub b: I::Ty,', '    pub super_ty: I::Ty,'),
    ]):
        files_changed += 1

    # File 2: Predicate kind
    print("[2/19] compiler/rustc_type_ir/src/predicate_kind.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_type_ir/src/predicate_kind.rs', [
        (r'Subtype\(ty::SubtypePredicate<I>\)', 'Subtype(ty::SubtypeRelation<I>)'),
    ]):
        files_changed += 1

    # File 3: IR Print imports
    print("[3/19] compiler/rustc_type_ir/src/ir_print.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_type_ir/src/ir_print.rs', [
        (r'SubtypePredicate', 'SubtypeRelation'),
    ]):
        files_changed += 1

    # File 4: Interner
    print("[4/19] compiler/rustc_type_ir/src/interner.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_type_ir/src/interner.rs', [
        (r'IrPrint<ty::SubtypePredicate<Self>>', 'IrPrint<ty::SubtypeRelation<Self>>'),
    ]):
        files_changed += 1

    # File 5: Flags
    print("[5/19] compiler/rustc_type_ir/src/flags.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_type_ir/src/flags.rs', [
        (r'ty::SubtypePredicate<I::Ty>', 'ty::SubtypeRelation<I::Ty>'),
        (r'ty::SubtypePredicate\s*{\s*a_is_expected:\s*_,\s*a,\s*b\s*}', 'ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }'),
    ]):
        files_changed += 1

    # File 6: Solver relating
    print("[6/19] compiler/rustc_type_ir/src/relate/solver_relating.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_type_ir/src/relate/solver_relating.rs', [
        (r'ty::SubtypePredicate', 'ty::SubtypeRelation'),
        (r'PredicateKind::Subtype\(ty::SubtypeRelation\s*{\s*a_is_expected,\s*a,\s*b\s*}\)',
         'PredicateKind::Subtype(ty::SubtypeRelation { a_is_expected, sub_ty, super_ty })'),
    ]):
        files_changed += 1

    # File 7: Type aliases
    print("[7/19] compiler/rustc_middle/src/ty/predicate.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_middle/src/ty/predicate.rs', [
        (r'pub type SubtypePredicate<\'tcx> = ir::SubtypePredicate<',
         'pub type SubtypeRelation<\'tcx> = ir::SubtypeRelation<'),
        (r'pub type PolySubtypePredicate<\'tcx> = ty::Binder<\'tcx, SubtypePredicate<',
         'pub type PolySubtypeRelation<\'tcx> = ty::Binder<\'tcx, SubtypeRelation<'),
    ]):
        files_changed += 1

    # File 8: Re-exports
    print("[8/19] compiler/rustc_middle/src/ty/mod.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_middle/src/ty/mod.rs', [
        (r'PolySubtypePredicate', 'PolySubtypeRelation'),
        (r'SubtypePredicate,', 'SubtypeRelation,'),
    ]):
        files_changed += 1

    # File 9: Pretty printer
    print("[9/19] compiler/rustc_middle/src/ty/print/pretty.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_middle/src/ty/print/pretty.rs', [
        (r'ty::SubtypePredicate<\'tcx>\s*{\s*a,\s*b,\s*a_is_expected\s*}',
         'ty::SubtypeRelation<\'tcx> { sub_ty, super_ty, a_is_expected }'),
    ]):
        files_changed += 1

    # File 10: Trait selection delegate
    print("[10/19] compiler/rustc_trait_selection/src/solve/delegate.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_trait_selection/src/solve/delegate.rs', [
        (r'ty::SubtypePredicate\s*{\s*a,\s*b,\s*\.\.', 'ty::SubtypeRelation { sub_ty, super_ty, ..'),
    ]):
        files_changed += 1

    # File 11: Overflow errors
    print("[11/19] compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_trait_selection/src/error_reporting/traits/overflow.rs', [
        (r'ty::SubtypePredicate\s*{\s*a,\s*b,\s*a_is_expected:\s*_\s*}',
         'ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ }'),
    ]):
        files_changed += 1

    # File 12: Ambiguity errors
    print("[12/19] compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_trait_selection/src/error_reporting/traits/ambiguity.rs', [
        (r'let ty::SubtypePredicate\s*{\s*a_is_expected:\s*_,\s*a,\s*b\s*}',
         'let ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }'),
    ]):
        files_changed += 1

    # File 13: Traits mod
    print("[13/19] compiler/rustc_trait_selection/src/traits/mod.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_trait_selection/src/traits/mod.rs', [
        (r'SubtypePredicate', 'SubtypeRelation'),
    ]):
        files_changed += 1

    # File 14: Infer mod
    print("[14/19] compiler/rustc_infer/src/infer/mod.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_infer/src/infer/mod.rs', [
        (r'ty::SubtypePredicate', 'ty::SubtypeRelation'),
        (r'PolySubtypePredicate', 'PolySubtypeRelation'),
        (r'\|ty::SubtypeRelation\s*{\s*a_is_expected,\s*a,\s*b\s*}\|',
         '|ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }|'),
    ]):
        files_changed += 1

    # File 15: Type relating
    print("[15/19] compiler/rustc_infer/src/infer/relate/type_relating.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_infer/src/infer/relate/type_relating.rs', [
        (r'ty::SubtypePredicate\s*{\s*a_is_expected,\s*a,\s*b\s*}',
         'ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }'),
    ]):
        files_changed += 1

    # File 16: HIR typeck fallback
    print("[16/19] compiler/rustc_hir_typeck/src/fallback.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_hir_typeck/src/fallback.rs', [
        (r'ty::SubtypePredicate\s*{\s*a_is_expected:\s*_,\s*a,\s*b\s*}',
         'ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }'),
    ]):
        files_changed += 1

    # File 17: Next trait solver
    print("[17/19] compiler/rustc_next_trait_solver/src/solve/mod.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_next_trait_solver/src/solve/mod.rs', [
        (r'ty::SubtypePredicate', 'ty::SubtypeRelation'),
        (r'Goal<I,\s*ty::SubtypeRelation<I>>', 'Goal<I, ty::SubtypeRelation<I>>'),
    ]):
        files_changed += 1

    # File 18: Public API
    print("[18/19] compiler/rustc_public/src/ty.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_public/src/ty.rs', [
        (r'SubType\(SubtypePredicate\)', 'SubType(SubtypeRelation)'),
        (r'pub struct SubtypePredicate', 'pub struct SubtypeRelation'),
        (r'\s+pub a: Ty,', '    pub sub_ty: Ty,'),
        (r'\s+pub b: Ty,', '    pub super_ty: Ty,'),
    ]):
        files_changed += 1

    # File 19: Stable conversion
    print("[19/19] compiler/rustc_public/src/unstable/convert/stable/ty.rs")
    total_files += 1
    if replace_in_file('compiler/rustc_public/src/unstable/convert/stable/ty.rs', [
        (r'impl<\'tcx> Stable<\'tcx> for ty::SubtypePredicate<\'tcx>',
         'impl<\'tcx> Stable<\'tcx> for ty::SubtypeRelation<\'tcx>'),
        (r'type T = crate::ty::SubtypePredicate', 'type T = crate::ty::SubtypeRelation'),
        (r'let ty::SubtypeRelation\s*{\s*a,\s*b,\s*a_is_expected:\s*_\s*}',
         'let ty::SubtypeRelation { sub_ty, super_ty, a_is_expected: _ }'),
        (r'crate::ty::SubtypeRelation\s*{\s*a:\s*a\.stable',
         'crate::ty::SubtypeRelation { sub_ty: sub_ty.stable'),
        (r',\s*b:\s*b\.stable', ', super_ty: super_ty.stable'),
    ]):
        files_changed += 1

    # Summary
    print("\n" + "="*60)
    print(f"Refactoring Complete: {GREEN}{files_changed}/{total_files}{RESET} files modified")
    print("="*60)

    print("\nNext steps:")
    print("1. Verify compilation: cargo check --all")
    print("2. Run tests: cargo test --lib")
    print("3. Review changes: git diff")
    print("4. Commit: git commit -am 'refactor: rename SubtypePredicate to SubtypeRelation'")

    return 0 if files_changed > 0 else 1

if __name__ == '__main__':
    sys.exit(main())
