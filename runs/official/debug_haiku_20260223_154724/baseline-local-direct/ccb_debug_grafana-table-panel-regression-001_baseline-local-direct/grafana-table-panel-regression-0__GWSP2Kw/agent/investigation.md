# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary
The table panel's field override configuration is silently dropped during dashboard import due to missing defensive null checks in the table panel migration functions. When `fieldConfig.defaults.custom` is not explicitly set in the saved dashboard JSON, the migration code attempts to access properties on potentially undefined objects, causing failures that are not properly handled.

## Root Cause

The regression is caused by **three table panel migration functions** that directly access `panel.fieldConfig` and its nested properties without checking if they exist:

1. **`migrateTextWrapToFieldLevel()`** (migrations.ts:306-334)
   - Line 314: `panel.fieldConfig.overrides = panel.fieldConfig.overrides.map(...)`
   - Assumes `panel.fieldConfig` is initialized with an `overrides` array
   - Missing check: Does not verify `panel.fieldConfig` is not null/undefined before access

2. **`migrateHiddenFields()`** (migrations.ts:336-350)
   - Line 337: `panel.fieldConfig.overrides = panel.fieldConfig.overrides.map(...)`
   - Identical issue: Direct access without null/undefined checks
   - Can fail with "Cannot read property 'overrides' of undefined"

3. **`migrateFooterV2()`** (migrations.ts:360-413)
   - Line 369-370: `panel.fieldConfig.defaults.custom = { ...panel.fieldConfig.defaults.custom, ... }`
   - Line 383, 397: `panel.fieldConfig.overrides.push(...)`
   - Missing checks before accessing `defaults.custom` and `overrides`

## Evidence

### File: `/workspace/public/app/plugins/panel/table/migrations.ts`

**Problem Code - `migrateTextWrapToFieldLevel` (lines 306-334):**
```typescript
export const migrateTextWrapToFieldLevel = (panel: PanelModel<Partial<Options>>) => {
  if (panel.fieldConfig?.defaults.custom?.wrapText !== undefined) {
    // already migrated
    return;
  }

  const legacyDefaultWrapText: boolean | undefined = panel.fieldConfig?.defaults.custom?.cellOptions?.wrapText;

  // BUG: No check for panel.fieldConfig existence before accessing .overrides
  panel.fieldConfig.overrides = panel.fieldConfig.overrides.map((override) => {
    // ...
  });

  panel.fieldConfig.defaults.custom = panel.fieldConfig.defaults.custom ?? {};
  // ...
};
```

**Problem Code - `migrateHiddenFields` (lines 336-350):**
```typescript
export const migrateHiddenFields = (panel: PanelModel<Partial<Options>>) => {
  // BUG: Direct access without null/undefined check
  panel.fieldConfig.overrides = panel.fieldConfig.overrides.map((override) => {
    // ...
  });
  return panel;
};
```

**Problem Code - `migrateFooterV2` (lines 360-413):**
```typescript
export const migrateFooterV2 = (panel: PanelModel<Options>) => {
  if (panel.options && 'footer' in panel.options) {
    const oldFooter = panel.options.footer as LegacyTableFooterOptions;

    if (oldFooter.show) {
      // BUG: Assumes fieldConfig.defaults.custom exists
      panel.fieldConfig.defaults.custom = {
        ...panel.fieldConfig.defaults.custom,
        footer: { reducers: reducers },
      };

      // BUG: Assumes fieldConfig.overrides exists and is an array
      panel.fieldConfig.overrides.push({
        // ...
      });
    }
  }
};
```

### File: `/workspace/public/app/features/dashboard/state/DashboardMigrator.ts`

**Schema Version 38 Migration (lines 644-674):**
```typescript
if (oldVersion < 38 && finalTargetVersion >= 38) {
  panelUpgrades.push((panel: PanelModel) => {
    if (panel.type === 'table' && panel.fieldConfig !== undefined) {
      const displayMode = panel.fieldConfig.defaults?.custom?.displayMode;

      // Only processes if displayMode exists
      if (displayMode !== undefined) {
        // Migration logic
      }
    }
    return panel;
  });
}
```

**Issue:** The condition checks `panel.fieldConfig !== undefined` but doesn't validate the structure of `fieldConfig.defaults.custom`. Dashboards without explicit custom config skip this migration entirely.

## Affected Components

1. **Panel Table Plugin:**
   - Package: `/public/app/plugins/panel/table/`
   - Files: `migrations.ts`, `module.tsx`
   - Functions: `tableMigrationHandler`, `migrateTextWrapToFieldLevel`, `migrateHiddenFields`, `migrateFooterV2`

2. **Dashboard State Management:**
   - Package: `/public/app/features/dashboard/state/`
   - File: `DashboardMigrator.ts` (schema version 38)
   - File: `PanelModel.ts` (plugin lifecycle - `pluginLoaded` method)

3. **Dashboard Model:**
   - File: `DashboardModel.ts`
   - Instantiates panels and triggers schema migrations

## Why Dashboards with Explicit `defaults.custom` Are Unaffected

When a dashboard has explicit `fieldConfig.defaults.custom` configuration in the saved JSON:

1. The PanelModel is created with the full structure: `fieldConfig: { defaults: { custom: { ... } }, overrides: [...] }`
2. All three migration functions can safely access `panel.fieldConfig.overrides` because the property exists
3. Optional chaining checks like `panel.fieldConfig?.defaults.custom?.displayMode` succeed
4. The migrations complete successfully and field overrides are preserved

## Why Dashboards Without Explicit `defaults.custom` Fail

When a dashboard has `fieldConfig` but no explicit `defaults.custom`:

1. Saved JSON: `fieldConfig: { defaults: {}, overrides: [] }` (no custom property)
2. During import, PanelModel initializes fieldConfig via `defaultsDeep`, but structure might be inconsistent
3. `tableMigrationHandler` is invoked during plugin load
4. `migrateTextWrapToFieldLevel`, `migrateHiddenFields`, and `migrateFooterV2` attempt to access `panel.fieldConfig.overrides` or `panel.fieldConfig.defaults.custom`
5. If `panel.fieldConfig` is undefined or malformed, these functions fail silently
6. Field override configuration is lost because the migration never completes
7. Table panels render without column formatting (widths, alignment, display modes)

## Conditional Logic Failure

The migration chain fails due to the following sequence:

1. **PanelModel Creation:** `defaultsDeep()` initializes fieldConfig structure
2. **Schema v38 Migration:** Skipped if `panel.fieldConfig === undefined` (line 646)
3. **Plugin Load:** `pluginLoaded()` method invokes `tableMigrationHandler`
4. **Table Migrations:** Directly access nested properties without checks:
   - Assumes `panel.fieldConfig !== null && panel.fieldConfig !== undefined`
   - Assumes `panel.fieldConfig.overrides` is always an array
   - Assumes `panel.fieldConfig.defaults.custom` exists (or safely creates it)
5. **Failure Point:** If fieldConfig is malformed, accessing `.overrides` throws an error

## Recommendation

### Fix Strategy

1. **Defensive Initialization:** Add null/undefined checks before accessing `fieldConfig` properties in all three migration functions.

2. **Specific Fixes Required:**
   - In `migrateTextWrapToFieldLevel`: Check `if (!panel.fieldConfig?.overrides)` before the map operation
   - In `migrateHiddenFields`: Check `if (!panel.fieldConfig?.overrides)` before the map operation
   - In `migrateFooterV2`: Check `if (!panel.fieldConfig?.defaults)` before accessing `defaults.custom`
   - In `migrateFooterV2`: Check `if (!panel.fieldConfig?.overrides)` before calling push

3. **Fallback Initialization:** Ensure `fieldConfig` has the expected structure before migrations run:
   ```typescript
   if (!panel.fieldConfig) {
     panel.fieldConfig = { defaults: {}, overrides: [] };
   }
   if (!panel.fieldConfig.defaults) {
     panel.fieldConfig.defaults = {};
   }
   if (!Array.isArray(panel.fieldConfig.overrides)) {
     panel.fieldConfig.overrides = [];
   }
   ```

4. **Early Return Pattern:** Implement safe return paths:
   ```typescript
   if (!panel.fieldConfig?.overrides) {
     return panel;
   }
   ```

### Root Issue
Missing defensive programming in table migration functions that assume `fieldConfig` structure without validation. This violates the principle of defensive programming where code should validate inputs before operating on them.
