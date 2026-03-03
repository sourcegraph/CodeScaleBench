# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary

The V38 dashboard migration contains a critical logic flaw where table panels without explicit `fieldConfig.defaults.custom` objects are entirely skipped, preventing field override migrations. This causes dashboards saved without explicit custom configuration to lose their field override formatting (column widths, text alignment, cell display modes) during upgrade from v10.3 to v10.4.

## Root Cause

**File:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go`
**Function:** `processPanelsV38()` (lines 90-137)
**Lines:** 120-123

The migration function contains nested conditional checks that cause premature exit:

```go
custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue  // BUG: Skips entire panel including overrides migration
}

// ... process displayMode ...

// This line is only reached if custom exists
migrateOverrides(fieldConfig)  // Line 135
```

**The Bug:** When `fieldConfig.defaults.custom` doesn't exist (a valid state for many dashboards), the function executes `continue` at line 122, immediately jumping to the next panel. This skips the critical `migrateOverrides(fieldConfig)` call at line 135 that should process field overrides regardless of whether defaults.custom exists.

## Evidence

### Backend Implementation (Broken)
**File:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go:115-135`

```go
defaults, ok := fieldConfig["defaults"].(map[string]interface{})
if !ok {
    continue
}

custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue  // <-- PROBLEM: Skips panel entirely
}

// Only reached if custom exists
if displayMode, exists := custom["displayMode"]; exists {
    custom["cellOptions"] = migrateTableDisplayModeToCellOptions(displayModeStr)
    delete(custom, "displayMode")
}

// Only reached if custom exists - overrides are skipped if custom is nil/missing
migrateOverrides(fieldConfig)
```

### Frontend Implementation (Correct)
**File:** `/workspace/public/app/features/dashboard/state/DashboardMigrator.ts:644-673`

The frontend implementation correctly handles this scenario by processing overrides independently:

```typescript
if (oldVersion < 38 && finalTargetVersion >= 38) {
  panelUpgrades.push((panel: PanelModel) => {
    if (panel.type === 'table' && panel.fieldConfig !== undefined) {
      const displayMode = panel.fieldConfig.defaults?.custom?.displayMode;

      // Only process defaults if displayMode exists
      if (displayMode !== undefined) {
        panel.fieldConfig.defaults.custom.cellOptions = migrateTableDisplayModeToCellOptions(displayMode);
        delete panel.fieldConfig.defaults.custom.displayMode;
      }

      // ALWAYS process overrides, regardless of whether defaults.custom exists
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
    }
    return panel;
  });
}
```

**Key Difference:** The frontend implementation checks `panel.fieldConfig?.overrides` directly without requiring `defaults.custom` to exist first. It processes overrides in all cases.

## Affected Components

1. **Backend Migration:** `apps/dashboard/pkg/migration/schemaversion/v38.go`
   - `V38()` function (line 75)
   - `processPanelsV38()` function (line 90)
   - `migrateOverrides()` function (line 140)

2. **Frontend Migration:** `public/app/features/dashboard/state/DashboardMigrator.ts`
   - Migration handler at lines 644-673 (works correctly)

3. **Tests:** `apps/dashboard/pkg/migration/schemaversion/v38_test.go`
   - All test cases include explicit `fieldConfig.defaults.custom` objects
   - Missing test coverage for panels without explicit custom config

4. **Schema Registration:** `apps/dashboard/pkg/migration/schemaversion/migrations.go:74`
   - V38 is registered in the migration chain

## Affected Scenario

**Affected Dashboards:** Those with table panels where:
- `fieldConfig.defaults.custom` was not explicitly defined in the saved JSON
- `fieldConfig.overrides` contains entries with `id: "custom.displayMode"`

**Example (Broken by Backend Migration):**
```json
{
  "type": "table",
  "fieldConfig": {
    "defaults": {
      // NO "custom" key here
    },
    "overrides": [
      {
        "matcher": { "id": "byName", "options": "ColumnName" },
        "properties": [
          {
            "id": "custom.displayMode",
            "value": "gradient-gauge"
          }
        ]
      }
    ]
  }
}
```

During backend migration (v37→v38):
- Panel is skipped due to missing `defaults.custom`
- Override with `custom.displayMode` is **never processed**
- Field override is silently lost
- Table renders without column formatting

**Why Dashboards with Explicit custom Config Work:**
- They pass the check at line 120-122
- `migrateOverrides()` is called at line 135
- Overrides are properly migrated to use `custom.cellOptions`

## Why This Matters

The regression creates a **silent data loss scenario**:
- Dashboards migrate without errors
- Field override configuration is dropped
- Users see tables with missing column formatting
- The issue only appears at runtime when panels fail to render correctly

The backend backend migration is more strict than the frontend, creating a divergence:
- Frontend handles missing `defaults.custom` gracefully
- Backend completely skips the panel
- Backend migration was probably developed before frontend patterns were fully established

## Recommendation

**Fix Strategy:**

The backend migration should restructure the control flow to:
1. Always check for and process field overrides (independent of defaults.custom)
2. Only process defaults.custom if it exists
3. Call `migrateOverrides(fieldConfig)` unconditionally for all table panels

**Pseudo-fix pattern:**
```go
processPanelsV38(panels []interface{}) {
  for _, panel := range panels {
    // ... type checks ...

    if p["type"] != "table" {
      continue
    }

    fieldConfig, ok := p["fieldConfig"].(map[string]interface{})
    if !ok {
      continue
    }

    // Process defaults.custom IF it exists
    if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
      if custom, ok := defaults["custom"].(map[string]interface{}); ok {
        if displayMode, exists := custom["displayMode"]; exists {
          // ... migrate ...
        }
      }
    }

    // ALWAYS process overrides, regardless of defaults state
    migrateOverrides(fieldConfig)
  }
}
```

## Verification

**Test Coverage Gap:**
- `v38_test.go` includes 10+ test cases but ALL have explicit `fieldConfig.defaults.custom`
- Missing test case: table panel with overrides but no defaults.custom object
- This test case would have caught the regression

**Issue Reproduction:**
1. Create v37 dashboard with table panel
2. Add field override with `custom.displayMode` (no explicit defaults.custom)
3. Migrate to v38 via backend
4. Override is lost (backend bug)
5. Frontend migration handles it correctly (divergence)
