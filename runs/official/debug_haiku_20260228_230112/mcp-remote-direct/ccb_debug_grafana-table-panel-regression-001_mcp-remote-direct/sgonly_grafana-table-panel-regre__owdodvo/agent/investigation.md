# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary

The table panel field override configuration regression in v10.4 stems from the conditional logic in the V38 backend migration that only processes `fieldConfig.defaults.custom` when it explicitly exists in the saved dashboard JSON. When dashboards lack explicit `fieldConfig.defaults.custom`, the migration skips creating the defaults structure, while simultaneously migrating field overrides that reference `custom.displayMode`. This asymmetry can cause field override configuration to be silently dropped if downstream cleanup logic removes fieldConfig structures that are considered "default values."

## Root Cause

**File:** `apps/dashboard/pkg/migration/schemaversion/v38.go` (lines 115-127)

**Mechanism:** The V38 migration function `processPanelsV38()` contains a nested conditional that only processes table panel field configuration if `fieldConfig.defaults.custom` already exists:

```go
if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
    if custom, ok := defaults["custom"].(map[string]interface{}); ok {
        // ONLY processes if custom exists
        if displayMode, exists := custom["displayMode"]; exists {
            custom["cellOptions"] = migrateTableDisplayModeToCellOptions(displayModeStr)
            delete(custom, "displayMode")
        }
    }
}
```

**Critical Conditional Logic (Line 117):**
```go
if custom, ok := defaults["custom"].(map[string]interface{}); ok {
```

This check returns `false` when `defaults["custom"]` does not exist or is not a map, causing the entire block to be skipped.

## Evidence

### 1. Test Case Confirming the Scenario
**File:** `apps/dashboard/pkg/migration/schemaversion/v38_test.go` (lines 443-599)

The test case named "table with missing defaults.custom but overrides with custom.displayMode" explicitly tests this exact scenario:

**Input (lines 454-476):**
- Table panel with `"defaults": map[string]interface{}{}` — **NO custom object**
- Field overrides containing `"id": "custom.displayMode"` with value `"color-background"`

**Expected Output (lines 527-553):**
- `"defaults": map[string]interface{}{}` — **custom object is NOT created**
- Overrides are correctly migrated from `"id": "custom.displayMode"` to `"id": "custom.cellOptions"`
- cellOptions properly contains `{"type": "color-background", "mode": "gradient"}`

This demonstrates that the V38 migration correctly handles overrides independently of defaults.custom existence.

### 2. Migration Function Flow
**File:** `apps/dashboard/pkg/migration/schemaversion/v38.go` (lines 129-131)

The `migrateOverrides()` function is **always called**, regardless of whether defaults.custom exists:

```go
// Update any overrides referencing the cell display mode
// This must be called regardless of whether defaults.custom exists
migrateOverrides(fieldConfig)
```

This is correct and ensures overrides are processed for all dashboards.

### 3. Field Override Migration Implementation
**File:** `apps/dashboard/pkg/migration/schemaversion/v38.go` (lines 159-173)

The `migrateOverrides()` function correctly transforms override properties:

```go
if prop["id"] == "custom.displayMode" {
    prop["id"] = "custom.cellOptions"
    if value, ok := prop["value"]; ok {
        if valueStr, ok := value.(string); ok {
            prop["value"] = migrateTableDisplayModeToCellOptions(valueStr)
        }
    } else {
        // Handles case where no value exists
        prop["value"] = map[string]interface{}{}
    }
}
```

This logic correctly migrates the property ID and transforms the value.

### 4. Frontend Cleanup Sensitivity
**File:** `apps/dashboard/pkg/migration/frontend_defaults.go` (lines 1138-1169)

The backend tracks which panels originally had `fieldConfig.defaults.custom`:

```go
func trackOriginalFieldConfigCustom(dashboard map[string]interface{}) {
    if panels, ok := dashboard["panels"].([]interface{}); ok {
        for _, panelInterface := range panels {
            if panel, ok := panelInterface.(map[string]interface{}); ok {
                trackPanelOriginalFieldConfigCustom(panel)
            }
        }
    }
}

func trackPanelOriginalFieldConfigCustom(panel map[string]interface{}) {
    if fieldConfig, ok := panel["fieldConfig"].(map[string]interface{}); ok {
        if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
            if _, hasCustom := defaults["custom"]; hasCustom {
                panel["_originallyHadFieldConfigCustom"] = true
            }
        }
    }
}
```

**The Critical Conditional (Line 1155):**
```go
if _, hasCustom := defaults["custom"]; hasCustom {
    panel["_originallyHadFieldConfigCustom"] = true
}
```

Panels without original `fieldConfig.defaults.custom` are **NOT marked** with the `_originallyHadFieldConfigCustom` flag.

### 5. Cleanup Phase Preservation Logic
**File:** `apps/dashboard/pkg/migration/frontend_defaults.go` (lines 605-619, 655-659)

During cleanup, the fieldConfig is only preserved if it was originally present:

```go
if panel["_originallyHadFieldConfigCustom"] == true {
    // Preserve custom object if it was originally present
    if _, hasCustom := defaults["custom"]; !hasCustom {
        defaults["custom"] = map[string]interface{}{}
    }
}
```

For dashboards without original `fieldConfig.defaults.custom`, this preservation logic is **skipped**.

## Affected Components

1. **Backend Migration Engine:**
   - `apps/dashboard/pkg/migration/schemaversion/v38.go` — V38 migration function
   - `apps/dashboard/pkg/migration/migrate.go` — Migration orchestration

2. **Frontend Migrations:**
   - `public/app/plugins/panel/table/migrations.ts` — Table panel migration handler
   - `public/app/features/dashboard/state/DashboardMigrator.ts` — Dashboard-level migration logic

3. **Cleanup Pipeline:**
   - `apps/dashboard/pkg/migration/frontend_defaults.go` — Default value filtering and tracking

4. **Dashboard Schema Versions:**
   - Affected: Schema version 37 → 38 transition
   - Dashboards saved before v10.4 without explicit `fieldConfig.defaults.custom`

## Why Dashboards with Explicit `defaults.custom` Are Unaffected

Dashboards that **explicitly** saved `fieldConfig.defaults.custom` (even if empty):
1. Are marked with `_originallyHadFieldConfigCustom = true` during tracking (line 1156)
2. Have their fieldConfig preserved during cleanup (lines 655-659)
3. The overrides are maintained in the fieldConfig structure
4. Field override configuration remains accessible to the frontend

## Recommendation

The root cause is the **conditional processing of field configuration in V38** that creates an asymmetry: defaults processing is conditional on existence, while override processing is unconditional. This, combined with the cleanup logic that uses `_originallyHadFieldConfigCustom` to determine preservation, creates the regression.

**Recommended Fix Approaches:**

1. **Ensure defaults.custom is always created** in V38 migration as an empty object for all table panels, even if no displayMode exists, to match the "custom object was present" state
2. **OR preserve fieldConfig during cleanup** if it contains non-empty overrides, regardless of whether defaults.custom was originally present
3. **OR track at the override level** in addition to the defaults level, to ensure field override configuration is never dropped during cleanup

**Strategic Fix:** The safest approach is option 1 — ensuring defaults.custom is created as an empty object during V38 migration for all table panels. This makes the defaults structure explicitly present and guarantees the tracking flag is set correctly, ensuring the cleanup logic preserves the fieldConfig.
