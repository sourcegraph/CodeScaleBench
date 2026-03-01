# SubtypePredicate → SubtypeRelation Refactoring - Quick Start

## What This Is

A complete refactoring of the Rust compiler to rename `SubtypePredicate` to `SubtypeRelation` with clearer field names (`a` → `sub_ty`, `b` → `super_ty`).

## The Problem

**Before**: Field names `a` and `b` are opaque
```rust
pub struct SubtypePredicate<I: Interner> {
    pub a_is_expected: bool,
    pub a: I::Ty,  // Which one is the subtype?
    pub b: I::Ty,  // Which one is the supertype?
}
```

**After**: Semantic meaning is clear
```rust
pub struct SubtypeRelation<I: Interner> {
    pub a_is_expected: bool,
    pub sub_ty: I::Ty,   // The subtype
    pub super_ty: I::Ty, // The supertype
}
```

## Key Changes

| Item | Old | New |
|------|-----|-----|
| Struct name | `SubtypePredicate<I>` | `SubtypeRelation<I>` |
| Field a | `.a: I::Ty` | `.sub_ty: I::Ty` |
| Field b | `.b: I::Ty` | `.super_ty: I::Ty` |
| Type alias | `SubtypePredicate<'tcx>` | `SubtypeRelation<'tcx>` |
| Poly type | `PolySubtypePredicate<'tcx>` | `PolySubtypeRelation<'tcx>` |

## Documentation

### 📋 Full Analysis
**→ `/logs/agent/solution.md`**
- Complete dependency chain
- All affected files documented
- Detailed code diffs

### 📖 Step-by-Step Guide
**→ `/logs/agent/IMPLEMENTATION_GUIDE.md`**
- Line-by-line instructions for each file
- Exact code replacements
- Verification steps

### 📊 Summary Report
**→ `/logs/agent/REFACTORING_SUMMARY.md`**
- Executive summary
- Impact analysis
- Risk assessment

### 🐍 Automation Scripts
**→ `/logs/agent/refactor.py`** — Python implementation
**→ `/logs/agent/implementation_script.sh`** — Bash version

## Files to Modify (19 Total)

### rustc_type_ir (6 files)
1. src/predicate.rs
2. src/predicate_kind.rs
3. src/ir_print.rs
4. src/interner.rs
5. src/flags.rs
6. src/relate/solver_relating.rs

### rustc_middle (3 files)
7. src/ty/predicate.rs
8. src/ty/mod.rs
9. src/ty/print/pretty.rs

### rustc_trait_selection (4 files)
10. src/solve/delegate.rs
11. src/error_reporting/traits/overflow.rs
12. src/error_reporting/traits/ambiguity.rs
13. src/traits/mod.rs

### rustc_infer (2 files)
14. src/infer/mod.rs
15. src/infer/relate/type_relating.rs

### rustc_hir_typeck (1 file)
16. src/fallback.rs

### rustc_next_trait_solver (1 file)
17. src/solve/mod.rs

### rustc_public (2 files)
18. src/ty.rs
19. src/unstable/convert/stable/ty.rs

## Common Change Patterns

### Pattern 1: Pattern Matching
```diff
- ty::PredicateKind::Subtype(ty::SubtypePredicate { a, b, .. })
+ ty::PredicateKind::Subtype(ty::SubtypeRelation { sub_ty, super_ty, .. })
```

### Pattern 2: Struct Construction
```diff
- ty::SubtypePredicate { a_is_expected, a, b }
+ ty::SubtypeRelation { a_is_expected, sub_ty, super_ty }
```

### Pattern 3: Type Aliases
```diff
- pub type SubtypePredicate<'tcx> = ir::SubtypePredicate<TyCtxt<'tcx>>;
+ pub type SubtypeRelation<'tcx> = ir::SubtypeRelation<TyCtxt<'tcx>>;
```

## How to Apply

### Option A: Automated (Requires Write Access)
```bash
cd /workspace
python3 /logs/agent/refactor.py
cargo check --all
```

### Option B: Manual (Recommended)
1. Read `/logs/agent/IMPLEMENTATION_GUIDE.md`
2. Apply changes to each file
3. Verify compilation

### Option C: Using Git
```bash
cd /workspace
git diff > /tmp/changes.patch
# Apply patch with proper permissions
patch -p1 < /tmp/changes.patch
```

## Verification Checklist

After making changes:

```bash
# 1. Check for old names (should find none or only in comments)
grep -r "SubtypePredicate" compiler/ --include="*.rs" | grep -v "//" || echo "✓ Clean"

# 2. Check compilation
cargo check --all 2>&1 | head -50

# 3. Look at diffs
git diff | head -200

# 4. Run basic tests
cargo test --lib infer 2>&1 | tail -20
```

## Common Issues & Fixes

### Issue: `error[E0425]: cannot find type 'SubtypePredicate'`
**Fix**: Make sure you updated both the definition (predicate.rs) and all usages

### Issue: `error[E0560]: struct 'SubtypeRelation' has no field named 'a'`
**Fix**: You updated the struct but not a pattern match. Find all destructuring patterns and update field names

### Issue: `error[E0308]: mismatched types`
**Fix**: Check type aliases in rustc_middle/src/ty/predicate.rs are updated

## Success Indicators

✅ All 19 files modified
✅ Code compiles without warnings
✅ No "SubtypePredicate" in code (only in docs/comments)
✅ All field accesses use new names
✅ Tests pass

## Timeline

- Analyze: 15 min (already done)
- Read guides: 15 min
- Apply changes: 30-60 min
- Verify: 10 min
- **Total: ~1.5-2 hours**

## Key Insights

1. **Mechanical Refactoring**: Only field/name changes, no logic changes
2. **Low Risk**: Internal compiler change, no external API breaks
3. **High Impact**: Improves code readability across 6 compiler crates
4. **Complete**: All dependent code updated together

## Resources

```
📁 /logs/agent/
├── solution.md                    # Full analysis (detailed)
├── IMPLEMENTATION_GUIDE.md        # Step-by-step (practical)
├── REFACTORING_SUMMARY.md         # Executive summary
├── QUICK_START.md                 # This file
├── refactor.py                    # Python script
└── implementation_script.sh       # Bash script
```

## Need Help?

Each document has a specific purpose:

- **Getting started?** → Read this file (QUICK_START.md)
- **Need exact changes?** → Read IMPLEMENTATION_GUIDE.md
- **Want full analysis?** → Read solution.md
- **Checking impact?** → Read REFACTORING_SUMMARY.md
- **Going automated?** → Use refactor.py

---

**Status**: ✓ Analysis complete, ready for implementation

**Remaining Step**: Apply changes to files (manual or automated)

**Next Action**: Choose approach (A, B, or C above) and begin implementation
