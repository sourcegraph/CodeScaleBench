#!/usr/bin/env python3
"""
Extract ground truth documentation from Kubernetes repositories.

This script extracts existing documentation to serve as ground truth for
evaluating agent-generated documentation:
- doc.go files from specified packages
- KEP (Kubernetes Enhancement Proposal) content
- API documentation from staging/src/k8s.io/api
- README files from package directories

Usage:
    python extract_ground_truth.py --source /path/to/kubernetes --task pkg-doc-001 --output ./ground_truth

Options:
    --source      Path to kubernetes source repository
    --keps        Path to kubernetes/enhancements repository (for KEPs)
    --task        Task ID to extract ground truth for
    --output      Output directory for extracted content
    --format      Output format: markdown, json, or raw (default: markdown)
"""

import argparse
import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Any


# Task configuration: maps task IDs to their ground truth sources
# All active benchmark tasks use actual doc.go files from kubernetes/kubernetes master
TASK_GROUND_TRUTH_CONFIG = {
    # Active benchmark tasks (all ground truth = actual doc.go from k8s repo)
    "pkg-doc-001": {
        "type": "package",
        "sources": ["pkg/kubelet/cm/doc.go"],
        "description": "Container Manager package documentation",
    },
    "client-go-doc-001": {
        "type": "package",
        "sources": ["staging/src/k8s.io/client-go/doc.go"],
        "description": "Client-Go library documentation",
    },
    "applyconfig-doc-001": {
        "type": "package",
        "sources": ["staging/src/k8s.io/client-go/applyconfigurations/doc.go"],
        "description": "Apply Configurations package documentation",
    },
    "apiserver-doc-001": {
        "type": "package",
        "sources": ["staging/src/k8s.io/apiserver/doc.go"],
        "description": "API Server library documentation",
    },
    "fairqueuing-doc-001": {
        "type": "package",
        "sources": [
            "staging/src/k8s.io/apiserver/pkg/util/flowcontrol/fairqueuing/queueset/doc.go"
        ],
        "description": "Fair Queuing QueueSet package documentation",
    },
    # Legacy / extended tasks (kept for reference, not in active benchmark)
    "pkg-doc-002": {
        "type": "package",
        "sources": ["pkg/scheduler/framework/doc.go"],
        "description": "Scheduler Framework package documentation",
    },
    "pkg-doc-003": {
        "type": "package",
        "sources": ["pkg/controller/doc.go"],
        "description": "Controller package documentation",
    },
    "pkg-doc-004": {
        "type": "package",
        "sources": ["pkg/kubelet/volumemanager/doc.go"],
        "description": "Volume Manager package documentation",
    },
}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Extract ground truth documentation from Kubernetes repositories"
    )
    parser.add_argument(
        "--source", required=True, help="Path to kubernetes/kubernetes repository"
    )
    parser.add_argument(
        "--keps", help="Path to kubernetes/enhancements repository (for KEPs)"
    )
    parser.add_argument(
        "--task", required=True, help="Task ID to extract ground truth for"
    )
    parser.add_argument(
        "--output", required=True, help="Output directory for extracted content"
    )
    parser.add_argument(
        "--format",
        choices=["markdown", "json", "raw"],
        default="markdown",
        help="Output format",
    )
    parser.add_argument(
        "--list-tasks", action="store_true", help="List all available tasks"
    )
    return parser.parse_args()


def extract_doc_go_content(file_path: Path) -> Optional[str]:
    """Extract documentation from a doc.go file."""
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Extract the package-level comment
    # This is typically a /* */ block before the package declaration
    block_match = re.search(r"/\*\s*([\s\S]*?)\*/", content)
    if block_match:
        doc_content = block_match.group(1).strip()
        # Clean up leading * from each line if present
        lines = doc_content.split("\n")
        cleaned_lines = []
        for line in lines:
            # Remove leading whitespace and asterisks
            cleaned = re.sub(r"^\s*\*\s?", "", line)
            cleaned_lines.append(cleaned)
        return "\n".join(cleaned_lines)

    # Try // style comments
    lines = content.split("\n")
    doc_lines = []
    in_doc = False

    for line in lines:
        if line.strip().startswith("// Package ") or (
            in_doc and line.strip().startswith("//")
        ):
            in_doc = True
            doc_lines.append(line.strip()[3:])  # Remove "// "
        elif line.strip().startswith("package "):
            break
        elif in_doc and not line.strip():
            doc_lines.append("")

    return "\n".join(doc_lines) if doc_lines else None


def extract_kep_content(file_path: Path, sections: List[str] = None) -> Optional[str]:
    """Extract content from a KEP README.md file."""
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    if sections is None:
        return content

    # Extract specific sections
    extracted = []
    current_section = None
    current_content = []

    for line in content.split("\n"):
        # Check for header
        header_match = re.match(r"^(#{1,6})\s+(.+)", line)
        if header_match:
            # Save previous section if we were tracking it
            if current_section and current_section.lower() in [
                s.lower() for s in sections
            ]:
                extracted.append(f"## {current_section}\n" + "\n".join(current_content))

            current_section = header_match.group(2)
            current_content = []
        else:
            current_content.append(line)

    # Don't forget last section
    if current_section and current_section.lower() in [s.lower() for s in sections]:
        extracted.append(f"## {current_section}\n" + "\n".join(current_content))

    return "\n\n".join(extracted) if extracted else content


def extract_readme_content(file_path: Path) -> Optional[str]:
    """Extract content from a README.md file."""
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()


def extract_code_patterns(file_path: Path, pattern: str) -> Optional[str]:
    """Extract code with specific documentation patterns."""
    if not file_path.exists():
        return None

    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()

    # For feature gate files, extract the feature definitions with their comments
    if "feature_gate" in pattern.lower() or "feature gate" in pattern.lower():
        # Find feature gate constants with their documentation
        feature_pattern = (
            r'(//[^\n]*\n)*\s*(\w+)\s*featuregate\.Feature\s*=\s*"([^"]+)"'
        )
        matches = re.findall(feature_pattern, content)

        if matches:
            result_lines = ["# Feature Gate Definitions\n"]
            for comments, name, value in matches:
                result_lines.append(f"## {name}")
                result_lines.append(f"Value: `{value}`")
                if comments:
                    result_lines.append("Documentation:")
                    result_lines.append(comments.strip())
                result_lines.append("")
            return "\n".join(result_lines)

    return content


def format_output(
    task_config: Dict[str, Any], extracted_content: Dict[str, str], output_format: str
) -> str:
    """Format the extracted content for output."""
    if output_format == "json":
        return json.dumps(
            {"task_config": task_config, "content": extracted_content}, indent=2
        )

    elif output_format == "raw":
        return "\n\n---\n\n".join(extracted_content.values())

    else:  # markdown
        lines = [
            f"# Ground Truth: {task_config['description']}",
            "",
            f"**Type:** {task_config['type']}",
            f"**Sources:** {', '.join(task_config['sources'])}",
            "",
        ]

        if "kep_id" in task_config:
            lines.append(f"**KEP:** {task_config['kep_id']}")
            lines.append("")

        lines.append("---")
        lines.append("")

        for source, content in extracted_content.items():
            lines.append(f"## Source: `{source}`")
            lines.append("")
            lines.append(content)
            lines.append("")

        return "\n".join(lines)


def main():
    args = parse_args()

    if args.list_tasks:
        print("Available tasks:")
        for task_id, config in sorted(TASK_GROUND_TRUTH_CONFIG.items()):
            print(f"  {task_id}: {config['description']} ({config['type']})")
        return 0

    if args.task not in TASK_GROUND_TRUTH_CONFIG:
        print(f"Error: Unknown task '{args.task}'")
        print("Use --list-tasks to see available tasks")
        return 1

    task_config = TASK_GROUND_TRUTH_CONFIG[args.task]
    source_dir = Path(args.source).resolve()
    keps_dir = Path(args.keps).resolve() if args.keps else None
    output_dir = Path(args.output).resolve()

    extracted_content = {}

    for source in task_config["sources"]:
        # Determine which repository to use
        if source.startswith("keps/"):
            if keps_dir is None:
                print(f"Warning: KEP source '{source}' requires --keps argument")
                continue
            file_path = keps_dir / source.replace("keps/", "")
        else:
            file_path = source_dir / source

        print(f"Extracting from: {file_path}")

        # Extract based on type
        if task_config["type"] == "package":
            if source.endswith("doc.go"):
                content = extract_doc_go_content(file_path)
            else:
                content = extract_readme_content(file_path)
        elif task_config["type"] == "kep":
            content = extract_kep_content(file_path)
        elif task_config["type"] == "code_pattern":
            content = extract_code_patterns(file_path, task_config.get("pattern", ""))
        elif task_config["type"] == "changelog":
            content = extract_readme_content(file_path)
        else:
            content = extract_readme_content(file_path)

        if content:
            extracted_content[source] = content
        else:
            print(f"  Warning: Could not extract content from {source}")

    if not extracted_content:
        print("Error: No content extracted from any source")
        return 1

    # Format and write output
    output_dir.mkdir(parents=True, exist_ok=True)

    formatted = format_output(task_config, extracted_content, args.format)

    ext = {"markdown": ".md", "json": ".json", "raw": ".txt"}[args.format]

    output_file = output_dir / f"ground_truth{ext}"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(formatted)

    print(f"\nGround truth written to: {output_file}")
    print(f"Extracted from {len(extracted_content)} source(s)")

    return 0


if __name__ == "__main__":
    exit(main())
