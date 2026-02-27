# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary

The v38 migration function (`V38()` in `apps/dashboard/pkg/migration/schemaversion/v38.go`) introduces a regression where table panels without explicit `fieldConfig.defaults.custom` in the original JSON lose their field override configuration during dashboard migration to v10.4. The migration conditionally processes defaults only if `defaults.custom` exists, causing structural inconsistency with migrated overrides.

## Root Cause

**File:** `apps/dashboard/pkg/migration/schemaversion/v38.go` (lines 115-131)
**Function:** `processPanelsV38()`

The migration code has a critical conditional check that **skips processing field defaults for tables without explicit `custom` object**:

```go
// Process defaults.custom if it exists (LINE 115-127)
if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
    if custom, ok := defaults["custom"].(map[string]interface{}); ok {  // CONDITIONAL: custom MUST EXIST
        // Migrate displayMode to cellOptions in defaults
        if displayMode, exists := custom["displayMode"]; exists {
            if displayModeStr, ok := displayMode.(string); ok {
                custom["cellOptions"] = migrateTableDisplayModeToCellOptions(displayModeStr)
            }
            delete(custom, "displayMode")
        }
    }
}

// This ALWAYS runs, regardless of whether defaults.custom exists (LINE 131)
migrateOverrides(fieldConfig)
```

**The Problem:**
1. **For dashboards WITH explicit `fieldConfig.defaults.custom`:** Defaults are migrated, overrides are migrated, structure is consistent ✓
2. **For dashboards WITHOUT explicit `fieldConfig.defaults.custom`:**
   - Defaults migration is **skipped** (line 117 condition fails)
   - Overrides migration **still runs** (line 131 always executes)
   - This creates a **structural mismatch**: overrides reference `custom.cellOptions` but `defaults.custom` was never created

## Evidence

### Affected Migration Code

**File:** `apps/dashboard/pkg/migration/schemaversion/v38.go`

**Lines 115-131 - The Conditional Logic Failure:**
- Line 116: `if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {`
- Line 117: `if custom, ok := defaults["custom"].(map[string]interface{}); ok {` ← **This condition fails for dashboards without explicit custom**
  - The entire defaults migration block (lines 118-126) is skipped
- Line 131: `migrateOverrides(fieldConfig)` ← **This runs regardless**, migrating `custom.displayMode` → `custom.cellOptions` in field overrides

### Test Case Demonstrating the Issue

**File:** `apps/dashboard/pkg/migration/schemaversion/v38_test.go` (lines 444-596)

Test case: **"table with missing defaults.custom but overrides with custom.displayMode"**

```go
// INPUT: Table panel WITHOUT fieldConfig.defaults.custom
"fieldConfig": map[string]interface{}{
    "defaults": map[string]interface{}{},  // ← NO "custom" key
    "overrides": []interface{}{
        map[string]interface{}{
            "properties": []interface{}{
                map[string]interface{}{
                    "id": "custom.displayMode",  // ← Override references custom namespace
                    "value": "color-background",
                },
            },
        },
    },
}
```

After v38 migration:
- Overrides are migrated: `custom.displayMode` → `custom.cellOptions`
- But `defaults.custom` remains absent
- This structural inconsistency can cause rendering issues

### How Frontend Defaults Interact

**File:** `apps/dashboard/pkg/migration/frontend_defaults.go`

**Lines 102-117 - `applyPanelDefaults()` Behavior:**
```go
if fieldConfig, ok := panel["fieldConfig"].(map[string]interface{}); ok {
    if _, hasDefaults := fieldConfig["defaults"]; !hasDefaults {
        fieldConfig["defaults"] = map[string]interface{}{}  // ← Creates defaults
    }
    if _, hasOverrides := fieldConfig["overrides"]; !hasOverrides {
        fieldConfig["overrides"] = []interface{}{}          // ← Creates overrides
    }
}
```

**Critical Issue:** `applyPanelDefaults()` creates `fieldConfig.defaults` but **NOT** `fieldConfig.defaults.custom`. This is called BEFORE v38 migration runs, setting up the condition for the regression.

**Lines 1138-1169 - `trackOriginalFieldConfigCustom()` Tracking:**
The backend explicitly tracks which panels had `fieldConfig.defaults.custom` in the original JSON:
```go
func trackOriginalFieldConfigCustom(dashboard map[string]interface{}) {
    // ... marks panels with _originallyHadFieldConfigCustom = true
}
```

This flag is used during cleanup phase (lines 605-620) to preserve/restore custom objects for originally-saved panels. **Dashboards WITHOUT explicit custom never get this flag**, leaving them vulnerable during migration.

## Migration Sequence Analysis

From `apps/dashboard/pkg/migration/migrate.go` (lines 65-135):

1. **Line 67-71:** Track panels that originally had `fieldConfig.defaults.custom`
2. **Line 73-75:** Apply frontend defaults (creates empty `fieldConfig.defaults` but NOT `custom`)
3. **Line 119-127:** Run v38 migration
   - For panels with no original `custom`: defaults migration skipped, overrides migrated
   - Creates structural inconsistency
4. **Line 135:** Cleanup phase (uses the `_originallyHadFieldConfigCustom` flag)
   - Panels without the flag don't receive protection during cleanup
   - Can lead to silent loss of field configuration

## Affected Components

1. **Backend Migration:** `apps/dashboard/pkg/migration/schemaversion/v38.go`
   - `V38()` function
   - `processPanelsV38()` function
   - `migrateOverrides()` function (calls into the defaults migration implicitly through structural expectations)

2. **Migration Pipeline:** `apps/dashboard/pkg/migration/migrate.go`
   - Migration orchestration order
   - Frontend defaults application timing

3. **Frontend Defaults:** `apps/dashboard/pkg/migration/frontend_defaults.go`
   - `trackOriginalFieldConfigCustom()` - flags panels with original custom objects
   - `cleanupFieldConfigDefaults()` - cleanup logic that assumes structure consistency

4. **Table Panel Handling:** `public/app/plugins/panel/table/migrations.ts`
   - Frontend side migration mirrors the backend's displayMode → cellOptions transformation
   - Expects structural consistency between defaults and overrides

## Why Dashboards WITH Explicit `defaults.custom` Are Unaffected

When a dashboard explicitly saves `fieldConfig.defaults.custom`:

1. **Tracking:** `trackOriginalFieldConfigCustom()` marks it with `_originallyHadFieldConfigCustom = true`
2. **Migration:** v38's line 117 condition succeeds, defaults ARE processed
3. **Cleanup:** Lines 608-616 in `frontend_defaults.go` preserve the custom object
4. **Result:** Consistent structure with both defaults and overrides properly migrated

## Dashboard Schema Version Triggering Issue

- **Affected Range:** Schema versions **37 → 38** (specifically the v38 migration)
- **Entry Point:** When any dashboard with v37 (or earlier) is migrated to v38 (Grafana v10.4)
- **Detection:** Only affects table panels that either:
  - Have overrides with `custom.displayMode` properties, AND
  - Did NOT have explicit `fieldConfig.defaults.custom` in the original JSON

## Recommendation

**Root Fix Strategy:**

The v38 migration function should ensure `fieldConfig.defaults.custom` object exists before processing overrides for table panels. Specifically:

1. **Before calling `migrateOverrides()`:** Check if fieldConfig has overrides with `custom.*` properties
2. **If overrides exist with `custom.* properties` AND defaults.custom does not exist:** Create an empty `defaults.custom` object
3. **Alternative approach:** Modify the conditional at line 116-117 to handle the missing `defaults.custom` case by creating it on-demand

This ensures structural consistency: if overrides reference `custom.*` properties, `defaults.custom` must exist in the field configuration, even if empty.

**Secondary safeguard:** Review the cleanup phase logic to ensure panels without `_originallyHadFieldConfigCustom` flag don't lose their field configuration structure when overrides are present.

## Files Involved

- **Primary:** `apps/dashboard/pkg/migration/schemaversion/v38.go`
- **Secondary:** `apps/dashboard/pkg/migration/frontend_defaults.go`
- **Orchestration:** `apps/dashboard/pkg/migration/migrate.go`
- **Test Reference:** `apps/dashboard/pkg/migration/schemaversion/v38_test.go` (line 444 test case)
- **Frontend Mirror:** `public/app/plugins/panel/table/migrations.ts`
