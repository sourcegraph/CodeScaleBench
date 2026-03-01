# Investigation Report: Dashboard Migration v38 Table Panel Regression

## Summary

The v38 schema migration regression is caused by a premature early-return condition in the `processPanelsV38` function that skips override migration when a table panel's `fieldConfig.defaults.custom` field is not explicitly set. This causes field overrides with `custom.displayMode` to be silently dropped during dashboard import, affecting all dashboards from pre-v10.4 versions that have field overrides without explicit defaults configuration.

## Root Cause

**File:** `/workspace/apps/dashboard/pkg/migration/schemaversion/v38.go`
**Function:** `processPanelsV38` (lines 90-137)
**Mechanism:** Lines 120-123 perform an early return that prevents execution of the override migration logic

```go
custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue  // Early return if custom is not a map
}
```

This early return occurs **before** the `migrateOverrides(fieldConfig)` call at line 135, which is the function responsible for migrating field override properties from `custom.displayMode` to `custom.cellOptions`.

### The Problematic Control Flow

```
processPanelsV38():
  ├─ Line 110-113: Validate fieldConfig exists
  ├─ Line 115-118: Validate defaults exists
  ├─ Line 120-123: Check for defaults.custom
  │   └─ ❌ RETURN IF NOT FOUND (breaks control flow)
  ├─ Line 126-132: Migrate defaults.custom.displayMode
  └─ Line 135: migrateOverrides(fieldConfig)  ← Never reached if custom is missing
```

When `defaults["custom"]` doesn't exist or is not a map, the function continues to the next panel without calling `migrateOverrides`, which leaves field override properties in the legacy `custom.displayMode` format instead of migrating them to the new `custom.cellOptions` structure.

## Evidence

### 1. Early Return Condition (v38.go:120-123)
The problematic code is clearly visible:
```go
custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue  // This prevents migrateOverrides from being called
}
```

### 2. Override Migration Function Placement (v38.go:135)
The `migrateOverrides` call is placed **after** the early return check:
```go
// Migrate displayMode to cellOptions
if displayMode, exists := custom["displayMode"]; exists {
    // ... process defaults.custom.displayMode
}

// Update any overrides referencing the cell display mode
migrateOverrides(fieldConfig)  // Only called if custom exists
```

### 3. Override Migration Function Signature (v38.go:140)
The `migrateOverrides` function can operate independently from defaults.custom:
```go
func migrateOverrides(fieldConfig map[string]interface{}) {
    overrides, ok := fieldConfig["overrides"].([]interface{})
    // ... processes overrides array directly from fieldConfig
}
```
This function receives the entire `fieldConfig` object and doesn't require `defaults.custom` to exist. However, it is never invoked when `defaults.custom` is missing.

### 4. Test Coverage Gap
All test cases in `v38_test.go` include explicit `custom` fields in defaults (lines 23-29, 36-42, etc.), masking the regression for dashboards without explicit custom configuration.

## Affected Components

1. **Package:** `github.com/grafana/grafana/apps/dashboard/pkg/migration/schemaversion`
2. **Module:** Dashboard migration pipeline (v0alpha1/v1beta1 to v1beta1)
3. **Scope:** Table panels in dashboards with schema versions < 38 being migrated to v38
4. **Impact:** Field overrides configuration for table cell display modes

### Migration Chain

```
Dashboard Import → Migration Pipeline (v13→v42) → V38 (Regression Point)
                 ↓
            processPanelsV38()
                 ↓
            [Check for defaults.custom]
                 ↓
            ❌ Early return if missing
                 ↓
            ✗ migrateOverrides() skipped
                 ↓
            Field overrides remain unmigrated (legacy format)
```

## Why Dashboards with Explicit `defaults.custom` Are Unaffected

Dashboards that explicitly define `fieldConfig.defaults.custom` satisfy the type assertion at line 120:
```go
custom, ok := defaults["custom"].(map[string]interface{})
if !ok {
    continue
}
// custom exists, so execution continues...
migrateOverrides(fieldConfig)  // ✓ This gets called
```

These dashboards successfully reach the `migrateOverrides` call, which properly converts field override properties from `custom.displayMode` to `custom.cellOptions`.

## Schema Version Trigger

- **Affected Version:** v38
- **Affects Dashboards:** Imported from any version < 38
- **Version Released:** As part of Grafana v10.4+ (schema versions 13-42 support v0alpha1/v1beta1 dashboards)
- **Minimum Supported Version:** v13 (per migration/README.md line 82)
- **Latest Version:** v42

The migration executes when:
1. Dashboard schemaVersion is < 38
2. Dashboard is being migrated through the schema version pipeline
3. Dashboard contains table panels with field overrides

## Recommendation

**Fix Strategy:** Restructure the conditional logic to ensure `migrateOverrides` is called for all table panels regardless of whether `defaults.custom` exists.

**Implementation Approach:**
1. Move the `migrateOverrides(fieldConfig)` call outside of the `defaults.custom` existence check
2. Ensure it executes whenever fieldConfig and defaults exist, independent of custom field presence
3. Process `defaults.custom.displayMode` separately (only when custom exists)
4. Process field overrides independently (always when fieldConfig.overrides exists)

**Test Coverage Addition:**
Add test cases covering:
- Table panels with field overrides but no explicit `defaults.custom`
- Table panels with overrides referencing `custom.displayMode` where defaults.custom doesn't exist
- Nested panels with the same missing custom field scenario
