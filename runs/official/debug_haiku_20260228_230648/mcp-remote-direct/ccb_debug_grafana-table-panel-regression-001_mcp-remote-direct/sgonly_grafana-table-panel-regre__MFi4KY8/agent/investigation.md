# Investigation Report

## Dashboard Migration v38 Table Panel Regression

## Summary

The v38 dashboard migration fails to properly initialize `fieldConfig.defaults.custom` for table panels that have field overrides with `custom.displayMode` but do NOT have an explicit `fieldConfig.defaults.custom` object in the original dashboard JSON. This causes field override configuration to be silently dropped or incorrectly rendered during dashboard import in Grafana v10.4.

## Root Cause

**File**: `apps/dashboard/pkg/migration/schemaversion/v38.go` (lines 115-131)

**Conditional Logic That Fails**: Lines 116-127

```go
// Process defaults.custom if it exists
if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
    if custom, ok := defaults["custom"].(map[string]interface{}); ok {
        // Migrate displayMode to cellOptions in defaults
        if displayMode, exists := custom["displayMode"]; exists {
            if displayModeStr, ok := displayMode.(string); ok {
                custom["cellOptions"] = migrateTableDisplayModeToCellOptions(displayModeStr)
            }
            // Delete the legacy field
            delete(custom, "displayMode")
        }
    }
}
```

The issue is **nested conditional logic that only creates `cellOptions` if `defaults.custom` already exists**. When a table panel has:
- `fieldConfig.defaults` (exists)
- `fieldConfig.defaults.custom` (DOES NOT exist)
- `fieldConfig.overrides[*].properties[*].id = "custom.displayMode"` (exists with display mode values)

The code skips the entire defaults migration block (lines 116-127) because the second condition `if custom, ok := defaults["custom"]` fails.

## Why Dashboards With Explicit defaults.custom Work

When `fieldConfig.defaults.custom` is explicitly present in the original dashboard JSON:
1. The nested conditional succeeds
2. The displayMode is migrated to cellOptions (line 121)
3. The legacy field is deleted (line 124)
4. Field overrides are then processed correctly (line 131)

## Why Dashboards Without defaults.custom Fail

When `fieldConfig.defaults.custom` is **NOT** present (or is created but empty by `applyPanelDefaults`):
1. The nested conditional `if custom, ok := defaults["custom"]` fails
2. **Lines 116-127 are completely skipped**
3. `migrateOverrides()` is called (line 131) and converts `custom.displayMode` to `custom.cellOptions` in the overrides
4. BUT `fieldConfig.defaults.custom` still doesn't exist
5. Frontend table rendering may expect `defaults.custom` to exist if ANY overrides reference custom properties
6. This asymmetry causes the field override configuration to be silently dropped or incorrectly evaluated

## Evidence

**File**: `apps/dashboard/pkg/migration/schemaversion/v38.go`
- Lines 75-87: V38 function entry point
- Lines 90-132: processPanelsV38 function
- Lines 115-127: **Root cause** - nested conditional that skips when defaults.custom is missing
- Lines 129-131: Override migration that always runs (regardless of defaults.custom)
- Lines 135-176: migrateOverrides function (handles override transformation)

**File**: `apps/dashboard/pkg/migration/schemaversion/v38_test.go`
- Lines 443-600: Test case "table with missing defaults.custom but overrides with custom.displayMode"
- Lines 450-477: Panel 1 input - NO custom in defaults, BUT HAS custom.displayMode in overrides
- Lines 480-515: Panel 2 input - EMPTY custom in defaults, BUT HAS custom.displayMode in overrides
- Lines 523-553, 556-597: Expected output shows overrides SHOULD be migrated successfully

The tests demonstrate the migration should work even without explicit defaults.custom, but the nested conditional prevents initialization.

**File**: `apps/dashboard/pkg/migration/frontend_defaults.go`
- Lines 102-117: `applyPanelDefaults()` creates `fieldConfig` with empty defaults but does NOT create `defaults.custom`
- Lines 1138-1158: `trackOriginalFieldConfigCustom()` and `trackPanelOriginalFieldConfigCustom()` only mark panels that originally had defaults.custom
- Lines 605-620: Cleanup logic that handles preservation of `_originallyHadFieldConfigCustom`

**File**: `public/app/features/dashboard/state/DashboardMigrator.ts`
- Lines 650-652: Frontend migration code that assumes `panel.fieldConfig.defaults.custom` exists when setting cellOptions
- Lines 659-669: Frontend override processing that ALWAYS runs and correctly handles custom.displayMode → custom.cellOptions

## Affected Components

1. **Backend Dashboard Migration System** (`apps/dashboard/pkg/migration/`)
   - `schemaversion/v38.go` - Primary source of regression
   - `frontend_defaults.go` - Interaction with defaults application
   - `migrate.go` - Migration pipeline orchestration

2. **Schema Version Processing**
   - Dashboard schema v37 → v38 migration path
   - Impacts all dashboards at schema version 37 or lower with table panels

3. **Table Panel Rendering**
   - Table panels with field overrides but no explicit defaults.custom
   - Field configuration merging and override application

4. **Frontend Migration** (secondary issue)
   - `public/app/features/dashboard/state/DashboardMigrator.ts` - lines 650-652
   - Assumes defaults.custom exists when setting cellOptions

## Dashboard Schema Version That Triggers Issue

**Schema Version 37 → 38 Migration**

Affects all dashboards at or below schema version 37 (versions v10.3 and earlier) that contain table panels with field overrides but without explicit `fieldConfig.defaults.custom`.

## Recommendation

**Fix Strategy**: Ensure `fieldConfig.defaults.custom` exists BEFORE processing overrides in v38 migration.

The migration function should:

1. **Check if ANY override has custom.displayMode** before processing
2. **Ensure defaults.custom exists** - create empty object if needed for table panels with custom overrides
3. **Then process both defaults and overrides** in consistent order

The fix should:
- Create `fieldConfig.defaults.custom` if it doesn't exist when processing table panels with custom field overrides
- Or alternatively, move the custom creation outside the nested conditional to execute unconditionally for table panels
- Ensure frontend and backend migration logic are synchronized regarding custom object initialization

This prevents the asymmetric state where overrides reference custom properties but defaults.custom doesn't exist, which causes rendering and configuration issues in the frontend table panel component.
