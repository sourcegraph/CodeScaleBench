# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary

Table panels lose field override configuration during schema migration from v10.3 to v10.4 when the original dashboard JSON lacks explicit `fieldConfig.defaults.custom`. The regression occurs in the dashboard cleanup phase after V38 schema migration, where field overrides are preserved incorrectly due to incomplete tracking of panels with fieldConfig structures.

## Root Cause

The regression is caused by a conditional tracking mechanism in the migration pipeline that fails to distinguish between two distinct fieldConfig scenarios:

### The Bug Location

**File:** `apps/dashboard/pkg/migration/frontend_defaults.go` (lines 1150-1169)

**Function:** `trackPanelOriginalFieldConfigCustom()`

```go
func trackPanelOriginalFieldConfigCustom(panel map[string]interface{}) {
    // Mark if this panel had fieldConfig.defaults.custom in original input
    if fieldConfig, ok := panel["fieldConfig"].(map[string]interface{}); ok {
        if defaults, ok := fieldConfig["defaults"].(map[string]interface{}); ok {
            if _, hasCustom := defaults["custom"]; hasCustom {  // LINE 1155
                panel["_originallyHadFieldConfigCustom"] = true
            }
        }
    }
    // ...
}
```

**The Conditional Logic That Fails:**

At **line 1155**, the function checks **only** for `fieldConfig.defaults.custom`. It completely ignores panels that have:
- `fieldConfig.overrides` (field configuration like column widths, alignment)
- Non-empty fieldConfig structure
- But NO `fieldConfig.defaults.custom`

### Consequence in Cleanup Phase

**File:** `apps/dashboard/pkg/migration/frontend_defaults.go` (lines 606-620)

**Function:** `filterDefaultValues()`

```go
if prop == "fieldConfig" {
    // Check if we need to preserve the custom object before removing fieldConfig
    if panel["_originallyHadFieldConfigCustom"] == true {  // LINE 608
        // Preserve custom and continue (don't delete fieldConfig)
        // ...
        continue  // LINE 616
    }
    delete(panel, prop)  // LINE 620 - FIELDCONFIG DELETED
}
```

**The Problem:**

1. Panel originally has: `fieldConfig.overrides[...]` but NO `fieldConfig.defaults.custom`
2. Tracking function doesn't set marker (line 1155 condition fails)
3. During cleanup, the special preservation logic at line 608 is skipped
4. If the fieldConfig structure happens to match the default pattern, it gets deleted entirely (line 620)
5. Field overrides are lost along with the entire fieldConfig

### Why Explicit `defaults.custom` Dashboards Are Unaffected

When a dashboard explicitly includes `fieldConfig.defaults.custom` (even if empty):

1. `trackPanelOriginalFieldConfigCustom()` sets `_originallyHadFieldConfigCustom = true` (line 1156)
2. In cleanup phase, line 608 condition is true
3. Execution continues at line 616, **skipping the delete at line 620**
4. fieldConfig and all overrides are preserved

## Evidence

### Affected Components

1. **Migration Tracking (apps/dashboard/pkg/migration/frontend_defaults.go:1150-1169)**
   - Function only checks for `defaults.custom` presence
   - Ignores other fieldConfig structures that need preservation

2. **Cleanup Logic (apps/dashboard/pkg/migration/frontend_defaults.go:606-620)**
   - Special preservation only applies if marker is set
   - No fallback logic for fieldConfig with overrides but no custom

3. **V38 Schema Migration (apps/dashboard/pkg/migration/schemaversion/v38.go:75-132)**
   - Correctly processes overrides that reference `custom.displayMode`
   - But overrides are lost if fieldConfig is deleted in later cleanup phase

### Test Evidence

**File:** `apps/dashboard/pkg/migration/frontend_defaults_test.go` (lines 1135-1150)

Test case `"remove_empty_custom_when_not_originally_present"` explicitly documents the behavior:
- When fieldConfig has no `_originallyHadFieldConfigCustom` marker
- And fieldConfig matches default structure
- The entire fieldConfig is removed

The test includes a comment: `// fieldConfig should be removed entirely as it matches defaults`

This is correct for truly empty fieldConfigs, but **fails for fieldConfigs with overrides**.

## Affected Dashboard Schema Version

**Schema Version 38** (V38 migration in `apps/dashboard/pkg/migration/schemaversion/v38.go`)

The regression occurs in the migration FROM any schema version < 38 TO v38 or later, affecting:
- Grafana v10.3 → v10.4 upgrades
- Any dashboard import that triggers schema version migration through V38

## Why The Bug Manifests

Table panels specifically are affected because:

1. Table columns are configured via **field overrides** with `custom.displayMode` properties
2. Early Grafana versions allowed saving table panels with field overrides but without `fieldConfig.defaults.custom`
3. The V38 migration expects to find and migrate these overrides
4. But the overrides are discarded in the cleanup phase for panels without the `_originallyHadFieldConfigCustom` marker

Example affected structure:
```json
{
  "type": "table",
  "fieldConfig": {
    "overrides": [
      {
        "matcher": { "id": "byName", "options": "CPU" },
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

This panel has NO `fieldConfig.defaults.custom`, so the marker is not set, and the overrides are lost.

## Recommendation

**Fix Strategy:**

Modify `trackPanelOriginalFieldConfigCustom()` in `apps/dashboard/pkg/migration/frontend_defaults.go` (lines 1150-1169) to mark panels that have **either**:
1. Non-empty `fieldConfig.defaults.custom` (current behavior), OR
2. Non-empty `fieldConfig.overrides` (missing behavior)

The marker should indicate: "This panel has original fieldConfig content that must be preserved."

**Alternative Approach:**

Update the cleanup logic in `filterDefaultValues()` to check not just for the marker, but also to detect non-empty `fieldConfig.overrides` as a trigger for preservation, providing a safety net if tracking is incomplete.

**Impact:**

This fix ensures that field override configuration from pre-v10.4 dashboards is correctly migrated and preserved during the V38 schema migration, restoring table column formatting and other field-level customizations.
