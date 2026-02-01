#!/usr/bin/env python3
"""
Strip documentation from Kubernetes source files to create undocumented versions.

This script supports two modes:

1. FULL STRIP: Remove all documentation from the entire repository
   - Use for creating a fully undocumented fork to index in Sourcegraph

2. SURGICAL STRIP (Recommended): Remove docs only from target packages
   - Preserves related context elsewhere in the repo
   - Tests MCP's ability to discover related documentation
   - Use --target-only with --packages to strip specific packages

Removes:
- doc.go files
- README.md files in pkg/ directories
- Package-level documentation comments

Usage:
    # Full strip (for indexing a stripped fork)
    python strip_k8s_docs.py --source /path/to/kubernetes --output /path/to/output

    # Surgical strip (recommended for benchmarking)
    python strip_k8s_docs.py --source /path/to/kubernetes --output /path/to/output \
        --packages pkg/scheduler/framework/plugins/podtopologyspread \
        --target-only

Options:
    --source        Path to kubernetes source repository
    --output        Path to output directory for processed code
    --packages      Comma-separated list of packages to strip
    --target-only   Only strip specified packages (surgical mode)
    --preserve-api  Keep API documentation comments (default: false)
    --dry-run       Show what would be done without making changes
"""

import argparse
import os
import re
import shutil
from pathlib import Path
from typing import List, Set


def parse_args():
    parser = argparse.ArgumentParser(
        description="Strip documentation from Kubernetes source files"
    )
    parser.add_argument(
        "--source", required=True, help="Path to kubernetes source repository"
    )
    parser.add_argument("--output", required=True, help="Path to output directory")
    parser.add_argument(
        "--packages",
        default="",
        help="Comma-separated list of packages to strip (e.g., pkg/kubelet/cm,pkg/scheduler)",
    )
    parser.add_argument(
        "--target-only",
        action="store_true",
        help="Only strip specified packages, copy everything else unchanged (surgical mode)",
    )
    parser.add_argument(
        "--preserve-api",
        action="store_true",
        help="Preserve API documentation comments in staging/src/k8s.io/api",
    )
    parser.add_argument(
        "--preserve-structure",
        action="store_true",
        help="Preserve directory structure even for empty directories",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )
    return parser.parse_args()


# Files to remove completely
DOC_FILES_TO_REMOVE = {
    "doc.go",
    "README.md",
    "README",
    "DESIGN.md",
    "CONTRIBUTING.md",
}

# Directories to skip entirely
SKIP_DIRECTORIES = {
    ".git",
    "vendor",
    "third_party",
    "test",
    "hack",
    "docs",
    "examples",
    "_output",
    ".cache",
}

# File extensions to process for comment stripping
GO_EXTENSIONS = {".go"}


def should_skip_directory(path: Path) -> bool:
    """Check if directory should be skipped."""
    return any(part in SKIP_DIRECTORIES for part in path.parts)


def is_doc_file(filename: str) -> bool:
    """Check if file is a documentation file to be removed."""
    return filename in DOC_FILES_TO_REMOVE


def strip_package_comment(content: str) -> str:
    """
    Strip package-level documentation comment from Go file.

    Package comments appear immediately before the 'package' declaration
    and can be either // or /* */ style.
    """
    # Pattern to match package comment (multi-line /* */ style)
    # This matches everything from /* to */ immediately before 'package'
    block_comment_pattern = r"/\*[\s\S]*?\*/\s*(?=package\s)"
    content = re.sub(block_comment_pattern, "", content)

    # Pattern to match package comment (// style)
    # This matches consecutive // lines immediately before 'package'
    # But we need to preserve the copyright header

    # Find the package line
    package_match = re.search(r"^package\s+\w+", content, re.MULTILINE)
    if not package_match:
        return content

    package_pos = package_match.start()

    # Look for // comments right before package (excluding copyright)
    lines = content[:package_pos].split("\n")

    # Find where documentation comments start (after copyright block)
    # Copyright block typically ends with an empty line
    in_copyright = True
    doc_comment_start = -1

    for i, line in enumerate(lines):
        stripped = line.strip()
        if in_copyright:
            # Copyright block ends with first non-comment, non-empty line
            # or an empty line after comments
            if stripped == "" and i > 0:
                in_copyright = False
            elif not stripped.startswith("//") and stripped != "":
                in_copyright = False
        else:
            # After copyright, any // comments before package are doc comments
            if stripped.startswith("//") and doc_comment_start == -1:
                doc_comment_start = i

    # If we found doc comments, remove them
    if doc_comment_start != -1:
        # Keep everything up to doc comments, then skip to package
        pre_doc = "\n".join(lines[:doc_comment_start])
        content = pre_doc + "\n" + content[package_pos:]

    return content


def process_go_file(source_path: Path, dest_path: Path, dry_run: bool) -> None:
    """Process a Go file, optionally stripping documentation."""
    if dry_run:
        print(f"  Would process: {source_path}")
        return

    with open(source_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Strip package-level documentation
    modified_content = strip_package_comment(content)

    # Write to destination
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    with open(dest_path, "w", encoding="utf-8") as f:
        f.write(modified_content)


def copy_file(source_path: Path, dest_path: Path, dry_run: bool) -> None:
    """Copy a file without modification."""
    if dry_run:
        print(f"  Would copy: {source_path}")
        return

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, dest_path)


def process_directory(
    source_dir: Path,
    output_dir: Path,
    packages: Set[str],
    preserve_api: bool,
    target_only: bool,
    dry_run: bool,
) -> dict:
    """
    Process a directory, stripping documentation.

    If target_only is True (surgical mode):
      - Only strip docs from packages in the 'packages' set
      - Copy everything else unchanged (preserving related context)

    If target_only is False (full strip mode):
      - Strip docs from all packages (or filtered by 'packages')
    """
    stats = {
        "files_copied": 0,
        "files_modified": 0,
        "files_removed": 0,
        "dirs_processed": 0,
    }

    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        rel_path = root_path.relative_to(source_dir)
        rel_str = str(rel_path)

        # Skip certain directories
        if should_skip_directory(rel_path):
            dirs[:] = []  # Don't descend into this directory
            continue

        # Determine if this directory should be stripped
        should_strip = True

        if target_only and packages:
            # In surgical mode, only strip specified packages
            # Check if current path is inside a target package
            should_strip = any(rel_str.startswith(p) or rel_str == p for p in packages)
        elif packages:
            # In full strip mode with filter, skip non-matching packages
            if not any(
                rel_str.startswith(p) or p.startswith(rel_str) for p in packages
            ):
                if rel_str != ".":
                    # Copy without processing in surgical mode, skip in full mode
                    if target_only:
                        should_strip = False
                    else:
                        continue

        stats["dirs_processed"] += 1

        for filename in files:
            source_file = root_path / filename
            dest_file = output_dir / rel_path / filename

            # Skip test files
            if filename.endswith("_test.go"):
                continue

            if should_strip:
                # Remove documentation files from target packages
                if is_doc_file(filename):
                    stats["files_removed"] += 1
                    if dry_run:
                        print(f"  Would remove (doc): {source_file}")
                    continue

                # Process Go files (strip package comments)
                if source_file.suffix in GO_EXTENSIONS:
                    # Check if this is API directory that should be preserved
                    if preserve_api and "staging/src/k8s.io/api" in rel_str:
                        copy_file(source_file, dest_file, dry_run)
                        stats["files_copied"] += 1
                    else:
                        process_go_file(source_file, dest_file, dry_run)
                        stats["files_modified"] += 1
                else:
                    copy_file(source_file, dest_file, dry_run)
                    stats["files_copied"] += 1
            else:
                # Copy files unchanged (preserving related context)
                copy_file(source_file, dest_file, dry_run)
                stats["files_copied"] += 1

    return stats


def main():
    args = parse_args()

    source_dir = Path(args.source).resolve()
    output_dir = Path(args.output).resolve()

    if not source_dir.exists():
        print(f"Error: Source directory does not exist: {source_dir}")
        return 1

    # Parse packages filter
    packages = set()
    if args.packages:
        packages = set(p.strip() for p in args.packages.split(","))
        print(f"Target packages: {packages}")

    mode = "surgical (target-only)" if args.target_only else "full strip"
    print(f"Mode: {mode}")
    print(f"Source: {source_dir}")
    print(f"Output: {output_dir}")
    print(f"Dry run: {args.dry_run}")
    print()

    if args.target_only and not packages:
        print("Warning: --target-only specified but no --packages provided.")
        print("         This will copy everything unchanged.")

    if not args.dry_run:
        output_dir.mkdir(parents=True, exist_ok=True)

    stats = process_directory(
        source_dir,
        output_dir,
        packages,
        args.preserve_api,
        args.target_only,
        args.dry_run,
    )

    print()
    print("Summary:")
    print(f"  Mode: {mode}")
    print(f"  Directories processed: {stats['dirs_processed']}")
    print(f"  Files copied (unchanged): {stats['files_copied']}")
    print(f"  Files modified (stripped): {stats['files_modified']}")
    print(f"  Files removed (documentation): {stats['files_removed']}")

    if args.target_only:
        print()
        print("Surgical strip complete.")
        print(
            "Related context (KEPs, framework docs, API docs) preserved for MCP discovery."
        )

    return 0


if __name__ == "__main__":
    exit(main())
