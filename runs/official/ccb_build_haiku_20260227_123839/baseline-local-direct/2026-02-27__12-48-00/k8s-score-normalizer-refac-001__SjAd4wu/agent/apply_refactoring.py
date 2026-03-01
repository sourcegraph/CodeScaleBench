#!/usr/bin/env python3
"""
ScoreExtensions to ScoreNormalizer Refactoring Script
This Python script applies all necessary changes for the refactoring.
"""

import os
import re
import sys
from pathlib import Path

def replace_in_file(file_path, replacements):
    """Apply multiple regex replacements to a file."""
    try:
        with open(file_path, 'r') as f:
            content = f.read()
    except Exception as e:
        print(f"  ✗ Failed to read {file_path}: {e}")
        return False

    original_content = content

    for pattern, replacement in replacements:
        content = re.sub(pattern, replacement, content)

    if content == original_content:
        return None  # No changes

    try:
        with open(file_path, 'w') as f:
            f.write(content)
        return True
    except Exception as e:
        print(f"  ✗ Failed to write {file_path}: {e}")
        return False

def main():
    os.chdir('/workspace')

    print("Starting ScoreExtensions to ScoreNormalizer refactoring...")
    print()

    # ============================================================
    # 1. Core Interface Definition
    # ============================================================
    print("1. Updating pkg/scheduler/framework/interface.go...")

    interface_replacements = [
        (r'// ScoreExtensions is an interface for Score extended functionality\.',
         '// ScoreNormalizer is an interface for normalizing scores produced by a Score plugin.'),
        (r'^type ScoreExtensions interface \{',
         'type ScoreNormalizer interface {'),
        (r'// ScoreExtensions returns a ScoreExtensions interface if it implements one, or nil if does not\.',
         '// ScoreNormalizer returns a ScoreNormalizer interface if it implements one, or nil if does not.'),
        (r'ScoreExtensions\(\) ScoreExtensions',
         'ScoreNormalizer() ScoreNormalizer'),
    ]

    result = replace_in_file('pkg/scheduler/framework/interface.go', interface_replacements)
    if result is True:
        print("  ✓ Updated interface.go")
    elif result is False:
        sys.exit(1)

    # ============================================================
    # 2. Metrics Definition
    # ============================================================
    print("2. Updating pkg/scheduler/metrics/metrics.go...")

    metrics_replacements = [
        (r'ScoreExtensionNormalize\s*=\s*"ScoreExtensionNormalize"',
         'ScoreNormalize              = "ScoreNormalize"'),
    ]

    result = replace_in_file('pkg/scheduler/metrics/metrics.go', metrics_replacements)
    if result is True:
        print("  ✓ Updated metrics.go")
    elif result is False:
        sys.exit(1)

    # ============================================================
    # 3. Runtime Framework
    # ============================================================
    print("3. Updating pkg/scheduler/framework/runtime/framework.go...")

    framework_replacements = [
        (r'if pl\.ScoreExtensions\(\) == nil',
         'if pl.ScoreNormalizer() == nil'),
        (r'pl\.ScoreExtensions\(\)\.NormalizeScore',
         'pl.ScoreNormalizer().NormalizeScore'),
        (r'metrics\.ScoreExtensionNormalize',
         'metrics.ScoreNormalize'),
    ]

    result = replace_in_file('pkg/scheduler/framework/runtime/framework.go', framework_replacements)
    if result is True:
        print("  ✓ Updated framework.go")
    elif result is False:
        sys.exit(1)

    # ============================================================
    # 4. Plugin Implementations
    # ============================================================
    print("4. Updating plugin implementations...")

    plugin_files = [
        "pkg/scheduler/framework/plugins/tainttoleration/taint_toleration.go",
        "pkg/scheduler/framework/plugins/interpodaffinity/scoring.go",
        "pkg/scheduler/framework/plugins/podtopologyspread/scoring.go",
        "pkg/scheduler/framework/plugins/nodeaffinity/node_affinity.go",
        "pkg/scheduler/framework/plugins/volumebinding/volume_binding.go",
        "pkg/scheduler/framework/plugins/noderesources/balanced_allocation.go",
        "pkg/scheduler/framework/plugins/noderesources/fit.go",
        "pkg/scheduler/framework/plugins/imagelocality/image_locality.go",
    ]

    plugin_replacements = [
        (r'// ScoreExtensions of the Score plugin\.',
         '// ScoreNormalizer of the Score plugin.'),
        (r'func \(([^)]*)\) ScoreExtensions\(\) framework\.ScoreExtensions',
         r'func (\1) ScoreNormalizer() framework.ScoreNormalizer'),
    ]

    for file_path in plugin_files:
        if Path(file_path).exists():
            result = replace_in_file(file_path, plugin_replacements)
            if result is True:
                print(f"   ✓ {file_path}")
            elif result is None:
                print(f"   - {file_path} (no changes needed)")
            elif result is False:
                sys.exit(1)
        else:
            print(f"   ⊘ {file_path} (file not found)")

    # ============================================================
    # 5. Test Files
    # ============================================================
    print("5. Updating test files...")

    test_files = [
        "pkg/scheduler/framework/runtime/framework_test.go",
        "pkg/scheduler/schedule_one_test.go",
        "pkg/scheduler/testing/framework/fake_plugins.go",
        "pkg/scheduler/testing/framework/fake_extender.go",
        "pkg/scheduler/framework/plugins/tainttoleration/taint_toleration_test.go",
        "pkg/scheduler/framework/plugins/nodeaffinity/node_affinity_test.go",
        "pkg/scheduler/framework/plugins/interpodaffinity/scoring_test.go",
    ]

    test_replacements = [
        (r'ScoreExtensions', 'ScoreNormalizer'),
    ]

    for file_path in test_files:
        if Path(file_path).exists():
            result = replace_in_file(file_path, test_replacements)
            if result is True:
                print(f"   ✓ {file_path}")
            elif result is None:
                print(f"   - {file_path} (no changes needed)")
            elif result is False:
                sys.exit(1)
        else:
            print(f"   ⊘ {file_path} (file not found)")

    # ============================================================
    # Verification
    # ============================================================
    print()
    print("Verifying refactoring...")

    # Count remaining bad references
    old_refs = 0
    old_metric_refs = 0
    new_refs = 0

    for root, dirs, files in os.walk('pkg/scheduler'):
        # Skip testdata and vendor directories
        dirs[:] = [d for d in dirs if d not in ('testdata', 'vendor', '.git')]

        for file in files:
            if file.endswith('.go'):
                file_path = os.path.join(root, file)
                try:
                    with open(file_path, 'r') as f:
                        content = f.read()
                        old_refs += len(re.findall(r'\bScoreExtensions\b', content))
                        old_metric_refs += len(re.findall(r'ScoreExtensionNormalize', content))
                        new_refs += len(re.findall(r'\bScoreNormalizer\b', content))
                except:
                    pass

    print()
    if old_refs == 0 and old_metric_refs == 0:
        print("✓ All 'ScoreExtensions' references have been renamed")
        print("✓ All 'ScoreExtensionNormalize' references have been renamed")
    else:
        print(f"✗ WARNING: Found {old_refs} remaining 'ScoreExtensions' references")
        print(f"✗ WARNING: Found {old_metric_refs} remaining 'ScoreExtensionNormalize' references")

    print(f"✓ Found {new_refs} 'ScoreNormalizer' references")

    print()
    print("Refactoring completed successfully!")
    print()
    print("Next steps:")
    print("1. Run tests to verify the changes: go test ./pkg/scheduler/framework/...")
    print("2. Review the git diff: git diff")
    print("3. Commit the changes")

if __name__ == '__main__':
    main()
