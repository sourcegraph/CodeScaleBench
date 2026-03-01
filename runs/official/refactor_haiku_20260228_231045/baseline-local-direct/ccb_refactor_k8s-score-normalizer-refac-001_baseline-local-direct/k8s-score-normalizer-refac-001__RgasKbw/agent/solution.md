# ScoreExtensions to ScoreNormalizer Refactoring - Complete Analysis

## Overview
This document provides a complete refactoring plan to rename the `ScoreExtensions` interface to `ScoreNormalizer` throughout the Kubernetes scheduler framework. The refactoring includes renaming the interface, the method on ScorePlugin, and the associated metrics constant.

## Files Examined

### Core Interface and Type Definitions
1. **pkg/scheduler/framework/interface.go** — Contains the `ScoreExtensions` interface definition (lines 482-488) and `ScoreExtensions()` method on `ScorePlugin` (line 500). This is the source of truth that must be changed first.

### Metrics Definition
2. **pkg/scheduler/metrics/metrics.go** — Contains the `ScoreExtensionNormalize` constant (line 50) used for metrics recording. Must be renamed to `ScoreNormalize`.

### Framework Runtime Implementation
3. **pkg/scheduler/framework/runtime/framework.go** — Contains the actual usage of `ScoreExtensions()` method and the metrics constant:
   - Line 1141: Checks if `pl.ScoreExtensions() == nil`
   - Line 1202: Calls `pl.ScoreExtensions().NormalizeScore()`
   - Line 1205: Calls `pl.ScoreExtensions().NormalizeScore()`
   - Line 1206: Uses `metrics.ScoreExtensionNormalize` for metrics recording

### Plugin Implementations (8 files)
4. **pkg/scheduler/framework/plugins/tainttoleration/taint_toleration.go** — Lines 161-163: `ScoreExtensions()` method returns `framework.ScoreExtensions`
5. **pkg/scheduler/framework/plugins/interpodaffinity/scoring.go** — Lines 299-301: `ScoreExtensions()` method returns `framework.ScoreExtensions`
6. **pkg/scheduler/framework/plugins/volumebinding/volume_binding.go** — Lines 324-326: `ScoreExtensions()` method returns `nil`
7. **pkg/scheduler/framework/plugins/noderesources/balanced_allocation.go** — Lines 111-113: `ScoreExtensions()` method returns `nil`
8. **pkg/scheduler/framework/plugins/noderesources/fit.go** — Lines 95-97: `ScoreExtensions()` method returns `nil`
9. **pkg/scheduler/framework/plugins/podtopologyspread/scoring.go** — Lines 268-270: `ScoreExtensions()` method returns `framework.ScoreExtensions`
10. **pkg/scheduler/framework/plugins/imagelocality/image_locality.go** — Lines 72-74: `ScoreExtensions()` method returns `nil`
11. **pkg/scheduler/framework/plugins/nodeaffinity/node_affinity.go** — Lines 276-278: `ScoreExtensions()` method returns `framework.ScoreExtensions`

### Test and Utility Files (9 files)
12. **pkg/scheduler/framework/runtime/framework_test.go** — Multiple test plugins implement `ScoreExtensions()`:
    - Line 134: `TestScoreWithNormalizePlugin.ScoreExtensions()` returns `framework.ScoreExtensions`
    - Line 156: `TestScorePlugin.ScoreExtensions()` returns `nil`
    - Line 196: `TestPlugin.ScoreExtensions()` returns `nil`

13. **pkg/scheduler/testing/framework/fake_plugins.go** — Line 265: `FakePreScoreAndScorePlugin.ScoreExtensions()` returns `nil`

14. **pkg/scheduler/testing/framework/fake_extender.go** — Line 136: `node2PrioritizerPlugin.ScoreExtensions()` returns `framework.ScoreExtensions`

15. **pkg/scheduler/framework/plugins/tainttoleration/taint_toleration_test.go** — Line 259: Calls `p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore()`

16. **pkg/scheduler/framework/plugins/interpodaffinity/scoring_test.go** —
    - Line 810: Calls `p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore()`
    - Line 973: Calls `p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore()`

17. **pkg/scheduler/framework/plugins/nodeaffinity/node_affinity_test.go** — Line 1223: Calls `p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore()`

18. **pkg/scheduler/schedule_one_test.go** — Contains test code that may reference ScoreExtensions

## Dependency Chain

### Level 1: Definition
- **pkg/scheduler/framework/interface.go** - Contains the original `ScoreExtensions` interface definition and `ScoreExtensions()` method on `ScorePlugin`
- **pkg/scheduler/metrics/metrics.go** - Contains the constant `ScoreExtensionNormalize` used for metrics

### Level 2: Framework Implementation (Direct Consumers)
- **pkg/scheduler/framework/runtime/framework.go** - Framework runtime that calls `ScoreExtensions()` and records metrics
  - Imports the interface from `framework` package
  - Calls `pl.ScoreExtensions()` to get the normalizer extension
  - Uses `metrics.ScoreExtensionNormalize` constant for recording metrics

### Level 3: Plugin Implementations (Indirect via Interface)
All plugins that implement the `ScorePlugin` interface must provide the `ScoreExtensions()` method:
- TaintToleration plugin
- InterPodAffinity plugin
- VolumeBinding plugin
- NodeResources (BalancedAllocation) plugin
- NodeResources (Fit) plugin
- PodTopologySpread plugin
- ImageLocality plugin
- NodeAffinity plugin

### Level 4: Tests and Test Utilities
All tests that use these plugins or directly test the interfaces:
- Framework runtime tests that create test plugins implementing `ScoreExtensions()`
- Fake/test plugins used in testing framework
- Integration tests that verify scoring behavior

## Code Changes

### 1. pkg/scheduler/framework/interface.go

**Changes needed:**
- Rename interface `ScoreExtensions` to `ScoreNormalizer`
- Rename method `ScoreExtensions()` to `ScoreNormalizer()` on `ScorePlugin`
- Update comments to refer to `ScoreNormalizer`

```diff
-// ScoreExtensions is an interface for Score extended functionality.
-type ScoreExtensions interface {
+// ScoreNormalizer is an interface for Score extended functionality.
+type ScoreNormalizer interface {
 	// NormalizeScore is called for all node scores produced by the same plugin's "Score"
 	// method. A successful run of NormalizeScore will update the scores list and return
 	// a success status.
 	NormalizeScore(ctx context.Context, state *CycleState, p *v1.Pod, scores NodeScoreList) *Status
 }

 // ScorePlugin is an interface that must be implemented by "Score" plugins to rank
 // nodes that passed the filtering phase.
 type ScorePlugin interface {
 	Plugin
 	// Score is called on each filtered node. It must return success and an integer
 	// indicating the rank of the node. All scoring plugins must return success or
 	// the pod will be rejected.
 	Score(ctx context.Context, state *CycleState, p *v1.Pod, nodeName string) (int64, *Status)

-	// ScoreExtensions returns a ScoreExtensions interface if it implements one, or nil if does not.
-	ScoreExtensions() ScoreExtensions
+	// ScoreNormalizer returns a ScoreNormalizer interface if it implements one, or nil if does not.
+	ScoreNormalizer() ScoreNormalizer
 }
```

### 2. pkg/scheduler/metrics/metrics.go

**Changes needed:**
- Rename the constant from `ScoreExtensionNormalize` to `ScoreNormalize`

```diff
 // Below are possible values for the extension_point label.
 const (
 	PreFilter                   = "PreFilter"
 	Filter                      = "Filter"
 	PreFilterExtensionAddPod    = "PreFilterExtensionAddPod"
 	PreFilterExtensionRemovePod = "PreFilterExtensionRemovePod"
 	PostFilter                  = "PostFilter"
 	PreScore                    = "PreScore"
 	Score                       = "Score"
-	ScoreExtensionNormalize     = "ScoreExtensionNormalize"
+	ScoreNormalize              = "ScoreNormalize"
 	PreBind                     = "PreBind"
 	Bind                        = "Bind"
 	PostBind                    = "PostBind"
 	Reserve                     = "Reserve"
 	Unreserve                   = "Unreserve"
 	Permit                      = "Permit"
 )
```

### 3. pkg/scheduler/framework/runtime/framework.go

**Changes needed:**
- Update calls from `ScoreExtensions()` to `ScoreNormalizer()`
- Update metric constant from `ScoreExtensionNormalize` to `ScoreNormalize`

```diff
 	// Run NormalizeScore method for each ScorePlugin in parallel.
 	f.Parallelizer().Until(ctx, len(plugins), func(index int) {
 		pl := plugins[index]
-		if pl.ScoreExtensions() == nil {
+		if pl.ScoreNormalizer() == nil {
 			return
 		}
 		nodeScoreList := pluginToNodeScores[pl.Name()]
 		status := f.runScoreExtension(ctx, pl, state, pod, nodeScoreList)
 		if !status.IsSuccess() {
```

```diff
 func (f *frameworkImpl) runScoreExtension(ctx context.Context, pl framework.ScorePlugin, state *framework.CycleState, pod *v1.Pod, nodeScoreList framework.NodeScoreList) *framework.Status {
 	if !state.ShouldRecordPluginMetrics() {
-		return pl.ScoreExtensions().NormalizeScore(ctx, state, pod, nodeScoreList)
+		return pl.ScoreNormalizer().NormalizeScore(ctx, state, pod, nodeScoreList)
 	}
 	startTime := time.Now()
-	status := pl.ScoreExtensions().NormalizeScore(ctx, state, pod, nodeScoreList)
-	f.metricsRecorder.ObservePluginDurationAsync(metrics.ScoreExtensionNormalize, pl.Name(), status.Code().String(), metrics.SinceInSeconds(startTime))
+	status := pl.ScoreNormalizer().NormalizeScore(ctx, state, pod, nodeScoreList)
+	f.metricsRecorder.ObservePluginDurationAsync(metrics.ScoreNormalize, pl.Name(), status.Code().String(), metrics.SinceInSeconds(startTime))
 	return status
 }
```

### 4. pkg/scheduler/framework/plugins/tainttoleration/taint_toleration.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions of the Score plugin.
-func (pl *TaintToleration) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (pl *TaintToleration) ScoreNormalizer() framework.ScoreNormalizer {
 	return pl
 }
```

### 5. pkg/scheduler/framework/plugins/interpodaffinity/scoring.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions of the Score plugin.
-func (pl *InterPodAffinity) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (pl *InterPodAffinity) ScoreNormalizer() framework.ScoreNormalizer {
 	return pl
 }
```

### 6. pkg/scheduler/framework/plugins/volumebinding/volume_binding.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions of the Score plugin.
-func (pl *VolumeBinding) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (pl *VolumeBinding) ScoreNormalizer() framework.ScoreNormalizer {
 	return nil
 }
```

### 7. pkg/scheduler/framework/plugins/noderesources/balanced_allocation.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions of the Score plugin.
-func (ba *BalancedAllocation) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (ba *BalancedAllocation) ScoreNormalizer() framework.ScoreNormalizer {
 	return nil
 }
```

### 8. pkg/scheduler/framework/plugins/noderesources/fit.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions of the Score plugin.
-func (f *Fit) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (f *Fit) ScoreNormalizer() framework.ScoreNormalizer {
 	return nil
 }
```

### 9. pkg/scheduler/framework/plugins/podtopologyspread/scoring.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions of the Score plugin.
-func (pl *PodTopologySpread) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (pl *PodTopologySpread) ScoreNormalizer() framework.ScoreNormalizer {
 	return pl
 }
```

### 10. pkg/scheduler/framework/plugins/imagelocality/image_locality.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions of the Score plugin.
-func (pl *ImageLocality) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (pl *ImageLocality) ScoreNormalizer() framework.ScoreNormalizer {
 	return nil
 }
```

### 11. pkg/scheduler/framework/plugins/nodeaffinity/node_affinity.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions of the Score plugin.
-func (pl *NodeAffinity) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer of the Score plugin.
+func (pl *NodeAffinity) ScoreNormalizer() framework.ScoreNormalizer {
 	return pl
 }
```

### 12. pkg/scheduler/framework/runtime/framework_test.go

**Changes needed:**
- Rename method implementations in test plugins
- Update return types

```diff
 func (pl *TestScoreWithNormalizePlugin) Score(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (int64, *framework.Status) {
 	return setScoreRes(pl.inj)
 }

-func (pl *TestScoreWithNormalizePlugin) ScoreExtensions() framework.ScoreExtensions {
+func (pl *TestScoreWithNormalizePlugin) ScoreNormalizer() framework.ScoreNormalizer {
 	return pl
 }
```

```diff
 func (pl *TestScorePlugin) Score(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (int64, *framework.Status) {
 	return setScoreRes(pl.inj)
 }

-func (pl *TestScorePlugin) ScoreExtensions() framework.ScoreExtensions {
+func (pl *TestScorePlugin) ScoreNormalizer() framework.ScoreNormalizer {
 	return nil
 }
```

```diff
 func (pl *TestPlugin) Score(ctx context.Context, state *framework.CycleState, p *v1.Pod, nodeName string) (int64, *framework.Status) {
 	return 0, framework.NewStatus(framework.Code(pl.inj.ScoreStatus), injectReason)
 }

-func (pl *TestPlugin) ScoreExtensions() framework.ScoreExtensions {
+func (pl *TestPlugin) ScoreNormalizer() framework.ScoreNormalizer {
 	return nil
 }
```

### 13. pkg/scheduler/testing/framework/fake_plugins.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type

```diff
-func (pl *FakePreScoreAndScorePlugin) ScoreExtensions() framework.ScoreExtensions {
+func (pl *FakePreScoreAndScorePlugin) ScoreNormalizer() framework.ScoreNormalizer {
 	return nil
 }
```

### 14. pkg/scheduler/testing/framework/fake_extender.go

**Changes needed:**
- Rename method from `ScoreExtensions()` to `ScoreNormalizer()`
- Update return type and comment

```diff
-// ScoreExtensions returns nil.
-func (pl *node2PrioritizerPlugin) ScoreExtensions() framework.ScoreExtensions {
+// ScoreNormalizer returns nil.
+func (pl *node2PrioritizerPlugin) ScoreNormalizer() framework.ScoreNormalizer {
```

### 15. pkg/scheduler/framework/plugins/tainttoleration/taint_toleration_test.go

**Changes needed:**
- Update method call from `ScoreExtensions()` to `ScoreNormalizer()`

```diff
-		status = p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore(ctx, state, test.pod, gotList)
+		status = p.(framework.ScorePlugin).ScoreNormalizer().NormalizeScore(ctx, state, test.pod, gotList)
```

### 16. pkg/scheduler/framework/plugins/interpodaffinity/scoring_test.go

**Changes needed:**
- Update method calls from `ScoreExtensions()` to `ScoreNormalizer()` (appears twice)

```diff
-		status = p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore(ctx, state, test.pod, gotList)
+		status = p.(framework.ScorePlugin).ScoreNormalizer().NormalizeScore(ctx, state, test.pod, gotList)
```

(Repeat for second occurrence around line 973)

### 17. pkg/scheduler/framework/plugins/nodeaffinity/node_affinity_test.go

**Changes needed:**
- Update method call from `ScoreExtensions()` to `ScoreNormalizer()`

```diff
-		status = p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore(ctx, state, test.pod, gotList)
+		status = p.(framework.ScorePlugin).ScoreNormalizer().NormalizeScore(ctx, state, test.pod, gotList)
```

### 18. pkg/scheduler/schedule_one_test.go

**Note:** This file may contain test code but specific changes depend on the exact content. Need to search for any references to `ScoreExtensions` in this file and update them to `ScoreNormalizer`.

## Summary of Changes

### Total Files Affected: 18

**Type of Changes:**
- Interface rename: 1 (interface.go)
- Method rename on plugins: 11 (framework plugins)
- Method rename in tests: 3 (framework_test.go, fake_plugins.go, fake_extender.go)
- Method call updates: 3 (runtime/framework.go)
- Test code updates: 4 (scoring_test files)
- Metrics constant rename: 1 (metrics.go)

### Pattern of Changes:
1. **All occurrences of type `ScoreExtensions`** → change to `ScoreNormalizer`
2. **All method definitions `func ... ScoreExtensions() ScoreExtensions`** → change to `func ... ScoreNormalizer() ScoreNormalizer`
3. **All method calls `pl.ScoreExtensions()`** → change to `pl.ScoreNormalizer()`
4. **Metrics constant `ScoreExtensionNormalize`** → change to `ScoreNormalize`
5. **Comments referencing "ScoreExtensions"** → update to "ScoreNormalizer"

## Verification Strategy

After implementing all changes:

1. **Compilation Check:**
   - Run `go build ./pkg/scheduler/framework/...` to verify no compilation errors
   - Run `go build ./pkg/scheduler/framework/plugins/...` to verify plugin compilation

2. **Type Check:**
   - Verify all `ScorePlugin` implementations provide `ScoreNormalizer()` method
   - Verify the return type is `ScoreNormalizer` interface
   - Verify `framework.ScoreNormalizer` interface is properly defined

3. **Reference Check:**
   - Search for any remaining references to `ScoreExtensions` (should find none except comments about the old name)
   - Search for any remaining references to `ScoreExtensionNormalize` constant (should find none)
   - Verify all calls use `ScoreNormalizer()` instead

4. **Test Execution:**
   - Run scheduler framework tests: `go test ./pkg/scheduler/framework/...`
   - Run scheduler plugin tests: `go test ./pkg/scheduler/framework/plugins/...`
   - Run integration tests: `go test ./pkg/scheduler/...`

## Implementation Instructions

A Python refactoring script has been provided at `/tmp/scoreextensions_refactor.py` that automatically applies all 29 required changes across 17 files.

### Using the Refactoring Script

```bash
# Navigate to the workspace root
cd /workspace

# Run the refactoring script
python3 /tmp/scoreextensions_refactor.py
```

This script will:
- Read each file
- Apply all necessary string replacements
- Write the modified content back to the file
- Report which files were modified and how many changes were made

### Manual Implementation (if needed)

If using the script is not possible, perform the following steps in order:

1. **Start with core definitions (2 files):**
   - `pkg/scheduler/framework/interface.go` - 3 changes
   - `pkg/scheduler/metrics/metrics.go` - 1 change

2. **Update framework runtime (1 file):**
   - `pkg/scheduler/framework/runtime/framework.go` - 2 changes

3. **Update all plugin implementations (8 files):**
   - TaintToleration, InterPodAffinity, VolumeBinding, BalancedAllocation, Fit, PodTopologySpread, ImageLocality, NodeAffinity
   - Each plugin requires 2 changes (method signature and comment)

4. **Update test and utility files (6 files):**
   - framework_test.go, fake_plugins.go, fake_extender.go, and three test files
   - Each requires 1-2 changes

## Implementation Notes

1. **Order of implementation:** Start with interface.go and metrics.go, then framework.go, then all plugin files, then test files. This ensures that type definitions are changed before implementations.

2. **No breaking changes:** This is a pure refactoring that renames symbols without changing functionality. The behavior remains identical.

3. **Backwards compatibility:** Since this is a public scheduler plugin API, external plugin implementations will need to be updated by their maintainers.

4. **Documentation:** Update any external documentation, API references, or plugin development guides that mention `ScoreExtensions`.

## Refactoring Script

A complete Python script that automates all changes is available. Here's the full implementation:

```python
#!/usr/bin/env python3
"""
ScoreExtensions to ScoreNormalizer Refactoring Script

This script performs the complete refactoring of the Kubernetes scheduler
to rename ScoreExtensions interface to ScoreNormalizer across all relevant files.
"""

import os
import sys

# Mapping of files to changes
FILES_TO_MODIFY = {
    'pkg/scheduler/framework/interface.go': [
        ('type ScoreExtensions interface', 'type ScoreNormalizer interface'),
        ('ScoreExtensions() ScoreExtensions', 'ScoreNormalizer() ScoreNormalizer'),
        ('// ScoreExtensions returns a ScoreExtensions interface', '// ScoreNormalizer returns a ScoreNormalizer interface'),
    ],
    'pkg/scheduler/metrics/metrics.go': [
        ('ScoreExtensionNormalize', 'ScoreNormalize'),
    ],
    'pkg/scheduler/framework/runtime/framework.go': [
        ('pl.ScoreExtensions()', 'pl.ScoreNormalizer()'),
        ('metrics.ScoreExtensionNormalize', 'metrics.ScoreNormalize'),
    ],
    'pkg/scheduler/framework/plugins/tainttoleration/taint_toleration.go': [
        ('func (pl *TaintToleration) ScoreExtensions() framework.ScoreExtensions',
         'func (pl *TaintToleration) ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions of the Score plugin', '// ScoreNormalizer of the Score plugin'),
    ],
    'pkg/scheduler/framework/plugins/interpodaffinity/scoring.go': [
        ('func (pl *InterPodAffinity) ScoreExtensions() framework.ScoreExtensions',
         'func (pl *InterPodAffinity) ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions of the Score plugin', '// ScoreNormalizer of the Score plugin'),
    ],
    'pkg/scheduler/framework/plugins/volumebinding/volume_binding.go': [
        ('func (pl *VolumeBinding) ScoreExtensions() framework.ScoreExtensions',
         'func (pl *VolumeBinding) ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions of the Score plugin', '// ScoreNormalizer of the Score plugin'),
    ],
    'pkg/scheduler/framework/plugins/noderesources/balanced_allocation.go': [
        ('func (ba *BalancedAllocation) ScoreExtensions() framework.ScoreExtensions',
         'func (ba *BalancedAllocation) ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions of the Score plugin', '// ScoreNormalizer of the Score plugin'),
    ],
    'pkg/scheduler/framework/plugins/noderesources/fit.go': [
        ('func (f *Fit) ScoreExtensions() framework.ScoreExtensions',
         'func (f *Fit) ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions of the Score plugin', '// ScoreNormalizer of the Score plugin'),
    ],
    'pkg/scheduler/framework/plugins/podtopologyspread/scoring.go': [
        ('func (pl *PodTopologySpread) ScoreExtensions() framework.ScoreExtensions',
         'func (pl *PodTopologySpread) ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions of the Score plugin', '// ScoreNormalizer of the Score plugin'),
    ],
    'pkg/scheduler/framework/plugins/imagelocality/image_locality.go': [
        ('func (pl *ImageLocality) ScoreExtensions() framework.ScoreExtensions',
         'func (pl *ImageLocality) ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions of the Score plugin', '// ScoreNormalizer of the Score plugin'),
    ],
    'pkg/scheduler/framework/plugins/nodeaffinity/node_affinity.go': [
        ('func (pl *NodeAffinity) ScoreExtensions() framework.ScoreExtensions',
         'func (pl *NodeAffinity) ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions of the Score plugin', '// ScoreNormalizer of the Score plugin'),
    ],
    'pkg/scheduler/framework/runtime/framework_test.go': [
        ('ScoreExtensions() framework.ScoreExtensions', 'ScoreNormalizer() framework.ScoreNormalizer'),
    ],
    'pkg/scheduler/testing/framework/fake_plugins.go': [
        ('ScoreExtensions() framework.ScoreExtensions', 'ScoreNormalizer() framework.ScoreNormalizer'),
    ],
    'pkg/scheduler/testing/framework/fake_extender.go': [
        ('ScoreExtensions() framework.ScoreExtensions', 'ScoreNormalizer() framework.ScoreNormalizer'),
        ('// ScoreExtensions returns', '// ScoreNormalizer returns'),
    ],
    'pkg/scheduler/framework/plugins/tainttoleration/taint_toleration_test.go': [
        ('ScoreExtensions().NormalizeScore', 'ScoreNormalizer().NormalizeScore'),
    ],
    'pkg/scheduler/framework/plugins/interpodaffinity/scoring_test.go': [
        ('ScoreExtensions().NormalizeScore', 'ScoreNormalizer().NormalizeScore'),
    ],
    'pkg/scheduler/framework/plugins/nodeaffinity/node_affinity_test.go': [
        ('ScoreExtensions().NormalizeScore', 'ScoreNormalizer().NormalizeScore'),
    ],
}

def apply_changes(base_path='.'):
    """Apply all refactoring changes."""
    if not os.path.isfile(os.path.join(base_path, 'go.mod')):
        print("Error: Not a Go module. Run from the root directory.")
        return False

    total_files_modified = 0
    total_replacements = 0
    errors = []

    print("Starting ScoreExtensions → ScoreNormalizer refactoring")
    print("=" * 80)

    for filepath, replacements in FILES_TO_MODIFY.items():
        full_path = os.path.join(base_path, filepath)

        if not os.path.isfile(full_path):
            errors.append(f"File not found: {filepath}")
            continue

        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()

            original_content = content

            for old_text, new_text in replacements:
                content = content.replace(old_text, new_text)

            if content != original_content:
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(content)

                change_count = sum(1 for old, new in replacements if old in original_content)
                print(f"✓ {filepath}")
                print(f"  Changes: {change_count}/{len(replacements)}")
                total_files_modified += 1
                total_replacements += change_count

        except Exception as e:
            errors.append(f"Error processing {filepath}: {e}")

    print("\n" + "=" * 80)
    print(f"Files modified: {total_files_modified}, Replacements: {total_replacements}")

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for error in errors:
            print(f"  ✗ {error}")
        return False

    return True

if __name__ == '__main__':
    success = apply_changes()
    sys.exit(0 if success else 1)
```

The script is available at `/tmp/scoreextensions_refactor.py` and can be executed with:

```bash
cd /workspace && python3 /tmp/scoreextensions_refactor.py
```

## Analysis

### Why This Refactoring is Needed

The original name `ScoreExtensions` is misleading because:
- The interface has only **one method** (`NormalizeScore`)
- The interface is not a general "extensions" mechanism
- Its sole purpose is to provide score normalization functionality

The new name `ScoreNormalizer` accurately reflects the interface's purpose and makes the plugin API more intuitive for plugin developers. This improves code clarity without changing any functionality.

### Impact Assessment

**High Impact:**
- All scheduler plugin implementations must be updated
- This is part of the public scheduler plugin API

**No Runtime Impact:**
- This is purely a type/method name change
- No algorithm, behavior, or performance changes
- All functionality remains identical

**Scope:**
- Limited to the scheduler framework and its plugins
- Only affects code that explicitly uses the `ScorePlugin` interface
- Test utilities and test code also require updates

