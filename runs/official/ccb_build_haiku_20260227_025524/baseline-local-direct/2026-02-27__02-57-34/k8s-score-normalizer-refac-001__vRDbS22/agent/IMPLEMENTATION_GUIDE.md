# ScoreExtensions → ScoreNormalizer Refactoring Implementation Guide

## Overview
This guide explains how to implement the refactoring that renames `ScoreExtensions` to `ScoreNormalizer` throughout the Kubernetes scheduler framework.

## Why This Refactoring?
The `ScoreExtensions` interface name is misleadingly generic, but it only has a single method: `NormalizeScore`. Renaming it to `ScoreNormalizer` better reflects its actual purpose.

## Files Affected: 18 Total

### Core Framework (3 files)
1. `pkg/scheduler/framework/interface.go` - Interface and method definition
2. `pkg/scheduler/metrics/metrics.go` - Metrics constant
3. `pkg/scheduler/framework/runtime/framework.go` - Runtime implementation

### Plugin Implementations (8 files)
1. `pkg/scheduler/framework/plugins/tainttoleration/taint_toleration.go`
2. `pkg/scheduler/framework/plugins/interpodaffinity/scoring.go`
3. `pkg/scheduler/framework/plugins/volumebinding/volume_binding.go`
4. `pkg/scheduler/framework/plugins/noderesources/balanced_allocation.go`
5. `pkg/scheduler/framework/plugins/noderesources/fit.go`
6. `pkg/scheduler/framework/plugins/podtopologyspread/scoring.go`
7. `pkg/scheduler/framework/plugins/imagelocality/image_locality.go`
8. `pkg/scheduler/framework/plugins/nodeaffinity/node_affinity.go`

### Tests and Test Utilities (7 files)
1. `pkg/scheduler/framework/plugins/tainttoleration/taint_toleration_test.go`
2. `pkg/scheduler/framework/plugins/interpodaffinity/scoring_test.go`
3. `pkg/scheduler/framework/plugins/nodeaffinity/node_affinity_test.go`
4. `pkg/scheduler/framework/runtime/framework_test.go`
5. `pkg/scheduler/schedule_one_test.go`
6. `pkg/scheduler/testing/framework/fake_plugins.go`
7. `pkg/scheduler/testing/framework/fake_extender.go`

## Implementation Steps

### Option 1: Apply Patch Files (Recommended)

If you have the patch files, apply them using `git apply` or `patch` command:

```bash
# Navigate to the repository root
cd /path/to/kubernetes

# Apply all patches
git apply refactoring.patch
git apply plugins.patch
git apply tests.patch
git apply test_utilities.patch

# Or using the traditional patch command
patch -p1 < refactoring.patch
patch -p1 < plugins.patch
patch -p1 < tests.patch
patch -p1 < test_utilities.patch
```

### Option 2: Manual Implementation

Follow these changes for each file category:

#### 1. Core Interface Changes (interface.go)

**Line 482-488**: Rename the interface
```diff
-// ScoreExtensions is an interface for Score extended functionality.
-type ScoreExtensions interface {
+// ScoreNormalizer is an interface for Score normalization functionality.
+type ScoreNormalizer interface {
```

**Line 499-500**: Rename the accessor method on ScorePlugin
```diff
-	// ScoreExtensions returns a ScoreExtensions interface if it implements one, or nil if does not.
-	ScoreExtensions() ScoreExtensions
+	// ScoreNormalizer returns a ScoreNormalizer interface if it implements one, or nil if does not.
+	ScoreNormalizer() ScoreNormalizer
```

#### 2. Metrics Constant (metrics.go)

**Line 50**: Rename the metrics constant
```diff
-	ScoreExtensionNormalize     = "ScoreExtensionNormalize"
+	ScoreNormalize              = "ScoreNormalize"
```

#### 3. Runtime Framework (framework.go)

**Line 1141**: Update method call
```diff
-		if pl.ScoreExtensions() == nil {
+		if pl.ScoreNormalizer() == nil {
```

**Line 1145**: Update function name call (near line 1200)
```diff
-		status := f.runScoreExtension(ctx, pl, state, pod, nodeScoreList)
+		status := f.runScoreNormalize(ctx, pl, state, pod, nodeScoreList)
```

**Lines 1200-1208**: Rename function and update calls
```diff
-func (f *frameworkImpl) runScoreExtension(ctx context.Context, pl framework.ScorePlugin, state *framework.CycleState, pod *v1.Pod, nodeScoreList framework.NodeScoreList) *framework.Status {
+func (f *frameworkImpl) runScoreNormalize(ctx context.Context, pl framework.ScorePlugin, state *framework.CycleState, pod *v1.Pod, nodeScoreList framework.NodeScoreList) *framework.Status {
 	if !state.ShouldRecordPluginMetrics() {
-		return pl.ScoreExtensions().NormalizeScore(ctx, state, pod, nodeScoreList)
+		return pl.ScoreNormalizer().NormalizeScore(ctx, state, pod, nodeScoreList)
 	}
 	startTime := time.Now()
-	status := pl.ScoreExtensions().NormalizeScore(ctx, state, pod, nodeScoreList)
-	f.metricsRecorder.ObservePluginDurationAsync(metrics.ScoreExtensionNormalize, pl.Name(), status.Code().String(), metrics.SinceInSeconds(startTime))
+	status := pl.ScoreNormalizer().NormalizeScore(ctx, state, pod, nodeScoreList)
+	f.metricsRecorder.ObservePluginDurationAsync(metrics.ScoreNormalize, pl.Name(), status.Code().String(), metrics.SinceInSeconds(startTime))
```

#### 4. Plugin Implementations (8 plugins)

For each plugin file, make these changes:

**Comment update:**
```diff
-// ScoreExtensions of the Score plugin.
+// ScoreNormalizer of the Score plugin.
```

**Method signature:**
```diff
-func (pl *PluginName) ScoreExtensions() framework.ScoreExtensions {
+func (pl *PluginName) ScoreNormalizer() framework.ScoreNormalizer {
```

**Example for TaintToleration plugin:**
```diff
-// ScoreExtensions of the Score plugin.
-func (pl *TaintToleration) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (pl *TaintToleration) ScoreNormalizer() framework.ScoreNormalizer {
 	return pl
 }
```

#### 5. Test Files

Update test calls from `.ScoreExtensions()` to `.ScoreNormalizer()`:
```diff
-status = p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore(ctx, state, test.pod, gotList)
+status = p.(framework.ScorePlugin).ScoreNormalizer().NormalizeScore(ctx, state, test.pod, gotList)
```

Update test plugin implementations the same way as actual plugins.

## Verification Steps

### 1. Check for Remaining References

```bash
# Should find no matches in pkg/scheduler
grep -r "ScoreExtensions" pkg/scheduler --include="*.go"

# Should find no matches in pkg/scheduler
grep -r "ScoreExtensionNormalize" pkg/scheduler --include="*.go"

# Should find results (the old interface type alias or documentation) 
grep -r "ScoreNormalizer" pkg/scheduler --include="*.go"
```

### 2. Verify Compilation

```bash
# Check Go syntax
cd pkg/scheduler
go build ./...

# Or use go vet
go vet ./...
```

### 3. Run Tests

```bash
# Run scheduler tests
cd pkg/scheduler
go test ./...

# Or more specifically:
go test ./framework/...
go test ./framework/plugins/...
```

### 4. Verify Method Signatures

All `ScorePlugin` implementations should have:
```go
func (pl *PluginName) ScoreNormalizer() framework.ScoreNormalizer {
	return pl  // or nil if not implementing normalization
}
```

No implementations should have `ScoreExtensions()` method anymore.

## Common Issues and Solutions

### Issue: Build fails with "type ScoreExtensions not found"
**Solution**: Make sure you've updated interface.go first, as it's the core definition.

### Issue: Test failures with "undefined: ScoreExtensions"
**Solution**: Ensure all test files calling `.ScoreExtensions()` are updated to `.ScoreNormalizer()`.

### Issue: Some plugins still have old method names
**Solution**: Check that you've updated all 8 plugin implementations (tainttoleration, interpodaffinity, volumebinding, balanced_allocation, fit, podtopologyspread, imagelocality, nodeaffinity).

## Code Review Checklist

- [ ] interface.go: Interface renamed to ScoreNormalizer
- [ ] interface.go: ScorePlugin method renamed to ScoreNormalizer()
- [ ] metrics.go: ScoreExtensionNormalize renamed to ScoreNormalize
- [ ] framework.go: All .ScoreExtensions() calls changed to .ScoreNormalizer()
- [ ] framework.go: runScoreExtension() function renamed to runScoreNormalize()
- [ ] framework.go: metrics.ScoreExtensionNormalize changed to metrics.ScoreNormalize
- [ ] All 8 plugin implementations updated with new method name
- [ ] All 7 test/utility files updated with new method names
- [ ] No references to ScoreExtensions or ScoreExtensionNormalize remain
- [ ] All tests pass
- [ ] Code compiles without errors

## Backward Compatibility

**Breaking Change**: This is a breaking change at the API level since the interface name and method names change. Any external code implementing ScorePlugin will need to update their implementations.

## Summary of Changes

| Change Type | Count | Details |
|-------------|-------|---------|
| Interface renames | 1 | ScoreExtensions → ScoreNormalizer |
| Method renames | 10 | ScoreExtensions() → ScoreNormalizer() (1 on interface, 8 implementations, 1 function) |
| Function renames | 1 | runScoreExtension() → runScoreNormalize() |
| Constant renames | 1 | ScoreExtensionNormalize → ScoreNormalize |
| Comment updates | 10 | Updated comments referring to ScoreExtensions |
| Total files changed | 18 | - |

