# FxVanillaOption → FxEuropeanOption Refactoring

## Overview

This refactoring renames `FxVanillaOption` and related classes to `FxEuropeanOption` throughout the OpenGamma Strata codebase to clarify that these options use European-style exercise (exercisable only on the expiry date, not before).

## Documentation Files

This refactoring is documented in four detailed files:

### 1. **solution.md** (Main Analysis)
- High-level overview of all affected files
- Complete dependency chain showing why each file needs changes
- Verification checklist
- Expected outcomes

**Use this when:** You need to understand the scope and impact of the refactoring.

### 2. **IMPLEMENTATION_GUIDE.md** (Step-by-Step Implementation)
- Detailed line-by-line guidance for each type of file
- Exact changes needed for core classes, pricers, measures, utilities, and tests
- Code examples showing before/after patterns
- Search and replace patterns for batch updates
- Verification commands

**Use this when:** You're actually implementing the changes and need specific guidance on what to change in each file.

### 3. **FILE_CHANGES_SUMMARY.md** (File Inventory)
- Complete list of all 50+ affected files
- Organized by action type (rename vs. update)
- Statistics on the scope of changes
- Recommended implementation order
- Key implementation points

**Use this when:** You need to track which files have been changed or plan the implementation order.

### 4. **SAMPLE_CODE.md** (Code Examples)
- Example of a renamed core class (FxEuropeanOption.java)
- Shows the complete structure with all class name updates
- Demonstrates Joda-Beans pattern with renamed classes

**Use this when:** You need to see concrete examples of how renamed files should look.

---

## Quick Start

### For Project Leads

1. Read `solution.md` section "Dependency Chain" to understand impact
2. Review `FILE_CHANGES_SUMMARY.md` "Summary Statistics" for scope
3. Use recommended implementation order from `FILE_CHANGES_SUMMARY.md`

### For Developers Implementing

1. Follow the "Implementation Order" in `FILE_CHANGES_SUMMARY.md`
2. Use `IMPLEMENTATION_GUIDE.md` for step-by-step guidance on each file
3. Use search patterns from `IMPLEMENTATION_GUIDE.md` for batch updates
4. Refer to the sample file structure in this workspace as a template

### For Code Review

1. Use `FILE_CHANGES_SUMMARY.md` checklist to verify all files are renamed
2. Use `IMPLEMENTATION_GUIDE.md` to verify each type of file is updated correctly
3. Run verification commands from `IMPLEMENTATION_GUIDE.md`

---

## Key Facts

### Scope
- **13 core files to rename** (classes + pricers + measures + plugin)
- **14 test files to rename** (matching core files)
- **~23 supporting files to update** (imports, types, method calls)
- **Total: ~50 files affected**

### Modules Affected
- `modules/product` - Core product definitions
- `modules/pricer` - Pricing models
- `modules/measure` - Measurement and calculation
- `modules/loader` - CSV plugins

### Breaking Changes
- Public API change: `FxVanillaOption` → `FxEuropeanOption`
- Constant renamed: `ProductType.FX_VANILLA_OPTION` → `ProductType.FX_EUROPEAN_OPTION`
- CSV product type string changes: `"FxVanillaOption"` → `"FxEuropeanOption"`
- Method names updated: `writeFxVanillaOption()` → `writeFxEuropeanOption()`

---

## Why This Refactoring?

**Problem:** "Vanilla option" is ambiguous. Vanilla options can have different exercise styles:
- **American:** Exercisable any day from issuance until expiry
- **European:** Exercisable only on the expiry date
- **Bermudan:** Exercisable on specific dates

**Current:** The class name `FxVanillaOption` doesn't convey the exercise style, even though the implementation is European-only.

**Solution:** Rename to `FxEuropeanOption` to make the exercise style explicit in the class name.

---

## Implementation Timeline

### Estimated Effort
- **Rename operations:** 27 files
- **Update operations:** 23 files
- **Search and replace:** High parallelization possible
- **Testing:** Must run full test suite after changes

### Critical Path
1. Rename 4 core product classes (blocks everything else)
2. Rename 4 pricer classes (enables pricer users to compile)
3. Rename 4 measure classes (enables measure users to compile)
4. Update barrier option classes (enables barrier tests)
5. Rename all tests
6. Update test imports
7. Full system test

### Parallelization Opportunities
- Core class renames can happen in parallel after dependencies are clear
- Test file renames can happen independently after core renames
- Test import updates can happen in parallel

---

## Validation Checklist

Before considering this refactoring complete:

- [ ] All 13 core files renamed (check solution.md FILE_CHANGES_SUMMARY.md)
- [ ] All 14 test files renamed (check FILE_CHANGES_SUMMARY.md)
- [ ] All 23 supporting files updated (check FILE_CHANGES_SUMMARY.md)
- [ ] No `FxVanillaOption` references remain (except in comments/strings)
- [ ] No `FxVanillaOptionTrade` references remain (except in comments/strings)
- [ ] No `ResolvedFxVanillaOption` references remain (except in comments/strings)
- [ ] `ProductType.FX_EUROPEAN_OPTION` exists (not `FX_VANILLA_OPTION`)
- [ ] `writeFxEuropeanOption()` method exists (not `writeFxVanillaOption()`)
- [ ] All product, pricer, measure, and loader modules compile
- [ ] Full test suite passes
- [ ] No compilation warnings related to undefined types

---

## Related Files

### Renamed Example (provided)
- `/workspace/FxEuropeanOption.java` - Shows how the renamed core class should look

### Documentation
- `solution.md` - Complete technical analysis
- `IMPLEMENTATION_GUIDE.md` - Line-by-line implementation steps
- `FILE_CHANGES_SUMMARY.md` - File inventory and implementation order

---

## Questions?

Refer to the specific documentation file:
- **"What files are affected?"** → FILE_CHANGES_SUMMARY.md
- **"How do I implement changes to Product class?"** → IMPLEMENTATION_GUIDE.md Phase 1
- **"How do I implement changes to Pricer class?"** → IMPLEMENTATION_GUIDE.md Phase 2
- **"What's the dependency chain?"** → solution.md "Dependency Chain"
- **"What should I verify?"** → solution.md "Verification Checklist"

---

## Version Control

Recommended git approach:
1. Create feature branch: `git checkout -b refactor/fx-vanilla-to-european-option`
2. Implement all 50 files in a single commit with message:
   ```
   refactor: Rename FxVanillaOption to FxEuropeanOption

   - Rename 4 core product classes to clarify European exercise style
   - Rename 4 pricer classes (Black/VannaVolga)
   - Rename 4 measure classes (calculations/methods)
   - Rename CSV plugin class
   - Update ProductType constant FX_VANILLA_OPTION → FX_EUROPEAN_OPTION
   - Update all dependent imports and type references
   - Rename 14 test files and update all test imports
   - Update 23 supporting files with type/method updates

   BREAKING CHANGE: Public API names have changed from FxVanillaOption*
   to FxEuropeanOption*
   ```
3. Review all changes
4. Run full test suite
5. Merge to develop/main branch

---

## Next Steps

1. Read `solution.md` for complete context
2. Review `FILE_CHANGES_SUMMARY.md` implementation order
3. Begin implementation following `IMPLEMENTATION_GUIDE.md`
4. Use the verification commands to validate completeness
5. Run full test suite before merging

