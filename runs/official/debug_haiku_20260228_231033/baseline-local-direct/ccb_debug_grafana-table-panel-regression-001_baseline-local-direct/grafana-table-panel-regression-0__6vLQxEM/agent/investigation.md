# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary

The V38 schema migration in the backend fails to migrate field override configurations for table panels when `fieldConfig.defaults.custom` is not explicitly present in the dashboard JSON. The backend migration skips the entire panel when `defaults.custom` is missing, preventing override migrations from executing. This creates a critical discrepancy with the frontend migration, which processes overrides independently.

## Root Cause

**File:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go`

**Functions:** `processPanelsV38()` (lines 90-137) and `migrateOverrides()` (lines 140-180)

**Mechanism:**

The migration has a critical control flow issue:

```go
// Line 120-123: Conditional check that exits early
custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
	continue  // <-- EXITS EARLY if defaults.custom doesn't exist
}

// Lines 126-132: Process defaults.custom displayMode
if displayMode, exists := custom["displayMode"]; exists {
	if displayModeStr, ok := displayMode.(string); ok {
		custom["cellOptions"] = migrateTableDisplayModeToCellOptions(displayModeStr)
	}
	delete(custom, "displayMode")
}

// Line 135: ONLY called after successful defaults.custom retrieval
migrateOverrides(fieldConfig)  // <-- NEVER EXECUTES if line 122-123 continues
```

**The Bug:**
When a table panel's `fieldConfig.defaults.custom` is `nil`, `null`, or missing:
1. Line 121-122: Type assertion fails with `ok = false`
2. Line 122: `continue` statement skips the entire panel
3. Line 135: `migrateOverrides()` is never called
4. **Result:** Field overrides containing `custom.displayMode` are left unmigrated

## Evidence

### Backend Implementation (v38.go)
- **Location:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go:120-137`
- **Issue:** The `migrateOverrides()` function call on line 135 is **nested inside** the successful retrieval of `defaults["custom"]` (line 120-123)
- This means overrides are only migrated when defaults.custom explicitly exists

### Frontend Implementation (DashboardMigrator.ts)
- **Location:** `/workspace/public/app/features/dashboard/state/DashboardMigrator.ts:644-674`
- **Contrast:** Frontend migration processes overrides **independently** of defaults.custom
  - Lines 647-656: Handle `defaults.custom.displayMode` IF IT EXISTS
  - Lines 658-669: Process overrides **regardless of whether defaults.custom exists**
  - The override migration is NOT nested inside the defaults.custom check

```typescript
// Frontend code structure (lines 659-669):
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

### Missing Test Coverage
- **Location:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38_test.go`
- **Issue:** Test file does NOT include a test case for table panels with:
  - Field overrides containing `custom.displayMode`
  - BUT missing/null `fieldConfig.defaults.custom`
- All test cases that have overrides (lines 116-153, 160-207) also have `defaults.custom` explicitly defined

## Affected Components

1. **Backend Migration Service:**
   - `apps/dashboard/pkg/migration/schemaversion/v38.go`
   - Function: `processPanelsV38()`
   - Function: `migrateOverrides()`

2. **Frontend Migration Service:**
   - `public/app/features/dashboard/state/DashboardMigrator.ts`
   - Lines 644-674 (V38 migration)

3. **Test Coverage Gaps:**
   - `apps/dashboard/pkg/migration/schemaversion/v38_test.go`
   - Missing test case for the regression scenario

## Why Dashboards with Explicit `defaults.custom` Are Unaffected

When a dashboard has explicit `fieldConfig.defaults.custom`:
1. Line 120-121: Type assertion succeeds, `custom` is a valid map
2. Line 122: Condition is `ok == true`, so `continue` is NOT executed
3. Line 126-132: Defaults displayMode is processed
4. Line 135: `migrateOverrides()` IS called
5. **Result:** Both defaults and overrides are migrated successfully

## Dashboard Schema Version and Regression Timeline

- **Affected Schema Version:** V38 (introduced in Grafana 10.4)
- **Triggers:** Dashboards upgraded from v37 or earlier where:
  - Table panels have field overrides with `custom.displayMode`
  - Table panels do NOT have `fieldConfig.defaults.custom` explicitly set
- **Manifestation:** During dashboard import, field override configurations are silently dropped, causing:
  - Loss of column width settings
  - Loss of text alignment overrides
  - Loss of cell display mode overrides
  - Columns render without formatting

## Recommendation

The backend migration at `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go` should:

1. **Restructure conditional logic:** Move `migrateOverrides()` call OUTSIDE the `defaults.custom` check
2. **Ensure overrides are always processed:** Call `migrateOverrides(fieldConfig)` for all table panels with fieldConfig, regardless of whether defaults.custom exists
3. **Add test coverage:** Create a regression test with:
   - A table panel without explicit `defaults.custom`
   - Field overrides containing `custom.displayMode` properties
   - Verify that overrides are properly migrated to `custom.cellOptions`

**Suggested Fix Pattern:**
```go
// Process table panel fieldConfig
fieldConfig, ok := p["fieldConfig"].(map[string]interface{})
if !ok {
	continue
}

defaults, ok := fieldConfig["defaults"].(map[string]interface{})
if ok {
	custom, ok := defaults["custom"].(map[string]interface{})
	if ok {
		// Migrate displayMode to cellOptions in defaults
		if displayMode, exists := custom["displayMode"]; exists {
			if displayModeStr, ok := displayMode.(string); ok {
				custom["cellOptions"] = migrateTableDisplayModeToCellOptions(displayModeStr)
			}
			delete(custom, "displayMode")
		}
	}
}

// MOVE THIS OUTSIDE - process overrides regardless of defaults.custom
migrateOverrides(fieldConfig)  // <-- Now called for all panels with fieldConfig
```

This approach mirrors the frontend migration's logic and ensures complete consistency across both migration pipelines.
