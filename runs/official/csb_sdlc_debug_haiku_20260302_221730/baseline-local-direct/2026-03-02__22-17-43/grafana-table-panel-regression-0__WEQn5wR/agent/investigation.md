# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary
The v38 dashboard schema migration fails to process table panels when `fieldConfig.defaults.custom` is not explicitly defined in the dashboard JSON. This causes field override configuration to be silently skipped during both backend and frontend migration, resulting in loss of column formatting (cell display modes, widths, alignment).

## Root Cause

### Primary Issue: Broken Conditional Logic in V38 Migration

**Backend v38 Migration** (`/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go`, lines 115-137):

```go
defaults, ok := fieldConfig["defaults"].(map[string]interface{})
if !ok {
    continue
}

custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue  // <-- CRITICAL: Entire panel migration skipped if custom doesn't exist
}

// Migrate displayMode to cellOptions
if displayMode, exists := custom["displayMode"]; exists {
    if displayModeStr, ok := displayMode.(string); ok {
        custom["cellOptions"] = migrateTableDisplayModeToCellOptions(displayModeStr)
    }
    delete(custom, "displayMode")
}

// Update any overrides referencing the cell display mode
migrateOverrides(fieldConfig)  // <-- Never reached if custom doesn't exist
```

The type assertion on line 120 (`custom, ok := defaults["custom"].(map[string]interface{})`) assumes `fieldConfig.defaults.custom` already exists. When it doesn't:
- The assertion fails (ok == false)
- The migration skips to the next panel via `continue` (line 122)
- **Field overrides are never migrated** because `migrateOverrides(fieldConfig)` (line 135) is never called

**Frontend v38 Migration** (`/workspace/public/app/features/dashboard/state/DashboardMigrator.ts`, lines 644-674):

```typescript
if (oldVersion < 38 && finalTargetVersion >= 38) {
  panelUpgrades.push((panel: PanelModel) => {
    if (panel.type === 'table' && panel.fieldConfig !== undefined) {
      const displayMode = panel.fieldConfig.defaults?.custom?.displayMode;  // <-- Optional chaining

      // Update field configuration
      if (displayMode !== undefined) {  // <-- Skips if custom doesn't exist
        panel.fieldConfig.defaults.custom.cellOptions = migrateTableDisplayModeToCellOptions(displayMode);
        delete panel.fieldConfig.defaults.custom.displayMode;
      }

      // Update any overrides referencing the cell display mode
      if (panel.fieldConfig?.overrides) {
        for (const override of panel.fieldConfig.overrides) {
          for (let j = 0; j < (override.properties?.length || 0); j++) {
            if (override.properties[j].id === 'custom.displayMode') {
              // Override migration happens regardless of defaults.custom
              override.properties[j].id = 'custom.cellOptions';
              override.properties[j].value = migrateTableDisplayModeToCellOptions(overrideDisplayMode);
            }
          }
        }
      }
    }
    return panel;
  });
}
```

The optional chaining `?.` on line 647 causes the entire defaults migration to be skipped if `custom` doesn't exist. While overrides migration (lines 659-668) runs independently, it creates an inconsistency: overrides reference `custom.cellOptions` but the defaults object may not have `custom` properly initialized.

### Secondary Issue: Inconsistent Default Structure

**PanelModel Default Definition** (`/workspace/public/app/features/dashboard/state/PanelModel.ts`, lines 130-133):

```typescript
const defaults: any = {
  ...
  fieldConfig: {
    defaults: {},      // <-- No 'custom' object initialized
    overrides: [],
  },
  ...
};
```

The default `fieldConfig` structure only initializes `defaults: {}` and `overrides: []`. There is **no `custom` object**. This means:

1. Dashboards created before explicit `custom` properties were added won't have `fieldConfig.defaults.custom`
2. Dashboards imported from external sources or created with minimal configuration structures won't have it
3. The v38 migration assumes this structure will always exist, creating a silent failure

## Evidence

### Test Coverage Gap
**File**: `/workspace/apps/dashboard/pkg/migration/schemaversion/v38_test.go`

All test cases (lines 9-445) have explicit `fieldConfig.defaults.custom` defined. **Missing test case**: Dashboard with `fieldConfig` but without `fieldConfig.defaults.custom`.

All test inputs follow this pattern (lines 22-28):
```go
"fieldConfig": map[string]interface{}{
    "defaults": map[string]interface{}{
        "custom": map[string]interface{}{  // <-- Always present
            "displayMode": "basic",
        },
    },
    "overrides": []interface{}{},
},
```

**No test covers**:
```go
"fieldConfig": map[string]interface{}{
    "defaults": map[string]interface{}{
        // No 'custom' property
    },
    "overrides": []interface{}{
        map[string]interface{}{
            "properties": []interface{}{
                map[string]interface{}{
                    "id":    "custom.displayMode",
                    "value": "gradient-gauge",
                },
            },
        },
    },
},
```

### Version Progression
**File**: `/workspace/apps/dashboard/pkg/migration/schemaversion/v30.go` (lines 130-145)

Earlier migrations (v30) handle missing `custom` by checking existence before access:

```go
if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
    if mappings, ok := defaults["mappings"].([]interface{}); ok {
        // Process mappings
    }
}
```

V30 doesn't assume `custom` exists and processes only fields that are present. **V38 breaks this pattern** by requiring `custom` to exist.

## Affected Components

### Backend Migration Pipeline
- **Primary**: `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go` (processPanelsV38, migrateOverrides, migrateTableDisplayModeToCellOptions)
- **Impact**: Dashboard imports/saves via backend API, schema version advancement
- **Scope**: All table panels in dashboards where `fieldConfig.defaults.custom` is not pre-initialized

### Frontend Migration Pipeline
- **Primary**: `/workspace/public/app/features/dashboard/state/DashboardMigrator.ts` (v38 conditional block, lines 644-674)
- **Impact**: Dashboard viewing, panel rendering
- **Scope**: Same as backend, compounded by inconsistency

### Field Configuration Structure
- **Primary**: `/workspace/public/app/features/dashboard/state/PanelModel.ts` (default fieldConfig definition)
- **Related**: `/workspace/public/app/plugins/panel/table/migrations.ts` (table panel migrations)
- **Impact**: How field overrides are stored and serialized

## Affected Schema Version
- **Version**: 38 (Table cell display configuration migration: displayMode → cellOptions)
- **Dashboard Versions**: Affects dashboards at schema version 37 (or earlier) that lack explicit `fieldConfig.defaults.custom`
- **Introduced**: Schema migration from v10.3 to v10.4
- **Regression Type**: Silent data loss (field overrides not migrated)

## Conditional Logic Failure

### Failure Condition
A dashboard triggers the regression when:

1. **Panel type is 'table'** - Only table panels are processed by v38
2. **Has fieldConfig** - Panel has field configuration structure
3. **Has fieldConfig.defaults** - Defaults object exists
4. **Missing fieldConfig.defaults.custom** - No explicit custom object (common in older/minimal dashboards)
5. **Has fieldConfig.overrides with custom.displayMode** - Field-specific displayMode overrides exist

### Why Dashboards With Explicit custom Are Unaffected

When `fieldConfig.defaults.custom` IS explicitly defined:
- Type assertion succeeds: `custom, ok := defaults["custom"].(map[string]interface{})` returns ok=true
- Migration enters the processing block
- Both defaults and overrides are correctly migrated
- displayMode is converted to cellOptions and removed

## Migration Chain

```
Dashboard Schema v37 → V38 Migration → Schema v38
    ↓                      ↓
Backend Processes    Type assertion fails
(if custom missing)   custom doesn't exist
    ↓                  continue to next panel
Database saved    Overrides not migrated
    ↓
Frontend loads       Optional chaining skips
from database        defaults processing
    ↓
Renders with    Overrides may reference
missing formatting  non-existent custom.cellOptions
```

## Recommendation

### Fix Strategy
The v38 migration must initialize `fieldConfig.defaults.custom` if it doesn't exist before processing:

1. **Backend (v38.go)**: Initialize empty custom object if missing
   ```go
   custom, ok := defaults["custom"].(map[string]interface{})
   if !ok {
       custom = make(map[string]interface{})
       defaults["custom"] = custom
   }
   // Now proceed with migration
   ```

2. **Frontend (DashboardMigrator.ts)**: Ensure custom object exists before assignment
   ```typescript
   if (!panel.fieldConfig.defaults.custom) {
       panel.fieldConfig.defaults.custom = {};
   }
   // Now safe to migrate
   ```

3. **Test Coverage**: Add test case for dashboards without explicit `fieldConfig.defaults.custom`

4. **Consistency**: Review other migrations (v30, v35, v42) to ensure they follow the same pattern of initializing missing structures rather than skipping them

### Prevention
- All future schema migrations should validate/initialize required object structures before processing
- Test coverage should include both "structure exists" and "structure missing" scenarios
- Consider adding schema validation in the migration framework to catch these patterns early
