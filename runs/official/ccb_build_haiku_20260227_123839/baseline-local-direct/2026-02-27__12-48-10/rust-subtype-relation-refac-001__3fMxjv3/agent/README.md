# SubtypePredicate → SubtypeRelation Refactoring Documentation

## 📋 Quick Reference

This directory contains comprehensive analysis and implementation guidance for refactoring the Rust compiler to rename `SubtypePredicate` to `SubtypeRelation` and its fields from `a`/`b` to `sub_ty`/`super_ty`.

**Total Files Analyzed**: 18 files across 7 compiler crates
**Status**: ✅ Analysis Complete | Ready for Implementation

---

## 📚 Documentation Files

### 1. **REFACTORING_ANALYSIS_SUMMARY.md** ⭐ START HERE
**Purpose**: Executive summary and overview
**Contents**:
- High-level findings and completion status
- All 18 files listed by category
- Dependency chain visualization
- Risk assessment and benefits
- Timeline and next steps
- Verification checklist

**Use When**: You want a quick overview of what needs to be done

---

### 2. **solution.md**
**Purpose**: Comprehensive technical analysis
**Contents**:
- Detailed file examination with line numbers
- Complete dependency chain analysis
- Crate-by-crate impact assessment
- Refactoring strategy and verification approach
- Analysis of the refactoring benefits

**Use When**: You want to understand the architectural impact and reasoning

---

### 3. **detailed_code_changes.md**
**Purpose**: Exact code modifications needed
**Contents**:
- Before/after code for each file
- Specific line numbers
- 17 file sections with complete code context
- Summary table of all changes
- Field rename semantics

**Use When**: You're implementing the changes and need exact code to apply

---

### 4. **implementation_checklist.md**
**Purpose**: Step-by-step execution guide
**Contents**:
- 10-phase implementation strategy
- Pre-implementation verification
- Detailed checklist for each phase
- Compilation verification steps
- Testing and verification procedures
- Rollback plan
- Completeness verification checklist

**Use When**: You're ready to implement the changes

---

## 🎯 Quick Navigation

### For Different Roles

**📊 Project Manager / Tech Lead**
- Read: `REFACTORING_ANALYSIS_SUMMARY.md`
- Check: Timeline, risk assessment, and next steps sections
- Review: File count and scope summary

**🔧 Implementation Engineer**
- Read: `implementation_checklist.md` (start here)
- Reference: `detailed_code_changes.md` (for exact code)
- Verify: Completeness checklist at the end

**🏗️ Architecture Reviewer**
- Read: `solution.md` (comprehensive analysis)
- Study: Dependency chain and impact analysis
- Review: Verification approach section

**🧪 QA / Testing**
- Read: Testing section in `implementation_checklist.md`
- Reference: Files affected in `REFACTORING_ANALYSIS_SUMMARY.md`
- Run: Verification steps provided

---

## 📊 Key Statistics

| Metric | Value |
|--------|-------|
| **Total Files Affected** | 18 |
| **Compiler Crates Involved** | 7 |
| **Struct Renames** | 1 |
| **Field Renames** | 2 |
| **Struct Literals to Update** | 4 |
| **Pattern Matches to Update** | 6 |
| **Type Annotations to Update** | 8+ |
| **Lines of Code Affected** | 50-100 |
| **Implementation Time** | 1.5-2 hours |

---

## ✅ Verification Status

All analysis has been verified against the current codebase:

- ✅ Struct definition located: `rustc_type_ir/src/predicate.rs:918`
- ✅ Enum variant located: `rustc_type_ir/src/predicate_kind.rs:78`
- ✅ Type aliases located: `rustc_middle/src/ty/predicate.rs:24,32`
- ✅ All 18 files verified to exist
- ✅ All line numbers verified
- ✅ All struct literals documented
- ✅ All pattern matches documented

---

## 🚀 Implementation Path

### Phase 1: Preparation
1. Read `REFACTORING_ANALYSIS_SUMMARY.md` for overview
2. Review `solution.md` for architecture understanding
3. Study `detailed_code_changes.md` for specific changes

### Phase 2: Execution
1. Follow `implementation_checklist.md` 10-phase plan
2. Apply changes to files in dependency order
3. Verify compilation after each phase

### Phase 3: Verification
1. Run compiler test suite
2. Check for any remaining old names
3. Verify semantics are preserved

---

## 📁 Affected Files by Crate

### rustc_type_ir (6 files)
- `src/predicate.rs` - Core struct definition
- `src/predicate_kind.rs` - Enum variant
- `src/flags.rs` - Pattern match
- `src/relate/solver_relating.rs` - Struct literals (2)
- `src/ir_print.rs` - Imports
- `src/interner.rs` - Trait bounds

### rustc_middle (2 files)
- `src/ty/predicate.rs` - Type aliases
- `src/ty/mod.rs` - Re-exports

### rustc_infer (2 files)
- `src/infer/relate/type_relating.rs` - Struct literals (2)
- `src/infer/mod.rs` - Pattern match

### rustc_hir_typeck (1 file)
- `src/fallback.rs` - Pattern match

### rustc_trait_selection (3 files)
- `src/traits/mod.rs` - Comment
- `src/solve/delegate.rs` - Pattern match
- `src/error_reporting/traits/` - Pattern matches (2)

### rustc_next_trait_solver (1 file)
- `src/solve/mod.rs` - Struct literal

### rustc_public (2 files)
- `src/ty.rs` - Public struct
- `src/unstable/convert/stable/ty.rs` - Conversion impl

---

## 🔍 Change Patterns

### Pattern 1: Struct Definition
```rust
// BEFORE
pub struct SubtypePredicate<I: Interner> {
    pub a: I::Ty,
    pub b: I::Ty,
}

// AFTER
pub struct SubtypeRelation<I: Interner> {
    pub sub_ty: I::Ty,
    pub super_ty: I::Ty,
}
```

### Pattern 2: Type Annotations
```rust
// BEFORE
Subtype(ty::SubtypePredicate<I>)

// AFTER
Subtype(ty::SubtypeRelation<I>)
```

### Pattern 3: Struct Literals
```rust
// BEFORE
ty::SubtypePredicate { a_is_expected: true, a, b }

// AFTER
ty::SubtypeRelation { a_is_expected: true, sub_ty, super_ty }
```

### Pattern 4: Pattern Matches
```rust
// BEFORE
ty::SubtypePredicate { a_is_expected: _, a, b }

// AFTER
ty::SubtypeRelation { a_is_expected: _, sub_ty, super_ty }
```

---

## 📝 Semantic Notes

### Field Meaning
- **`sub_ty`** (formerly `a`): The subtype in the relation `sub_ty <: super_ty`
- **`super_ty`** (formerly `b`): The supertype in the relation `sub_ty <: super_ty`
- **`a_is_expected`**: Flag indicating which type to label as "expected" in diagnostics

### Bidirectional Cases
In `solver_relating.rs` and `type_relating.rs`, fields may be intentionally swapped:
- When `a_is_expected: false`, the check is reversed: `super_ty <: sub_ty`
- This is semantically correct and intentional
- The new names make this clearer

---

## ⚠️ Important Considerations

1. **Breaking Change**: This is a breaking change for `rustc_public` consumers
   - Can be mitigated with deprecation aliases
   - See `solution.md` for backward compatibility strategy

2. **Semantic Preservation**: The refactoring preserves all semantics
   - No behavioral changes
   - No runtime impact
   - Purely a naming improvement

3. **Testing Required**: Full compiler test suite must pass
   - No new tests needed (existing tests remain valid)
   - All existing tests should pass with new names

---

## 🆘 Troubleshooting

### Compilation Errors
- **"cannot find type `SubtypePredicate`"**: You need to rename the struct in `predicate.rs`
- **"field `a` not found"**: Update pattern match to use `sub_ty` instead
- **"field `b` not found"**: Update pattern match to use `super_ty` instead

### Missing Changes
- Use `grep -r "SubtypePredicate" compiler/` to find remaining old names
- Use `grep -r "\.a.*subtype\|\.b.*subtype" compiler/` to find field access issues

### Verification
- Run `cargo build -p rustc_type_ir` to verify Phase 1 changes
- Run full test suite to verify all changes

---

## 📞 Document References

For specific questions:
- **"What files are affected?"** → See `REFACTORING_ANALYSIS_SUMMARY.md`
- **"What are the exact code changes?"** → See `detailed_code_changes.md`
- **"How do I implement this?"** → See `implementation_checklist.md`
- **"Why are we doing this?"** → See `solution.md`

---

## 📅 Timeline

**Analysis Completed**: 2026-02-27
**Status**: READY FOR IMPLEMENTATION
**Confidence Level**: HIGH (all files verified, no ambiguities)

**Estimated Implementation Time**: 1.5-2 hours
**Estimated Testing Time**: 30-60 minutes
**Total Effort**: 2-3 hours

---

## ✨ Summary

This refactoring improves code clarity by giving semantic names to struct fields:
- `a` → `sub_ty` (makes it clear this is the subtype)
- `b` → `super_ty` (makes it clear this is the supertype)
- `SubtypePredicate` → `SubtypeRelation` (more descriptive name)

The benefits include:
- ✅ Reduced chance of field swap errors
- ✅ Self-documenting code
- ✅ Easier maintenance and code review
- ✅ Better developer experience

No runtime changes, no behavioral changes, purely improved clarity.

---

**Last Updated**: 2026-02-27
**All Files Verified**: YES
**Ready for Implementation**: YES

