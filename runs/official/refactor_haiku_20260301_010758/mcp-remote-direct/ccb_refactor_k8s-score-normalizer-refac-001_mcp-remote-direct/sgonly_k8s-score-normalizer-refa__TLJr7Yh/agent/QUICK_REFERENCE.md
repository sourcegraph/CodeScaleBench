# Quick Reference: ScoreExtensions → ScoreNormalizer Refactoring

## One-Line Summary
Rename `ScoreExtensions` interface to `ScoreNormalizer`, update all implementations and callers (19 files, ~25 changes).

---

## Search and Replace Patterns

Use these patterns in your editor to make the changes quickly:

### Pattern 1: Interface Definition
```
Find:    type ScoreExtensions interface {
Replace: type ScoreNormalizer interface {
```
**Files**: 1 (`interface.go`)

### Pattern 2: Method Signatures (Implementations)
```
Find:    func (.*) ScoreExtensions() framework.ScoreExtensions {
Replace: func $1 ScoreNormalizer() framework.ScoreNormalizer {
```
**Files**: 13 (8 plugins + 5 test implementations)

### Pattern 3: Method Calls
```
Find:    .ScoreExtensions()
Replace: .ScoreNormalizer()
```
**Files**: 4 (runtime/framework.go + 3 plugin test files)

### Pattern 4: Metrics Constant Definition
```
Find:    ScoreExtensionNormalize     = "ScoreExtensionNormalize"
Replace: ScoreNormalize              = "ScoreNormalize"
```
**Files**: 1 (`metrics.go`)

### Pattern 5: Function Definition
```
Find:    func (f *frameworkImpl) runScoreExtension(
Replace: func (f *frameworkImpl) runScoreNormalize(
```
**Files**: 1 (`runtime/framework.go`)

### Pattern 6: Comment Updates
```
Find:    // ScoreExtensions of the Score plugin.
Replace: // ScoreNormalizer of the Score plugin.
```
**Files**: 8 (plugin implementations)

---

## File-by-File Quick List

### Core Changes Required (3 files)
```
pkg/scheduler/framework/interface.go          - Change: type/method names
pkg/scheduler/metrics/metrics.go              - Change: constant name
pkg/scheduler/framework/runtime/framework.go  - Change: method/function calls
```

### Plugin Implementations (8 files)
```
pkg/scheduler/framework/plugins/noderesources/fit.go
pkg/scheduler/framework/plugins/noderesources/balanced_allocation.go
pkg/scheduler/framework/plugins/interpodaffinity/scoring.go
pkg/scheduler/framework/plugins/podtopologyspread/scoring.go
pkg/scheduler/framework/plugins/nodeaffinity/node_affinity.go
pkg/scheduler/framework/plugins/volumebinding/volume_binding.go
pkg/scheduler/framework/plugins/imagelocality/image_locality.go
pkg/scheduler/framework/plugins/tainttoleration/taint_toleration.go
```
Change: Method name and return type in each file

### Test Implementations (5 files)
```
pkg/scheduler/testing/framework/fake_plugins.go
pkg/scheduler/testing/framework/fake_extender.go
test/integration/scheduler/plugins/plugins_test.go
pkg/scheduler/schedule_one_test.go
pkg/scheduler/framework/runtime/framework_test.go
```
Change: Method name and return type in each file

### Test Method Calls (3 files)
```
pkg/scheduler/framework/plugins/interpodaffinity/scoring_test.go
pkg/scheduler/framework/plugins/nodeaffinity/node_affinity_test.go
pkg/scheduler/framework/plugins/tainttoleration/taint_toleration_test.go
```
Change: Update `.ScoreExtensions()` to `.ScoreNormalizer()` calls

---

## Validation Commands

After making changes, run these to verify:

### 1. Check for old names (should find nothing)
```bash
grep -r "ScoreExtensions" pkg/scheduler/ test/
grep -r "ScoreExtensionNormalize" pkg/scheduler/ test/
grep -r "runScoreExtension" pkg/scheduler/ test/
```

### 2. Verify new names exist
```bash
grep -r "ScoreNormalizer" pkg/scheduler/ test/ | wc -l  # Should be 20+
grep -r "ScoreNormalize" pkg/scheduler/ test/   | wc -l  # Should be 1+
grep -r "runScoreNormalize" pkg/scheduler/ test/ | wc -l  # Should be 2+
```

### 3. Build
```bash
go build ./pkg/scheduler/framework/...
go build ./pkg/scheduler/framework/plugins/...
```

### 4. Test
```bash
go test ./pkg/scheduler/framework/runtime/...
go test ./pkg/scheduler/framework/plugins/...
go test ./test/integration/scheduler/plugins/...
```

---

## Common Mistakes to Avoid

1. ❌ **Incomplete search/replace** - Use case-sensitive matching
2. ❌ **Typos** - Double-check spelling: `ScoreNormalizer` not `ScoreNormaliser`
3. ❌ **Missing test files** - Don't forget the 3 plugin test files with method calls
4. ❌ **Comment updates** - Update comment text when changing method names
5. ❌ **Partial updates** - Ensure both interface definition AND all implementations are updated

---

## Implementation Checklist

### Core Files (3)
- [ ] `interface.go` - Interface definition and method signature
- [ ] `metrics.go` - Constant name
- [ ] `framework.go` - Method calls, function name, constant usage

### Plugins (8)
- [ ] `fit.go`
- [ ] `balanced_allocation.go`
- [ ] `scoring.go` (interpodaffinity)
- [ ] `scoring.go` (podtopologyspread)
- [ ] `node_affinity.go`
- [ ] `volume_binding.go`
- [ ] `image_locality.go`
- [ ] `taint_toleration.go`

### Test Implementations (5)
- [ ] `fake_plugins.go`
- [ ] `fake_extender.go`
- [ ] `plugins_test.go` (integration)
- [ ] `schedule_one_test.go`
- [ ] `framework_test.go`

### Test Calls (3)
- [ ] `scoring_test.go` (interpodaffinity)
- [ ] `node_affinity_test.go`
- [ ] `taint_toleration_test.go`

---

## Time Estimate

- **With manual editing**: 15-20 minutes
- **With search/replace**: 5-10 minutes
- **With automated script**: 2-3 minutes

---

## Automated Implementation Script

For quick implementation using sed/awk:

```bash
# Update method implementations in plugins
find . -name "*.go" -type f | xargs sed -i \
  's/func (\([^)]*\)) ScoreExtensions() framework\.ScoreExtensions {/func (\1) ScoreNormalizer() framework.ScoreNormalizer {/g'

# Update method calls
find . -name "*.go" -type f | xargs sed -i \
  's/\.ScoreExtensions()/.ScoreNormalizer()/g'

# Update interface definition
sed -i 's/type ScoreExtensions interface {/type ScoreNormalizer interface {/g' \
  pkg/scheduler/framework/interface.go

# Update metrics constant
sed -i 's/ScoreExtensionNormalize/ScoreNormalize/g' \
  pkg/scheduler/metrics/metrics.go

# Update function name
sed -i 's/runScoreExtension(/runScoreNormalize(/g' \
  pkg/scheduler/framework/runtime/framework.go
```

**Warning**: Test the script on a copy first!

---

## Reference Links

- **Core Interface**: `pkg/scheduler/framework/interface.go` (lines 482-500)
- **Metrics Constant**: `pkg/scheduler/metrics/metrics.go` (line 50)
- **Runtime Usage**: `pkg/scheduler/framework/runtime/framework.go` (lines 1141-1206)

---

## Summary

- **19 files** total to modify
- **3 patterns** for most of the changes
- **Simple naming change** with no logic modifications
- **All changes documented** and ready to implement

---

**Status**: ✅ Ready for Implementation
