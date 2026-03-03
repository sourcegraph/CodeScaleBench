# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary
The v38 dashboard schema migration has a regression where table panel field overrides are conditionally processed based on the presence of `fieldConfig.defaults.custom`, even though field overrides can exist independently. When a table panel has field overrides with `custom.displayMode` but no `fieldConfig.defaults.custom`, the frontend migration handler skips critical initialization logic, causing the table panel's migration handler to execute on an improperly structured fieldConfig.

## Root Cause
**File:** `public/app/features/dashboard/state/DashboardMigrator.ts:644-674`
**Function:** Schema version 38 migration handler
**Specific Issue:** Conditional logic gates the entire table panel migration on the presence of `fieldConfig.defaults.custom`

The problematic code structure:
```typescript
// Line 644-674: V38 Migration Handler
if (oldVersion < 38 && finalTargetVersion >= 38) {
  panelUpgrades.push((panel: PanelModel) => {
    if (panel.type === 'table' && panel.fieldConfig !== undefined) {
      const displayMode = panel.fieldConfig.defaults?.custom?.displayMode;  // Line 647

      // Update field configuration
      if (displayMode !== undefined) {  // Line 650: CONDITIONAL BLOCK
        // Migrate any options for the panel
        panel.fieldConfig.defaults.custom.cellOptions = migrateTableDisplayModeToCellOptions(displayMode);
        delete panel.fieldConfig.defaults.custom.displayMode;
      }

      // Update any overrides referencing the cell display mode
      if (panel.fieldConfig?.overrides) {  // Line 659: INDEPENDENT BLOCK
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

## Exact Conditional Logic Failure

**The bug manifests when:**
1. A table panel has `fieldConfig.overrides` with `custom.displayMode` properties
2. The same panel does NOT have `fieldConfig.defaults.custom` defined
3. The optional chaining `panel.fieldConfig.defaults?.custom?.displayMode` evaluates to `undefined`
4. This causes the defaults migration block (lines 650-656) to be SKIPPED
5. However, the overrides ARE processed (lines 659-669), converting `custom.displayMode` → `custom.cellOptions`

**The cascading failure:**
After the v38 migration completes, the table panel's migration handler (`tableMigrationHandler` in `public/app/plugins/panel/table/migrations.ts`) is invoked. This handler calls `migrateTextWrapToFieldLevel()` which assumes `panel.fieldConfig.defaults` exists and is properly initialized. When the defaults structure is incomplete or missing the `custom` object:

```typescript
// Line 329 of public/app/plugins/panel/table/migrations.ts
panel.fieldConfig.defaults.custom = panel.fieldConfig.defaults.custom ?? {};
```

This creates or initializes `defaults.custom` only AFTER the overrides have already been processed. The missing initialization can cause subsequent field configuration operations to fail or be skipped.

## Why Dashboards WITH Explicit `defaults.custom` Are Unaffected

Dashboards that explicitly define `fieldConfig.defaults.custom` in the saved JSON work correctly because:

1. When `defaults.custom` is explicitly set, the optional chaining chain completes successfully
2. Line 647 retrieves the `displayMode` value (not undefined)
3. Line 650 condition is TRUE, so the defaults migration block executes
4. This ensures proper initialization of the `custom` object structure
5. When the table panel migration handler runs, `defaults.custom` is already properly initialized

## Schema Version and Trigger Point

**Affected Schema Version:** 38 (and all versions >= 38)
**Dashboard Migration Timeline:**
- v10.3 and earlier: Table panels could have incomplete fieldConfig structures
- v10.4 (when schema v38 was introduced): The v38 migration assumes `defaults.custom` always exists when processing displayMode
- Regression: Dashboards migrating from v10.3 to v10.4 with certain table panel configurations lose field overrides

## Migration Chain Analysis

### Frontend Migration Path (DashboardMigrator.ts)
1. **Line 647:** Extract displayMode with optional chaining (returns undefined if defaults.custom doesn't exist)
2. **Line 650-656:** Only migrate defaults.custom if displayMode is defined
3. **Line 659-669:** Process overrides independently (migrations happen but structure may be incomplete)
4. Table panel plugin's `tableMigrationHandler()` is called afterward
5. `migrateTextWrapToFieldLevel()` assumes proper fieldConfig initialization

### Backend Migration Path (apps/dashboard/pkg/migration/schemaversion/v38.go)
1. **Line 116-127:** Process `defaults.custom` only if it exists
2. **Line 129-131:** Call `migrateOverrides()` regardless of defaults.custom presence
3. **migrateOverrides() (lines 135-176):** Correctly processes all overrides
4. This backend migration is more defensive and handles both cases

**Key Difference:** The backend migration in `v38.go` calls `migrateOverrides()` unconditionally, while the frontend migration's logic flow doesn't properly initialize `defaults.custom` before the table panel handler executes.

## Files and Functions Involved

### Primary Regression Location
- **File:** `public/app/features/dashboard/state/DashboardMigrator.ts`
- **Function:** v38 migration handler (anonymous, lines 644-674)
- **Issue:** Conditional field override processing based on defaults.custom presence

### Secondary Impact Points
- **File:** `public/app/plugins/panel/table/migrations.ts`
- **Function:** `migrateTextWrapToFieldLevel()` (lines 306-334)
- **Issue:** Assumes `fieldConfig.defaults` structure is fully initialized

- **File:** `apps/dashboard/pkg/migration/schemaversion/v38.go`
- **Function:** `processPanelsV38()` (lines 89-133)
- **Status:** Correctly handles both cases (has proper defensive checks)

### Supporting Files
- **File:** `apps/dashboard/pkg/migration/frontend_defaults.go`
- **Function:** `trackOriginalFieldConfigCustom()` (lines 1138-1169)
- **Status:** Correctly tracks panels that had fieldConfig.defaults.custom for preservation during cleanup

## Evidence: Code References

1. **V38 Migration Handler Decision Point:**
   - `DashboardMigrator.ts:647` - Extracts displayMode with optional chaining
   - `DashboardMigrator.ts:650` - Conditional block gated on displayMode !== undefined
   - `DashboardMigrator.ts:659` - Independent override processing

2. **Backend v38 (Correct Implementation):**
   - `v38.go:115-127` - Processes defaults.custom if exists
   - `v38.go:129-131` - Calls migrateOverrides unconditionally
   - `v38.go:135-176` - migrateOverrides function properly handles all cases

3. **Table Panel Migration Handler Issues:**
   - `migrations.ts:306-310` - Early return based on wrapText check
   - `migrations.ts:314` - Assumes fieldConfig.overrides exists
   - `migrations.ts:329` - Creates/initializes defaults.custom

## Affected Components

- **Dashboard Migration Pipeline:** Core migration orchestration
- **Table Panel Plugin:** Field configuration migration handlers
- **Schema Version 38:** displayMode to cellOptions conversion
- **Field Configuration System:** defaults and overrides handling
- **Frontend-Backend Sync:** Inconsistent handling between frontend (DashboardMigrator) and backend (v38.go)

## Recommendation

**The fix requires ensuring that `fieldConfig.defaults.custom` is always initialized before any migration operation that depends on its existence, regardless of whether a displayMode value exists.**

Specifically:
1. In `DashboardMigrator.ts` line 644-674, restructure the v38 migration to ensure `fieldConfig.defaults.custom` is initialized even when no displayMode exists in defaults
2. Move the initialization logic outside the conditional block or add an explicit pre-initialization step
3. Ensure all field override migrations have access to a properly structured defaults object
4. Consider adding a validation step to match the defensive approach used in the backend `v38.go` migration

This regression demonstrates a critical difference in migration robustness between the frontend (DashboardMigrator.ts) and backend (v38.go) implementations, with the backend implementation being more defensive.
