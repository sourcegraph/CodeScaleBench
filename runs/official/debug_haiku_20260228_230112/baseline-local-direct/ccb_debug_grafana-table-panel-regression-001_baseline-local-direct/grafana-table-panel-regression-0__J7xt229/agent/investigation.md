# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary

The V38 schema migration silently drops field override configurations for table panels that don't have explicit `fieldConfig.defaults.custom` defined. This causes table cell display modes (column widths, text alignment, cell display modes) to be lost when dashboards are imported from v10.3 to v10.4. Dashboards with explicit `defaults.custom` are unaffected because the migration logic correctly processes their overrides.

## Root Cause

**File:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go`

**Functions:** `processPanelsV38()` (lines 90-137) and `migrateOverrides()` (lines 139-180)

**Mechanism:** The V38 migration has a critical conditional guard that prevents field override migration for dashboards without explicit `defaults.custom`:

```go
// v38.go lines 115-135
defaults, ok := fieldConfig["defaults"].(map[string]interface{})
if !ok {
    continue  // ← SKIPS ENTIRE PANEL if defaults missing
}

custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue  // ← SKIPS ENTIRE PANEL if custom missing
}

// Migrate displayMode to cellOptions
if displayMode, exists := custom["displayMode"]; exists {
    if displayModeStr, ok := displayMode.(string); ok {
        custom["cellOptions"] = migrateTableDisplayModeToCellOptions(displayModeStr)
    }
    delete(custom, "displayMode")
}

// Update any overrides referencing the cell display mode
migrateOverrides(fieldConfig)  // ← NEVER REACHED if custom doesn't exist
```

The problem: If a dashboard never had `fieldConfig.defaults.custom` defined, the code skips directly to the next panel without ever calling `migrateOverrides(fieldConfig)`. This means any field overrides with `custom.displayMode` properties are left unmigrated.

## Evidence

### The Bug in Context

1. **Migration Execution Flow** (`/workspace/apps/dashboard/pkg/migration/migrate.go` lines 119-127):
   - V38 migration is applied to all dashboards being migrated from schema version 37 → 38
   - The migration runs during the migration pipeline after frontend defaults are applied

2. **Missing Test Coverage** (`/workspace/apps/dashboard/pkg/migration/schemaversion/v38_test.go`):
   - All test cases (lines 10-442) have panels with explicit `fieldConfig.defaults.custom` defined
   - No test case covers the scenario: table panel with overrides but NO explicit `defaults.custom`
   - This gap allowed the regression to go undetected

3. **Frontend Behavior Mismatch** (`/workspace/public/app/features/dashboard/state/DashboardMigrator.ts` lines 658-669):
   - The frontend v38 migration ALWAYS processes overrides, regardless of `defaults.custom` existence:
   ```typescript
   if (panel.fieldConfig?.overrides) {
     for (const override of panel.fieldConfig.overrides) {
       for (let j = 0; j < (override.properties?.length || 0); j++) {
         if (override.properties[j].id === 'custom.displayMode') {
           override.properties[j].id = 'custom.cellOptions';
           override.properties[j].value = migrateTableDisplayModeToCellOptions(overrideDisplayMode);
         }
       }
     }
   }
   ```
   - The backend implementation incorrectly gates override migration behind the `defaults.custom` check

4. **V35 Comparison** (`/workspace/apps/dashboard/pkg/migration/schemaversion/v35.go` lines 67-68):
   - V35 shows the correct pattern for defensive code:
   ```go
   defaults, _ := fieldConfig["defaults"].(map[string]interface{})
   custom, _ := defaults["custom"].(map[string]interface{})
   ```
   - Uses `_, _` to ignore missing values and continue processing, rather than early returns
   - This allows override processing to happen even when defaults don't exist

### Dashboard Schema Context

**Affected dashboards:** Those saved in Grafana v10.3 or earlier that have:
- Table panels with field overrides specifying `custom.displayMode`
- NO explicit `fieldConfig.defaults.custom` object

**Why this configuration exists:**
- Frontend may not have required explicit `defaults.custom` in older versions
- Users could have dashboards where only overrides specified display modes
- The missing `defaults.custom` would be filled by frontend defaults at runtime

## Affected Components

1. **Migration Pipeline** (`apps/dashboard/pkg/migration/`)
   - `schemaversion/v38.go` - The buggy migration function
   - `migrate.go` - Orchestrates migrations (lines 119-127)

2. **Frontend Migration** (`public/app/features/dashboard/state/`)
   - `DashboardMigrator.ts` - Shows correct override handling pattern (lines 644-674)

3. **Test Infrastructure** (`apps/dashboard/pkg/migration/schemaversion/`)
   - `v38_test.go` - Missing test coverage for the regression scenario

4. **Cleanup Logic** (`apps/dashboard/pkg/migration/`)
   - `frontend_defaults.go:trackOriginalFieldConfigCustom()` - Tracks custom field presence

## Why Dashboards With Explicit `defaults.custom` Are Unaffected

When a dashboard has explicit `fieldConfig.defaults.custom`:

1. Line 120-123 condition succeeds: `custom, ok := defaults["custom"].(map[string]interface{})`
2. Code proceeds to line 135: `migrateOverrides(fieldConfig)` is called
3. All field overrides with `custom.displayMode` are properly migrated to `custom.cellOptions`

The regression only manifests when `defaults.custom` is absent from the saved dashboard JSON.

## Exact Conditional Logic Failure

**The problematic code flow:**

```
Input: Table panel with NO defaults.custom but WITH overrides[].properties[].id="custom.displayMode"
↓
processPanelsV38() executes
↓
p["type"] == "table" ✓
fieldConfig exists ✓
defaults exists ✓
custom EXISTS? ✗ (type assertion fails, ok=false)
↓
if !ok { continue } → JUMPS TO NEXT PANEL
↓
migrateOverrides(fieldConfig) NEVER CALLED
↓
Field overrides still reference "custom.displayMode" (unmigrated)
↓
Migration complete: schema version set to 38
↓
Result: Table renders without field override formatting
```

## Which Schema Version Triggers Issue

- **Trigger Version:** 38
- **Condition:** Dashboard with schemaVersion < 38
- **Migration Path:** Grafana v10.3 → v10.4 (schema v37 → v38)
- **Detection:** When dashboard is migrated to schema version 38 during import

## Recommendation

The `migrateOverrides()` function should be called unconditionally for all table panels, regardless of whether `defaults.custom` exists.

**Correct approach (pattern from v35):**
1. Use defensive unpacking: `defaults, _ := fieldConfig["defaults"].(map[string]interface{})`
2. Always call `migrateOverrides()` for table panels with field overrides
3. Allow `migrateOverrides()` to handle nil/missing defaults gracefully

This maintains consistency with the frontend implementation and ensures field overrides are always processed during the v38 migration, whether or not the dashboard had explicit `defaults.custom` in the original saved JSON.
