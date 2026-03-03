# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary

The V38 table panel migration silently drops field override configurations for dashboards that don't have an explicit `fieldConfig.defaults.custom` object. The migration's defensive check at line 120-123 of `v38.go` skips entire panels if the custom object doesn't exist, preventing field overrides with `custom.displayMode` references from being migrated to the new `custom.cellOptions` format.

## Root Cause

**File:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go`
**Function:** `processPanelsV38()` (lines 90-137)
**Problematic Code Block:** Lines 120-123

```go
custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue  // <-- BUG: Skips entire panel if custom doesn't exist
}
```

### The Mechanism of Failure

1. **V38 checks for `custom` object existence** (line 120): The code performs a type assertion to verify that `fieldConfig.defaults.custom` exists as a map.

2. **Early exit on missing custom** (lines 121-123): If `custom` doesn't exist, the code executes `continue`, skipping to the next panel without processing field overrides.

3. **Field overrides never get migrated** (line 135): Since `migrateOverrides(fieldConfig)` is only called after the `custom` object check, overrides are never processed for panels lacking explicit `defaults.custom`.

4. **Orphaned legacy field override references**: Field overrides with property IDs like `"custom.displayMode"` remain unmigrated, pointing to a legacy property that the table panel no longer recognizes.

### Example of Broken Dashboard

**Input (Saved Dashboard - v37 schema)**:
```json
{
  "panels": [{
    "type": "table",
    "fieldConfig": {
      "defaults": {},
      "overrides": [{
        "matcher": {"id": "byName", "options": "CPU"},
        "properties": [{
          "id": "custom.displayMode",
          "value": "color-background"
        }]
      }]
    }
  }]
}
```

**After V38 Migration (Broken)**:
```json
{
  "panels": [{
    "type": "table",
    "fieldConfig": {
      "defaults": {},
      "overrides": [{
        "matcher": {"id": "byName", "options": "CPU"},
        "properties": [{
          "id": "custom.displayMode",  // <-- Still using legacy property!
          "value": "color-background"  // <-- Should be cellOptions object
        }]
      }]
    }
  }]
}
```

## Why Dashboards with Explicit `defaults.custom` Are Unaffected

**Input (Saved Dashboard - v37 schema with explicit custom)**:
```json
{
  "panels": [{
    "type": "table",
    "fieldConfig": {
      "defaults": {
        "custom": {
          "displayMode": "color-background"
        }
      },
      "overrides": [{
        "matcher": {"id": "byName", "options": "CPU"},
        "properties": [{
          "id": "custom.displayMode",
          "value": "gradient-gauge"
        }]
      }]
    }
  }]
}
```

**After V38 Migration (Correct)**:
```json
{
  "panels": [{
    "type": "table",
    "fieldConfig": {
      "defaults": {
        "custom": {
          "cellOptions": {
            "type": "color-background",
            "mode": "basic"
          }
        }
      },
      "overrides": [{
        "matcher": {"id": "byName", "options": "CPU"},
        "properties": [{
          "id": "custom.cellOptions",  // <-- Properly migrated
          "value": {
            "type": "gauge",
            "mode": "gradient"
          }
        }]
      }]
    }
  }]
}
```

**Reason for Success:** The `custom` object exists (line 120 check passes), so the code continues to line 135 and calls `migrateOverrides(fieldConfig)`, which properly converts both the defaults and all override property IDs from `custom.displayMode` to `custom.cellOptions`.

## Evidence

### Migration Pipeline Context

**File:** `/workspace/apps/dashboard/pkg/migration/migrate.go`
**Lines:** 69-126

The migration pipeline has specific ordering:
1. **Line 69-71**: `trackOriginalFieldConfigCustom()` marks panels that originally had `custom`
2. **Line 75**: `applyFrontendDefaults()` applies frontend defaults - **does NOT create `defaults.custom`** (see frontend_defaults.go lines 102-117)
3. **Lines 119-126**: Migration loop runs V38 - expects `custom` to exist

### Frontend Defaults Don't Create Custom Object

**File:** `/workspace/apps/dashboard/pkg/migration/frontend_defaults.go`
**Lines:** 102-117

```go
if _, exists := panel["fieldConfig"]; !exists {
    panel["fieldConfig"] = map[string]interface{}{
        "defaults":  map[string]interface{}{},  // <-- empty, no custom
        "overrides": []interface{}{},
    }
}
```

The default panel creation does **not** create a `defaults.custom` object. This is intentional to match frontend behavior, but creates the precondition for the V38 regression.

### V38 Migration Doesn't Handle Missing Custom

**File:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go`
**Lines:** 110-137

```go
fieldConfig, ok := p["fieldConfig"].(map[string]interface{})
if !ok {
    continue  // Skip if no fieldConfig
}

defaults, ok := fieldConfig["defaults"].(map[string]interface{})
if !ok {
    continue  // Skip if no defaults
}

custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue  // REGRESSION: Skip entire panel if no custom object
}

// Only reached if custom exists - migrateOverrides never called otherwise
migrateOverrides(fieldConfig)
```

The `migrateOverrides()` function (lines 140-180) is only called if `custom` exists. This function is responsible for converting override property IDs from `"custom.displayMode"` to `"custom.cellOptions"`.

### Field Override Migration Logic

**File:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go`
**Lines:** 140-180 (migrateOverrides function)

```go
func migrateOverrides(fieldConfig map[string]interface{}) {
    overrides, ok := fieldConfig["overrides"].([]interface{})
    if !ok {
        return
    }

    for _, override := range overrides {
        o, ok := override.(map[string]interface{})
        if !ok {
            continue
        }

        properties, ok := o["properties"].([]interface{})
        if !ok {
            continue
        }

        for _, property := range properties {
            prop, ok := property.(map[string]interface{})
            if !ok {
                continue
            }

            // Update the id to cellOptions
            if prop["id"] == "custom.displayMode" {
                prop["id"] = "custom.cellOptions"
                if value, ok := prop["value"]; ok {
                    if valueStr, ok := value.(string); ok {
                        prop["value"] = migrateTableDisplayModeToCellOptions(valueStr)
                    }
                }
            }
        }
    }
}
```

This critical function is **never invoked** for panels without explicit `defaults.custom`.

## Affected Components

### Core Migration System
- **Package:** `github.com/grafana/grafana/apps/dashboard/pkg/migration`
- **Key Files:**
  - `v38.go` - The V38 schema migration (problematic)
  - `migrate.go` - Migration pipeline orchestration
  - `frontend_defaults.go` - Default value application
  - `migrations.go` - Migration registry (V38 is registered at line 74)

### Frontend Code References
- **File (mentioned in v38.go comments):** `public/app/features/dashboard/state/DashboardMigrator.ts:880`
- The comment at line 173 of v38.go references frontend migration logic

### Impact Scope
- **Affected Panel Type:** Table panels specifically (v38.go line 106: `if p["type"] != "table"`)
- **Affected Schema Versions:** Dashboards with schemaVersion < 38 that have:
  - Table panels without explicit `fieldConfig.defaults.custom`
  - Field overrides referencing `custom.displayMode`
- **Affected Table Panel Features:**
  - Column display modes (gauge variants, color backgrounds)
  - Any column formatting applied via field overrides
  - Cell rendering options

## Recommendation

### Fix Strategy

The V38 migration should handle the case where `defaults.custom` doesn't exist but overrides may still contain `custom.displayMode` references. Three potential approaches:

**Option 1 (Minimal Change):** Create empty `custom` object if needed for override processing
```go
custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    custom = map[string]interface{}{}
    defaults["custom"] = custom
}
```

**Option 2 (Explicit Logic):** Modify `migrateOverrides()` to work even without `custom` in defaults
- Keep override migration logic separate from defaults migration
- Call `migrateOverrides()` regardless of whether `custom` exists

**Option 3 (Frontend Alignment):** Modify frontend defaults to always create `custom` for table panels
- Ensure `applyPanelDefaults()` creates `defaults.custom` for table panels
- Prevents the precondition from occurring

### Root Cause Pattern

This is a **defensive programming regression**: the code assumes "if `custom` doesn't exist in defaults, there's nothing to migrate." This assumption fails because:
- Field overrides are independent of field defaults
- Overrides can reference properties that don't exist in defaults
- The migration must handle overrides separately from defaults

### Testing Gap

The V38 test suite (`v38_test.go`) only covers cases where `fieldConfig.defaults.custom` is explicitly present. No test case exists for:
- Table panels with no `fieldConfig.defaults.custom`
- Table panels with field overrides but no default custom configuration
- The regression scenario (dashboards saved v10.3 without explicit custom)

This testing gap allowed the regression to slip through quality checks.

## Timeline Context

- **Schema Version:** 38 (from v37)
- **Affected Version Range:** Dashboards upgraded from v10.3 → v10.4+
- **Deployment Impact:** Silent data corruption (field configuration loss) on dashboard import
- **User Visible Impact:** Table column formatting lost (widths, alignment, display modes) for field-overridden columns
