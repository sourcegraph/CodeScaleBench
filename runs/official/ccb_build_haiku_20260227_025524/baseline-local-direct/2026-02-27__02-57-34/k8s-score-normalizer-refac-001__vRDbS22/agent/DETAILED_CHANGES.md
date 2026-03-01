# Detailed Changes for ScoreExtensions → ScoreNormalizer Refactoring

## 1. pkg/scheduler/framework/interface.go

### Change 1.1: Interface Definition (Line 482-488)
```go
// OLD
// ScoreExtensions is an interface for Score extended functionality.
type ScoreExtensions interface {
	// NormalizeScore is called for all node scores produced by the same plugin's "Score"
	// method. A successful run of NormalizeScore will update the scores list and return
	// a success status.
	NormalizeScore(ctx context.Context, state *CycleState, p *v1.Pod, scores NodeScoreList) *Status
}

// NEW
// ScoreNormalizer is an interface for Score normalization functionality.
type ScoreNormalizer interface {
	// NormalizeScore is called for all node scores produced by the same plugin's "Score"
	// method. A successful run of NormalizeScore will update the scores list and return
	// a success status.
	NormalizeScore(ctx context.Context, state *CycleState, p *v1.Pod, scores NodeScoreList) *Status
}
```

### Change 1.2: ScorePlugin Interface Method (Line 499-500)
```go
// OLD
// ScoreExtensions returns a ScoreExtensions interface if it implements one, or nil if does not.
ScoreExtensions() ScoreExtensions

// NEW
// ScoreNormalizer returns a ScoreNormalizer interface if it implements one, or nil if does not.
ScoreNormalizer() ScoreNormalizer
```

## 2. pkg/scheduler/metrics/metrics.go

### Change 2.1: Metrics Constant (Line 50)
```go
// OLD
ScoreExtensionNormalize     = "ScoreExtensionNormalize"

// NEW
ScoreNormalize              = "ScoreNormalize"
```

## 3. pkg/scheduler/framework/runtime/framework.go

### Change 3.1: Method Call in RunScorePlugins (Line 1141)
```go
// OLD
if pl.ScoreExtensions() == nil {

// NEW
if pl.ScoreNormalizer() == nil {
```

### Change 3.2: Function Call in RunScorePlugins (Line ~1145)
```go
// OLD
status := f.runScoreExtension(ctx, pl, state, pod, nodeScoreList)

// NEW
status := f.runScoreNormalize(ctx, pl, state, pod, nodeScoreList)
```

### Change 3.3: Function Definition (Line 1200)
```go
// OLD
func (f *frameworkImpl) runScoreExtension(ctx context.Context, pl framework.ScorePlugin, state *framework.CycleState, pod *v1.Pod, nodeScoreList framework.NodeScoreList) *framework.Status {

// NEW
func (f *frameworkImpl) runScoreNormalize(ctx context.Context, pl framework.ScorePlugin, state *framework.CycleState, pod *v1.Pod, nodeScoreList framework.NodeScoreList) *framework.Status {
```

### Change 3.4: Method Call in runScoreNormalize (Line 1202)
```go
// OLD
return pl.ScoreExtensions().NormalizeScore(ctx, state, pod, nodeScoreList)

// NEW
return pl.ScoreNormalizer().NormalizeScore(ctx, state, pod, nodeScoreList)
```

### Change 3.5: Method Call in runScoreNormalize (Line 1205)
```go
// OLD
status := pl.ScoreExtensions().NormalizeScore(ctx, state, pod, nodeScoreList)

// NEW
status := pl.ScoreNormalizer().NormalizeScore(ctx, state, pod, nodeScoreList)
```

### Change 3.6: Metrics Constant in runScoreNormalize (Line 1206)
```go
// OLD
f.metricsRecorder.ObservePluginDurationAsync(metrics.ScoreExtensionNormalize, pl.Name(), status.Code().String(), metrics.SinceInSeconds(startTime))

// NEW
f.metricsRecorder.ObservePluginDurationAsync(metrics.ScoreNormalize, pl.Name(), status.Code().String(), metrics.SinceInSeconds(startTime))
```

## 4. Plugin Implementations (8 files)

### Pattern for All 8 Plugins:

**Comment:**
```go
// OLD
// ScoreExtensions of the Score plugin.

// NEW
// ScoreNormalizer of the Score plugin.
```

**Method Signature:**
```go
// OLD
func (pl *PluginName) ScoreExtensions() framework.ScoreExtensions {

// NEW
func (pl *PluginName) ScoreNormalizer() framework.ScoreNormalizer {
```

### Affected Files:
1. **pkg/scheduler/framework/plugins/tainttoleration/taint_toleration.go** (Lines 161-164)
2. **pkg/scheduler/framework/plugins/interpodaffinity/scoring.go** (Lines 299-302)
3. **pkg/scheduler/framework/plugins/volumebinding/volume_binding.go** (Lines 324-327)
4. **pkg/scheduler/framework/plugins/noderesources/balanced_allocation.go** (Lines 111-114)
5. **pkg/scheduler/framework/plugins/noderesources/fit.go** (Lines 95-98)
6. **pkg/scheduler/framework/plugins/podtopologyspread/scoring.go** (Lines 268-271)
7. **pkg/scheduler/framework/plugins/imagelocality/image_locality.go** (Lines 72-75)
8. **pkg/scheduler/framework/plugins/nodeaffinity/node_affinity.go** (Lines 276-279)

## 5. Test Files with Method Calls

### Pattern: Update method call in test assertions

**Pattern:**
```go
// OLD
status = p.(framework.ScorePlugin).ScoreExtensions().NormalizeScore(ctx, state, test.pod, gotList)

// NEW
status = p.(framework.ScorePlugin).ScoreNormalizer().NormalizeScore(ctx, state, test.pod, gotList)
```

### Affected Files and Lines:
1. **pkg/scheduler/framework/plugins/tainttoleration/taint_toleration_test.go** (Line 259)
2. **pkg/scheduler/framework/plugins/interpodaffinity/scoring_test.go** (Lines 810, 973)
3. **pkg/scheduler/framework/plugins/nodeaffinity/node_affinity_test.go** (Line 1223)

## 6. Test Plugin Implementations

### Pattern for Test Plugins:

Same as production plugins - update both comment and method signature.

**Comment:**
```go
// OLD
// (optional comment like "ScoreExtensions returns nil.")

// NEW
// (updated comment like "ScoreNormalizer returns nil.")
```

**Method:**
```go
// OLD
func (pl *TestPluginName) ScoreExtensions() framework.ScoreExtensions {

// NEW
func (pl *TestPluginName) ScoreNormalizer() framework.ScoreNormalizer {
```

### Affected Files and Line Ranges:

1. **pkg/scheduler/framework/runtime/framework_test.go**
   - Line 132-137: TestScoreWithNormalizePlugin
   - Line 154-159: TestScorePlugin  
   - Line 194-199: TestPlugin

2. **pkg/scheduler/schedule_one_test.go**
   - Line 171-176: falseMapPlugin
   - Line 195-200: numericMapPlugin
   - Line 218-223: reverseNumericMapPlugin
   - Line 255-260: trueMapPlugin
   - Line 369-374: TestPlugin

3. **pkg/scheduler/testing/framework/fake_plugins.go**
   - Line 263-268: FakePreScoreAndScorePlugin

4. **pkg/scheduler/testing/framework/fake_extender.go**
   - Line 133-139: node2PrioritizerPlugin (also update comment on line 135)

## Summary Statistics

| Category | Count | Details |
|----------|-------|---------|
| Interface definitions | 1 | type ScoreExtensions → type ScoreNormalizer |
| Interface methods | 1 | ScoreExtensions() → ScoreNormalizer() on ScorePlugin |
| Constants | 1 | ScoreExtensionNormalize → ScoreNormalize |
| Function definitions | 1 | runScoreExtension() → runScoreNormalize() |
| Function implementations | 8 | Plugin method implementations |
| Test plugin implementations | 5 | Test-only plugin definitions |
| Test helper implementations | 2 | Testing framework helpers |
| Method calls | 6 | Direct method invocations |
| Test assertions | 3 | Test method calls in assertions |
| Comment updates | 10+ | Comments referring to ScoreExtensions |
| **Total files** | **18** | - |

## Verification Commands

```bash
# 1. Check no old names remain
grep -r "ScoreExtensions" pkg/scheduler --include="*.go" | wc -l  # Should be 0
grep -r "ScoreExtensionNormalize" pkg/scheduler --include="*.go" | wc -l  # Should be 0

# 2. Check new names are present
grep -r "ScoreNormalizer" pkg/scheduler --include="*.go" | wc -l  # Should be > 0
grep -r "ScoreNormalize" pkg/scheduler --include="*.go" | wc -l  # Should be > 0

# 3. Compile check
cd pkg/scheduler && go build ./...

# 4. Run tests
cd pkg/scheduler && go test ./...
```

