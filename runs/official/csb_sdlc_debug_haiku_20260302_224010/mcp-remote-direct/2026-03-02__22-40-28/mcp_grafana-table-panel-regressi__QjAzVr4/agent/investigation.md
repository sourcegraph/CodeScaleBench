# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary
The v38 dashboard migration introduces a regression where table panels lose their field override configurations when imported from v10.3 dashboards that don't explicitly contain `fieldConfig.defaults.custom`. The migration successfully converts override properties from `custom.displayMode` to `custom.cellOptions`, but the conversion breaks during dashboard cleanup when the entire `fieldConfig` object is removed if it matches the default structure.

## Root Cause

**Migration Chain Conflict:** The bug occurs at the intersection of the backend v38 migration handler and the cleanup phase, combined with conditional preservation logic based on `_originallyHadFieldConfigCustom` marker.

**Specific Mechanism:**

1. **Backend Migration (v38.go, lines 115-131):** The migration correctly processes table panel overrides, converting `custom.displayMode` → `custom.cellOptions` regardless of whether `fieldConfig.defaults.custom` exists.

2. **Field Config Preservation Marker (migrate.go:71):** Before migrations run, `trackOriginalFieldConfigCustom()` marks panels that originally had `fieldConfig.defaults.custom` in the input JSON with `_originallyHadFieldConfigCustom = true`.

3. **Cleanup Deletion Logic (frontend_defaults.go, lines 606-626):** After migrations complete, during the cleanup phase in `filterDefaultValues()`:
   ```go
   if prop == "fieldConfig" {
       if panel["_originallyHadFieldConfigCustom"] == true {
           // Preserve fieldConfig if it originally had custom
           continue  // Don't delete
       }
       delete(panel, prop)  // DELETE if no custom originally
   }
   ```

4. **The Bug:** The cleanup logic assumes that if a panel's `fieldConfig` matches the default structure (empty `defaults: {}`, empty `overrides: []`), it can be safely deleted UNLESS it originally contained `defaults.custom`.

   However, this logic fails for dashboards where:
   - Original panel has NO `fieldConfig.defaults.custom`
   - Original panel HAS `fieldConfig.overrides` with `custom.displayMode` properties
   - After v38 migration, `fieldConfig.overrides` contains the migrated `custom.cellOptions`
   - BUT the cleanup code never checks the overrides array when deciding to delete fieldConfig
   - It only checks the `_originallyHadFieldConfigCustom` marker, which is FALSE

## Evidence

### Code References:

1. **Backend v38 Migration (apps/dashboard/pkg/migration/schemaversion/v38.go)**
   - Lines 75-87: V38 function entry point
   - Lines 116-127: Processes `defaults.custom` only if it exists
   - Lines 130-131: Always calls `migrateOverrides(fieldConfig)` regardless
   - Lines 159-173: Override property migration logic

2. **Cleanup Logic (apps/dashboard/pkg/migration/frontend_defaults.go)**
   - Lines 1138-1169: `trackOriginalFieldConfigCustom()` - Marks panels with custom
   - Lines 606-626: `filterDefaultValues()` - Deletion conditional on marker
   - Lines 525-531: First cleanup pass removes properties matching defaults
   - Lines 654-662: Special case for fieldConfig with custom marker

3. **Test Case Demonstrating Issue (apps/dashboard/pkg/migration/schemaversion/v38_test.go)**
   - Lines 444-517: Test case "table with missing defaults.custom but overrides with custom.displayMode"
   - Demonstrates input panel with NO `defaults.custom` but WITH override `custom.displayMode`
   - Expected output shows overrides properly migrated to `custom.cellOptions`

### Problem Flow:

```
Original Dashboard (v37):
├─ table panel
├─ fieldConfig.defaults: {} (NO custom)
└─ fieldConfig.overrides: [{...custom.displayMode: "color-background"...}]
                              ↓ (Backend v38 migration)
After v38 Migration:
├─ table panel
├─ fieldConfig.defaults: {} (still NO custom)
├─ fieldConfig.overrides: [{...custom.cellOptions: {...}...}]
├─ _originallyHadFieldConfigCustom: false/unset (CRITICAL)
                              ↓ (Cleanup phase)
After Cleanup:
├─ table panel
├─ fieldConfig: DELETED (because it matched default and no marker)
└─ Result: Table loses ALL column formatting configuration
```

## Affected Components

1. **Primary:** `apps/dashboard/pkg/migration/frontend_defaults.go`
   - `filterDefaultValues()` function (lines 556-662)
   - Specifically the fieldConfig deletion logic (lines 602-626)

2. **Secondary:** `apps/dashboard/pkg/migration/schemaversion/v38.go`
   - Migration works correctly, but downstream cleanup doesn't account for its changes

3. **Dashboard Migration Pipeline:** `apps/dashboard/pkg/migration/migrate.go`
   - Migration sequence and cleanup orchestration (lines 65-135)

4. **Test Coverage:** `apps/dashboard/pkg/migration/schemaversion/v38_test.go`
   - Test validates v38 migration logic correctly
   - No integration test validates cleanup phase behavior

## Why Dashboards WITH Explicit `defaults.custom` Are Unaffected

When a dashboard explicitly contains `fieldConfig.defaults.custom`:
- `trackOriginalFieldConfigCustom()` sets `_originallyHadFieldConfigCustom = true`
- During cleanup, the special case on line 608 preserves the fieldConfig
- Even if fieldConfig matches default structure, it's NOT deleted

This is why older dashboards or manually-configured panels with explicit custom objects render correctly.

## Conditional Logic Failure

The cleanup uses insufficient conditions for fieldConfig preservation:
- ✗ Only checks if panel originally had `custom` (boolean marker)
- ✗ Doesn't check if fieldConfig contains non-default overrides
- ✗ Deletes fieldConfig if marker is false, even when overrides exist

The fix would need to either:
1. Preserve the `_originallyHadFieldConfigCustom` marker for panels with non-empty overrides, OR
2. Add logic to check if overrides exist before deleting fieldConfig, OR
3. Mark fieldConfig as "originally had something" when tracking non-empty overrides

## Recommendation

The fix should modify the cleanup logic in `frontend_defaults.go` to:
- Preserve fieldConfig if it contains non-empty overrides, regardless of the `_originallyHadFieldConfigCustom` marker
- OR set the marker to true when tracking overrides with field override properties
- This ensures field override configurations survive the cleanup phase, matching frontend behavior where overrides always persist when present
