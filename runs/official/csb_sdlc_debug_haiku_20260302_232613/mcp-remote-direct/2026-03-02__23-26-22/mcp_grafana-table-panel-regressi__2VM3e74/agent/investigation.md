# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary
The v38 schema migration in Grafana fails to properly initialize `fieldConfig.defaults.custom` for table panels whose dashboard JSON does not explicitly include this property. This causes field override configuration to be silently dropped during migration, affecting any table panels saved in v10.3 without explicit `fieldConfig.defaults.custom` structures.

## Root Cause

**Location**: `apps/dashboard/pkg/migration/schemaversion/v38.go`, lines 115-127

**Mechanism**: The V38 migration function conditionally processes `fieldConfig.defaults.custom` only if it already exists in the parsed dashboard JSON:

```go
// Process defaults.custom if it exists
if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
    if custom, ok := defaults["custom"].(map[string]interface{}); ok {
        // Migrate displayMode to cellOptions in defaults
        if displayMode, exists := custom["displayMode"]; exists {
            // ... migration logic ...
        }
    }
}
```

The conditional logic at line 117 (`if custom, ok := defaults["custom"].(map[string]interface{})`) only executes if `custom` already exists. For dashboards where `fieldConfig.defaults.custom` was never explicitly set in the v10.3 saved JSON, this check fails silently, causing the entire migration block to be skipped.

## Conditional Logic Failure

**Lines 116-127** contain the bug:
- Line 116: Checks if `defaults` exists ✓
- Line 117: Checks if `custom` exists ✗ **FAILS for dashboards without explicit custom**
- Lines 119-125: Migration logic is skipped entirely

This is inconsistent with line 131, which calls `migrateOverrides(fieldConfig)` regardless of whether `defaults.custom` exists, showing that the code was intended to handle both scenarios.

## Why Dashboards WITH Explicit `custom` Work

Dashboards with explicit `fieldConfig.defaults.custom` in the saved JSON successfully pass the type assertion at line 117, allowing the migration logic to execute. The migrateOverrides function is then called and processes any field overrides correctly.

## Schema Version and Trigger

**Affected Version**: Schema v38 (table panel displayMode → cellOptions migration)

**Trigger Condition**: The bug manifests specifically when:
1. Dashboard was saved from v10.3 or earlier
2. Table panel does NOT have `fieldConfig.defaults.custom` explicitly set in the JSON
3. Table panel MAY have field overrides on custom properties (e.g., column widths, alignment)

## Files and Functions Involved

### Backend Migration Chain
1. **Migration Entry Point**: `apps/dashboard/pkg/migration/migrate.go`, line 119-127
   - Executes registered migration functions sequentially
   - Calls V38 during schema version 37→38 migration

2. **V38 Migration Function**: `apps/dashboard/pkg/migration/schemaversion/v38.go`
   - `V38()`: Line 75-86 (entry point)
   - `processPanelsV38()`: Line 90-132 (main processing loop)
   - **Bug location**: Line 116-127 (conditional processing of defaults.custom)
   - `migrateOverrides()`: Line 136-176 (override migration - works correctly)

3. **Field Config Tracking**: `apps/dashboard/pkg/migration/frontend_defaults.go`
   - `trackOriginalFieldConfigCustom()`: Line 1140-1148
   - `trackPanelOriginalFieldConfigCustom()`: Line 1151-1169
   - **Issue**: Only marks `_originallyHadFieldConfigCustom = true` if custom was ALREADY present in input
   - Does NOT identify panels that SHOULD have had custom but didn't

### Frontend Table Migration
1. **Table Migration Handler**: `public/app/plugins/panel/table/migrations.ts`
   - `tableMigrationHandler()`: Line 23-35
   - `migrateTextWrapToFieldLevel()`: Line 306-334
     - Line 329: Assumes `fieldConfig.defaults.custom` exists: `panel.fieldConfig.defaults.custom = panel.fieldConfig.defaults.custom ?? {}`
     - **Problem**: If backend v38 didn't create this, field config from overrides may not be properly migrated

2. **Frontend Defaults**: `public/app/features/dashboard/state/PanelModel.ts`, lines 130-132
   - PanelModel constructor defaults create `fieldConfig.defaults` but NOT `custom`

## Evidence with Code References

### The Conditional Bug
**File**: `apps/dashboard/pkg/migration/schemaversion/v38.go`, line 116-117
```go
if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
    if custom, ok := defaults["custom"].(map[string]interface{}); ok {  // ← FAILS if custom doesn't exist
        // Migration only happens if this passes
    }
}
```

### Contrast with Overrides Processing
**File**: `apps/dashboard/pkg/migration/schemaversion/v38.go`, line 131
```go
// This is called regardless of whether defaults.custom exists ✓
migrateOverrides(fieldConfig)
```

### Test Gap
**File**: `apps/dashboard/pkg/migration/schemaversion/v38_test.go`, lines 1-150
- All test cases provide explicit `fieldConfig.defaults.custom`
- No test case covers the regression scenario (table panel WITHOUT explicit custom)
- Lines 22-29: First test case shows custom is always explicitly provided

**File**: `apps/dashboard/pkg/migration/testdata/input/v38.timeseries_table_display_mode.json`, lines 1-187
- All table panels (ids 1-12) have explicit `"custom": {"displayMode": ...}`
- No test data for the missing-custom scenario

### Frontend Assumption
**File**: `public/app/plugins/panel/table/migrations.ts`, line 329
```typescript
panel.fieldConfig.defaults.custom = panel.fieldConfig.defaults.custom ?? {};
```
- Frontend assumes it can always operate on `defaults.custom`
- If backend didn't create it during v38, migrations may fail silently

## Affected Components

1. **Dashboard Migration System** (`apps/dashboard/pkg/migration/`)
   - Schema version handler pipeline
   - Field configuration tracking

2. **Table Panel Plugin** (`public/app/plugins/panel/table/`)
   - Table migrations (migrateTextWrapToFieldLevel, migrateHiddenFields, migrateFooterV2)
   - Field override preservation

3. **Frontend Defaults System** (`apps/dashboard/pkg/migration/frontend_defaults.go`)
   - Cleanup logic that removes empty custom objects
   - Field config preservation logic

## Recommendation

**Fix Strategy**:
Modify V38 migration to ENSURE `fieldConfig.defaults.custom` exists before attempting any migrations. The migration should either:

1. **Option A** (Preferred): Create empty `defaults.custom` if it doesn't exist
   - Before processing: Ensure `fieldConfig["defaults"]["custom"]` is initialized
   - Allows all downstream logic to work consistently

2. **Option B**: Restructure conditional logic to handle missing custom
   - Initialize custom on-demand: `if custom == nil { custom = {} }`
   - Process overrides independently of defaults existence

**Required Changes**:
1. Update `V38()` or `processPanelsV38()` to initialize `defaults.custom` when missing
2. Add test cases in `v38_test.go` for table panels WITHOUT explicit `fieldConfig.defaults.custom`
3. Add test data file for the regression scenario (table panel with no custom, but with overrides)
4. Verify that field overrides on custom properties are preserved during migration

**Affected Test Files**:
- `apps/dashboard/pkg/migration/schemaversion/v38_test.go`
- `apps/dashboard/pkg/migration/testdata/input/v38.timeseries_table_display_mode.json`
- `apps/dashboard/pkg/migration/testdata/output/*/v38.*.json`
