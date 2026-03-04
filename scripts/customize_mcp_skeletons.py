#!/usr/bin/env python3
"""Batch-customize generated MCP-unique task skeletons.

Adds missing files required by the reference task pattern:
- environment/Dockerfile.artifact_only
- instruction_mcp.md
- tests/test.sh
- tests/sgonly_verifier_wrapper.sh
- Fixes SOURCEGRAPH_REPOS + clone manifest in Dockerfile.sg_only
- Fixes .go template bug in instruction.md for non-Go tasks
"""

import json
import os
import shutil
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# New task IDs to customize (all generated skeletons)
NEW_TASK_IDS = [101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112,
                113, 114, 115, 116, 117, 118, 119, 120,
                121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132,
                133, 134, 135, 136, 137, 138, 139, 140, 141]

# Reference task for copying shared files
REFERENCE_TASK = os.path.join(PROJECT_ROOT, "benchmarks/csb_org_crossrepo_tracing/ccx-dep-trace-001")

# Tasks that support both artifact and direct verification modes
DUAL_MODE_TASK_IDS = {81, 82, 83, 113, 114, 115, 116, 117, 118, 119, 120, 122, 127}

# Map adapted task IDs to their parent SDLC task paths (for copying direct verifiers)
PARENT_TASK_MAP = {
    113: "ccb_debug/grafana-table-panel-regression-001",
    114: "ccb_refactor/kafka-batch-accumulator-refac-001",
    115: "ccb_secure/django-cross-team-boundary-001",
    116: "ccb_design/k8s-typemeta-dep-chain-001",
    117: "ccb_refactor/k8s-score-normalizer-refac-001",
    118: "ccb_secure/django-repo-scoped-access-001",
    119: "ccb_feature/flink-pricing-window-feat-001",
    120: "ccb_refactor/strata-fx-european-refac-001",
}

# Repo set definitions: sg_repos (for artifact_only/MCP search), clone_repos (for sg_only manifest)
REPO_SETS = {
    "apache-kafka-ecosystem": {
        "sg_repos": [
            "sg-evals/kafka--0753c489",
            "sg-evals/flink--0cc95fcc",
            "sg-evals/camel--1006f047",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/kafka--0753c489", "target_dir": "kafka"},
            {"mirror": "sg-evals/flink--0cc95fcc", "target_dir": "flink"},
            {"mirror": "sg-evals/camel--1006f047", "target_dir": "camel"},
        ],
        "language": "Java",
        "file_ext": ".java",
    },
    "envoy-service-mesh": {
        "sg_repos": [
            "sg-evals/envoy--v1.31.2",
            "sg-evals/data-plane-api--84e84367",
            "sg-evals/go-control-plane--71637ad6",
            "sg-evals/grpc--957dba5e",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/envoy--v1.31.2", "target_dir": "envoy"},
            {"mirror": "sg-evals/data-plane-api--84e84367", "target_dir": "data-plane-api"},
            {"mirror": "sg-evals/go-control-plane--71637ad6", "target_dir": "go-control-plane"},
            {"mirror": "sg-evals/grpc--957dba5e", "target_dir": "grpc"},
        ],
        "language": "C++",
        "file_ext": ".cpp",
    },
    "rust-systems": {
        "sg_repos": [
            "sg-evals/rust--01f6ddf7",
            "sg-evals/servo--be6a2f99",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/rust--01f6ddf7", "target_dir": "rust"},
            {"mirror": "sg-evals/servo--be6a2f99", "target_dir": "servo"},
        ],
        "language": "Rust",
        "file_ext": ".rs",
    },
    "kubernetes-ecosystem": {
        # For artifact_only, use the logical SG names (indexed under these names)
        "sg_repos": [
            "sg-evals/kubernetes-kubernetes",
            "sg-evals/kubernetes-client-go",
            "sg-evals/kubernetes-api",
            "sg-evals/etcd-io-etcd",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/kubernetes--v1.32.0", "target_dir": "kubernetes"},
            {"mirror": "sg-evals/client-go--v0.32.0", "target_dir": "client-go"},
            {"mirror": "sg-evals/api--v0.32.0", "target_dir": "api"},
            {"mirror": "sg-evals/etcd-io-etcd", "target_dir": "etcd"},
        ],
        "language": "Go",
        "file_ext": ".go",
    },
    "compiler-toolchain": {
        "sg_repos": [
            "sg-evals/llvm-project--a8f3c97d",
            "sg-evals/gcc--96dfb333",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/llvm-project--a8f3c97d", "target_dir": "llvm-project"},
            {"mirror": "sg-evals/gcc--96dfb333", "target_dir": "gcc"},
        ],
        "language": "C++",
        "file_ext": ".cpp",
    },
    "mozilla-firefox": {
        "sg_repos": [
            "sg-evals/firefox--871325b8",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/firefox--871325b8", "target_dir": "firefox"},
        ],
        "language": "C++",
        "file_ext": ".cpp",
    },
    "java-platform": {
        "sg_repos": [
            "sg-evals/jdk--742e735d",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/jdk--742e735d", "target_dir": "jdk"},
        ],
        "language": "Java",
        "file_ext": ".java",
    },
    "chromium-browser": {
        "sg_repos": [
            "sg-evals/chromium--2d05e315",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/chromium--2d05e315", "target_dir": "chromium"},
        ],
        "language": "C++",
        "file_ext": ".cpp",
    },
    "android-platform": {
        "sg_repos": [
            "sg-evals/android-frameworks-base--d41da232",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/android-frameworks-base--d41da232", "target_dir": "frameworks-base"},
        ],
        "language": "Java",
        "file_ext": ".java",
    },
    "libreoffice-desktop": {
        "sg_repos": [
            "sg-evals/libreoffice-core--9c8b85f3",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/libreoffice-core--9c8b85f3", "target_dir": "core"},
        ],
        "language": "C++",
        "file_ext": ".cpp",
    },
    "arangodb-database": {
        "sg_repos": [
            "sg-evals/arangodb--a5cca0b8",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/arangodb--a5cca0b8", "target_dir": "arangodb"},
        ],
        "language": "C++",
        "file_ext": ".cpp",
    },
    "grafana-observability": {
        "sg_repos": [
            "sg-evals/grafana--26d36ec",
            "sg-evals/grafana-loki",
            "sg-evals/grafana-mimir",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/grafana--26d36ec", "target_dir": "grafana"},
            {"mirror": "sg-evals/grafana-loki", "target_dir": "loki"},
            {"mirror": "sg-evals/grafana-mimir", "target_dir": "mimir"},
        ],
        "language": "Go",
        "file_ext": ".go",
    },
    "django-web-framework": {
        "sg_repos": [
            "sg-evals/django--674eda1c",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/django--674eda1c", "target_dir": "django"},
        ],
        "language": "Python",
        "file_ext": ".py",
    },
    "strata-finance": {
        "sg_repos": [
            "sg-evals/Strata--66225ca9",
        ],
        "clone_repos": [
            {"mirror": "sg-evals/Strata--66225ca9", "target_dir": "Strata"},
        ],
        "language": "Java",
        "file_ext": ".java",
    },
}

# Map use_case_id -> task directory and repo_set_id
def load_registry():
    path = os.path.join(PROJECT_ROOT, "configs/use_case_registry.json")
    with open(path) as f:
        data = json.load(f)
    return {uc["use_case_id"]: uc for uc in data["use_cases"]}


def find_task_dir(use_case_id, registry):
    """Find the task directory for a given use case ID."""
    uc = registry[use_case_id]
    suite = uc["mcp_suite"]
    task_id = uc.get("task_id", "")

    # Search benchmarks directory for the task
    benchmarks_dir = os.path.join(PROJECT_ROOT, "benchmarks")
    suite_dir = os.path.join(benchmarks_dir, suite)
    if not os.path.isdir(suite_dir):
        return None

    for entry in os.listdir(suite_dir):
        task_path = os.path.join(suite_dir, entry)
        toml_path = os.path.join(task_path, "task.toml")
        if os.path.isfile(toml_path):
            with open(toml_path) as f:
                content = f.read()
            if f'use_case_id = {use_case_id}' in content:
                return task_path
    return None


def generate_artifact_only_dockerfile(task_dir, sg_repos):
    """Create Dockerfile.artifact_only with SOURCEGRAPH_REPOS env var."""
    task_name = os.path.basename(task_dir)
    repos_str = ",".join(sg_repos)

    content = f"""# {task_name} — artifact_only variant
# No local repo clone — agent uses Sourcegraph MCP exclusively for code access.
# Agent produces answer.json artifact; verifier scores the artifact.

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV SOURCEGRAPH_REPOS="{repos_str}"

RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    ca-certificates \\
    python3 \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Empty workspace — agent discovers code via MCP tools only
RUN git init && \\
    git config user.email "agent@example.com" && \\
    git config user.name "Agent" && \\
    git config --global safe.directory '*'

# Create log directories
RUN mkdir -p /logs/agent /logs/verifier

# Mark artifact-only mode — verifiers and eval scripts check this flag
RUN touch /tmp/.artifact_only_mode

ENTRYPOINT []
"""
    path = os.path.join(task_dir, "environment", "Dockerfile.artifact_only")
    with open(path, "w") as f:
        f.write(content)
    return path


def update_sg_only_dockerfile(task_dir, sg_repos, clone_repos):
    """Add SOURCEGRAPH_REPOS env var and clone manifest to Dockerfile.sg_only."""
    path = os.path.join(task_dir, "environment", "Dockerfile.sg_only")
    with open(path) as f:
        content = f.read()

    repos_str = ",".join(sg_repos)
    task_name = os.path.basename(task_dir)

    # Build clone manifest as compact JSON
    manifest = {
        "workdir": "/workspace",
        "repos": clone_repos,
    }
    manifest_json = json.dumps(manifest, separators=(",", ":"))

    # Check if SOURCEGRAPH_REPOS already exists
    if "SOURCEGRAPH_REPOS" in content:
        return path  # Already customized

    # Insert SOURCEGRAPH_REPOS after DEBIAN_FRONTEND
    content = content.replace(
        "ENV DEBIAN_FRONTEND=noninteractive",
        f'ENV DEBIAN_FRONTEND=noninteractive\nENV SOURCEGRAPH_REPOS="{repos_str}"',
    )

    # Add clone manifest before ENTRYPOINT
    manifest_line = f"RUN echo '{manifest_json}' > /tmp/.sg_only_clone_manifest.json\n\n"
    content = content.replace("ENTRYPOINT []", manifest_line + "ENTRYPOINT []")

    with open(path, "w") as f:
        f.write(content)
    return path


def create_test_sh(task_dir):
    """Create tests/test.sh (Harbor compatibility wrapper)."""
    content = """#!/bin/bash
# test.sh — Harbor compatibility wrapper
# Harbor requires tests/test.sh for task discovery (TaskPaths.is_valid() check).
# The actual evaluation logic lives in eval.sh (SWE-Factory exit-code-first pattern).

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

exec bash "$(dirname "$0")/eval.sh" "$@"
"""
    path = os.path.join(task_dir, "tests", "test.sh")
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o755)
    return path


def create_dual_mode_test_sh(task_dir):
    """Create tests/test.sh that dispatches between artifact and direct mode."""
    content = """#!/bin/bash
# test.sh — Dual-mode verifier dispatcher
# Artifact mode (.artifact_only_mode exists): run eval.sh (oracle scoring)
# Direct mode  (default / .sg_only_mode):    run direct_verifier.sh

set -e

# sg_only_env: restore full repo before verification (no-op for regular runs)
[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh

if [ -f /tmp/.artifact_only_mode ]; then
    echo "[test.sh] Artifact mode detected -> running eval.sh (oracle verifier)"
    exec bash "$(dirname "$0")/eval.sh" "$@"
else
    echo "[test.sh] Direct mode -> running direct_verifier.sh"
    exec bash "$(dirname "$0")/direct_verifier.sh" "$@"
fi
"""
    path = os.path.join(task_dir, "tests", "test.sh")
    with open(path, "w") as f:
        f.write(content)
    os.chmod(path, 0o755)
    return path


def copy_parent_verifier(task_dir, parent_rel_path):
    """Copy direct verifier files from parent SDLC task.

    Copies the parent's test.sh as direct_verifier.sh (stripping wrapper/artifact
    lines since the dispatcher handles those), plus ground_truth.json and
    verifier_lib.sh if they exist.
    """
    parent_dir = os.path.join(PROJECT_ROOT, "benchmarks", parent_rel_path)
    parent_tests = os.path.join(parent_dir, "tests")
    task_tests = os.path.join(task_dir, "tests")
    copied = []

    # Copy parent test.sh -> direct_verifier.sh (strip wrapper/artifact lines)
    parent_test_sh = os.path.join(parent_tests, "test.sh")
    if os.path.exists(parent_test_sh):
        with open(parent_test_sh) as f:
            content = f.read()
        # Strip the sg_only_wrapper and artifact_only sourcing lines
        # (the dual-mode test.sh dispatcher handles those before calling us)
        lines = content.split("\n")
        filtered = []
        in_artifact_block = False
        for line in lines:
            stripped = line.strip()
            # Skip wrapper sourcing (handled by dispatcher)
            if "sgonly_verifier_wrapper.sh" in stripped:
                continue
            # Detect start of artifact_only_mode if/source/fi block
            if ".artifact_only_mode" in stripped and "answer_json_verifier_lib" in stripped:
                in_artifact_block = True
                continue
            if stripped.startswith("if") and ".artifact_only_mode" in stripped:
                in_artifact_block = True
                continue
            if in_artifact_block:
                if stripped == "source /tests/answer_json_verifier_lib.sh":
                    continue
                if stripped == "fi":
                    in_artifact_block = False
                    continue
                # Any other line inside the block — also skip
                continue
            # Also skip the "# Artifact mode:" comment that precedes the block
            if stripped == "# Artifact mode: parse answer.json, extract analysis text, apply diffs":
                continue
            filtered.append(line)
        direct_content = "\n".join(filtered)

        dst = os.path.join(task_tests, "direct_verifier.sh")
        with open(dst, "w") as f:
            f.write(direct_content)
        os.chmod(dst, 0o755)
        copied.append("direct_verifier.sh")

    # Copy supporting files if they exist
    for fname in ["ground_truth.json", "verifier_lib.sh", "answer_json_verifier_lib.sh"]:
        src = os.path.join(parent_tests, fname)
        if os.path.exists(src):
            dst = os.path.join(task_tests, fname)
            if not os.path.exists(dst):
                shutil.copy2(src, dst)
                if fname.endswith(".sh"):
                    os.chmod(dst, 0o755)
                copied.append(fname)

    return copied


def copy_sgonly_wrapper(task_dir):
    """Copy sgonly_verifier_wrapper.sh from reference task."""
    src = os.path.join(REFERENCE_TASK, "tests", "sgonly_verifier_wrapper.sh")
    dst = os.path.join(task_dir, "tests", "sgonly_verifier_wrapper.sh")
    shutil.copy2(src, dst)
    os.chmod(dst, 0o755)
    return dst


def generate_instruction_mcp(task_dir, sg_repos, registry_entry):
    """Create instruction_mcp.md with MCP preamble + task content."""
    # Read the task instruction
    instruction_path = os.path.join(task_dir, "instruction.md")
    with open(instruction_path) as f:
        task_content = f.read()

    # Build repo list for MCP header
    repo_lines = []
    for repo in sg_repos:
        repo_lines.append(
            f"- `github.com/{repo}` — use `repo:^github.com/{repo}$` filter"
        )
    repo_list = "\n".join(repo_lines)
    repo_names = ", ".join(f"`github.com/{r}`" for r in sg_repos)

    content = f"""# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repositories (version-pinned mirrors):**

{repo_list}

Scope ALL keyword_search/nls_search queries to these repos.
Use the repo name as the `repo` parameter for read_file/go_to_definition/find_references.


## Required Workflow

1. **Search first** — Use MCP tools to find relevant files and understand existing patterns
2. **Read remotely** — Use `sg_read_file` to read full file contents from Sourcegraph
3. **Edit locally** — Use Edit, Write, and Bash to create or modify files in your working directory
4. **Verify locally** — Run tests with Bash to check your changes

## Tool Selection

| Goal | Tool |
|------|------|
| Exact symbol/string | `sg_keyword_search` |
| Concepts/semantic search | `sg_nls_search` |
| Trace usage/callers | `sg_find_references` |
| See implementation | `sg_go_to_definition` |
| Read full file | `sg_read_file` |
| Browse structure | `sg_list_files` |
| Find repos | `sg_list_repos` |
| Search commits | `sg_commit_search` |
| Track changes | `sg_diff_search` |
| Compare versions | `sg_compare_revisions` |

**Decision logic:**
1. Know the exact symbol? -> `sg_keyword_search`
2. Know the concept, not the name? -> `sg_nls_search`
3. Need definition of a symbol? -> `sg_go_to_definition`
4. Need all callers/references? -> `sg_find_references`
5. Need full file content? -> `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search -> read -> references -> definition
- Don't re-search for the same pattern; use results from prior calls
- Prefer `sg_keyword_search` over `sg_nls_search` when you have exact terms
- Read 2-3 related files before synthesising, rather than one at a time
- Don't read 20+ remote files without writing code — once you understand the pattern, start implementing

## If Stuck

If MCP search returns no results:
1. Broaden the search query (synonyms, partial identifiers)
2. Try `sg_nls_search` for semantic matching
3. Use `sg_list_files` to browse the directory structure
4. Use `sg_list_repos` to verify the repository name

---

**Sourcegraph Repositories:** {repo_names}

{task_content}"""

    path = os.path.join(task_dir, "instruction_mcp.md")
    with open(path, "w") as f:
        f.write(content)
    return path


def fix_instruction_template_bugs(task_dir, file_ext, language):
    """Fix template .go extension in instruction.md for non-Go tasks."""
    path = os.path.join(task_dir, "instruction.md")
    with open(path) as f:
        content = f.read()

    original = content

    # Fix .go extension in example JSON
    if file_ext != ".go":
        content = content.replace(
            '"relative/path/to/file.go"',
            f'"relative/path/to/file{file_ext}"',
        )

    if content != original:
        with open(path, "w") as f:
            f.write(content)
        return True
    return False


def main():
    registry = load_registry()
    processed = []
    errors = []

    for uc_id in NEW_TASK_IDS:
        if uc_id not in registry:
            errors.append(f"UC {uc_id}: not found in registry")
            continue

        uc = registry[uc_id]
        repo_set_id = uc.get("repo_set_id", "")

        if repo_set_id not in REPO_SETS:
            errors.append(f"UC {uc_id}: unknown repo_set_id '{repo_set_id}'")
            continue

        task_dir = find_task_dir(uc_id, registry)
        if not task_dir:
            errors.append(f"UC {uc_id}: task directory not found")
            continue

        repo_set = REPO_SETS[repo_set_id]
        sg_repos = repo_set["sg_repos"]
        clone_repos = repo_set["clone_repos"]
        file_ext = repo_set["file_ext"]
        language = repo_set["language"]

        task_name = os.path.basename(task_dir)
        actions = []

        # 1. Create Dockerfile.artifact_only
        artifact_path = os.path.join(task_dir, "environment", "Dockerfile.artifact_only")
        if not os.path.exists(artifact_path):
            generate_artifact_only_dockerfile(task_dir, sg_repos)
            actions.append("created Dockerfile.artifact_only")

        # 2. Update Dockerfile.sg_only with SOURCEGRAPH_REPOS + manifest
        update_sg_only_dockerfile(task_dir, sg_repos, clone_repos)
        actions.append("updated Dockerfile.sg_only")

        # 3. Create test.sh (dual-mode dispatcher or standard wrapper)
        is_dual_mode = uc_id in DUAL_MODE_TASK_IDS
        test_path = os.path.join(task_dir, "tests", "test.sh")
        if not os.path.exists(test_path):
            if is_dual_mode:
                create_dual_mode_test_sh(task_dir)
                actions.append("created dual-mode test.sh")
            else:
                create_test_sh(task_dir)
                actions.append("created test.sh")

        # 3b. Copy parent verifier for dual-mode adapted tasks
        # Overwrite placeholder direct_verifier.sh with actual parent verifier
        if is_dual_mode and uc_id in PARENT_TASK_MAP:
            direct_path = os.path.join(task_dir, "tests", "direct_verifier.sh")
            is_placeholder = False
            if os.path.exists(direct_path):
                with open(direct_path) as f:
                    is_placeholder = "PLACEHOLDER" in f.read()
            if not os.path.exists(direct_path) or is_placeholder:
                copied_files = copy_parent_verifier(task_dir, PARENT_TASK_MAP[uc_id])
                if copied_files:
                    actions.append(f"copied parent verifier: {', '.join(copied_files)}")

        # 4. Copy sgonly_verifier_wrapper.sh
        wrapper_path = os.path.join(task_dir, "tests", "sgonly_verifier_wrapper.sh")
        if not os.path.exists(wrapper_path):
            copy_sgonly_wrapper(task_dir)
            actions.append("copied sgonly_verifier_wrapper.sh")

        # 5. Create instruction_mcp.md
        mcp_path = os.path.join(task_dir, "instruction_mcp.md")
        if not os.path.exists(mcp_path):
            generate_instruction_mcp(task_dir, sg_repos, uc)
            actions.append("created instruction_mcp.md")

        # 6. Fix template bugs in instruction.md
        if fix_instruction_template_bugs(task_dir, file_ext, language):
            actions.append(f"fixed .go -> {file_ext} in instruction.md")

        processed.append(f"  {task_name} (UC {uc_id}): {', '.join(actions)}")

    print(f"Customized {len(processed)} tasks:")
    for line in processed:
        print(line)

    if errors:
        print(f"\nErrors ({len(errors)}):")
        for err in errors:
            print(f"  {err}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
