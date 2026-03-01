#!/bin/bash
# ScoreExtensions to ScoreNormalizer Refactoring Script
# This script performs a complete refactoring of the Kubernetes scheduler
# to rename ScoreExtensions interface to ScoreNormalizer

set -e

echo "Starting ScoreExtensions to ScoreNormalizer refactoring..."
cd /workspace

# ============================================================
# 1. Core Interface Definition
# ============================================================
echo "1. Updating pkg/scheduler/framework/interface.go..."

# Create a temporary file with all the changes
cat > /tmp/interface_changes.sed << 'SEDDOC'
# Change the interface comment and name
s/\/\/ ScoreExtensions is an interface for Score extended functionality\./\/\/ ScoreNormalizer is an interface for normalizing scores produced by a Score plugin./
s/^type ScoreExtensions interface {/type ScoreNormalizer interface {/

# Update ScorePlugin method comment and signature
s/\/\/ ScoreExtensions returns a ScoreExtensions interface/\/\/ ScoreNormalizer returns a ScoreNormalizer interface/
s/ScoreExtensions() ScoreExtensions/ScoreNormalizer() ScoreNormalizer/
SEDDOC

sed -i.bak -f /tmp/interface_changes.sed pkg/scheduler/framework/interface.go

# ============================================================
# 2. Metrics Definition
# ============================================================
echo "2. Updating pkg/scheduler/metrics/metrics.go..."

sed -i.bak 's/^\tScoreExtensionNormalize\s*=/\tScoreNormalize                 =/g' pkg/scheduler/metrics/metrics.go

# ============================================================
# 3. Runtime Framework
# ============================================================
echo "3. Updating pkg/scheduler/framework/runtime/framework.go..."

# Update the call to ScoreExtensions()
sed -i.bak 's/if pl\.ScoreExtensions() == nil/if pl.ScoreNormalizer() == nil/g' pkg/scheduler/framework/runtime/framework.go

# Update NormalizeScore calls
sed -i.bak 's/pl\.ScoreExtensions()\.NormalizeScore/pl.ScoreNormalizer().NormalizeScore/g' pkg/scheduler/framework/runtime/framework.go

# Update metrics reference
sed -i.bak 's/metrics\.ScoreExtensionNormalize/metrics.ScoreNormalize/g' pkg/scheduler/framework/runtime/framework.go

# ============================================================
# 4. Plugin Implementations
# ============================================================
echo "4. Updating plugin implementations..."

PLUGIN_FILES=(
    "pkg/scheduler/framework/plugins/tainttoleration/taint_toleration.go"
    "pkg/scheduler/framework/plugins/interpodaffinity/scoring.go"
    "pkg/scheduler/framework/plugins/podtopologyspread/scoring.go"
    "pkg/scheduler/framework/plugins/nodeaffinity/node_affinity.go"
    "pkg/scheduler/framework/plugins/volumebinding/volume_binding.go"
    "pkg/scheduler/framework/plugins/noderesources/balanced_allocation.go"
    "pkg/scheduler/framework/plugins/noderesources/fit.go"
    "pkg/scheduler/framework/plugins/imagelocality/image_locality.go"
)

for file in "${PLUGIN_FILES[@]}"; do
    echo "   - $file"

    # Update comment
    sed -i.bak 's|// ScoreExtensions of the Score plugin\.|// ScoreNormalizer of the Score plugin.|g' "$file"

    # Update method signature and return type
    sed -i.bak 's/func (.*) ScoreExtensions() framework\.ScoreExtensions {/&/; s/framework\.ScoreExtensions/framework.ScoreNormalizer/g' "$file"

    # More precise method replacement
    sed -i.bak 's/func (\([^)]*\)) ScoreExtensions() framework\.ScoreExtensions/func (\1) ScoreNormalizer() framework.ScoreNormalizer/g' "$file"
done

# ============================================================
# 5. Test Files
# ============================================================
echo "5. Updating test files..."

TEST_FILES=(
    "pkg/scheduler/framework/runtime/framework_test.go"
    "pkg/scheduler/schedule_one_test.go"
    "pkg/scheduler/testing/framework/fake_plugins.go"
    "pkg/scheduler/testing/framework/fake_extender.go"
    "pkg/scheduler/framework/plugins/tainttoleration/taint_toleration_test.go"
    "pkg/scheduler/framework/plugins/nodeaffinity/node_affinity_test.go"
    "pkg/scheduler/framework/plugins/interpodaffinity/scoring_test.go"
)

for file in "${TEST_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "   - $file"

        # Update all occurrences
        sed -i.bak 's/ScoreExtensions/ScoreNormalizer/g' "$file"
        sed -i.bak 's/\.ScoreNormalizer()\s*==\s*nil/\.ScoreNormalizer() == nil/g' "$file"
    fi
done

# ============================================================
# Cleanup and Verification
# ============================================================
echo ""
echo "Refactoring completed!"
echo ""
echo "Cleaning up backup files..."
find pkg/scheduler -name "*.bak" -delete
rm -f /tmp/interface_changes.sed

echo ""
echo "Verifying changes..."
echo "Remaining 'ScoreExtensions' references (should be none):"
grep -r "ScoreExtensions" pkg/scheduler --include="*.go" || echo "✓ No 'ScoreExtensions' references found"

echo ""
echo "Remaining 'ScoreExtensionNormalize' references (should be none):"
grep -r "ScoreExtensionNormalize" pkg/scheduler --include="*.go" || echo "✓ No 'ScoreExtensionNormalize' references found"

echo ""
echo "New 'ScoreNormalizer' references (should be many):"
NORMALIZER_COUNT=$(grep -r "ScoreNormalizer" pkg/scheduler --include="*.go" | wc -l)
echo "✓ Found $NORMALIZER_COUNT references to 'ScoreNormalizer'"

echo ""
echo "Refactoring verification complete!"
