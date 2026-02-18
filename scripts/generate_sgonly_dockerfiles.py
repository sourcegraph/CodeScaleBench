#!/usr/bin/env python3
"""Generate Dockerfile.sg_only for all active tasks that don't have one.

Write-only tasks: minimal image with no repo clone.
Build-requiring tasks: original Dockerfile + backup/truncate/marker.

Also injects the verifier wrapper guard into test.sh for build-requiring tasks
and copies sgonly_verifier_wrapper.sh into tests/.
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS = REPO_ROOT / "benchmarks"
WRAPPER_SRC = REPO_ROOT / "scripts" / "sgonly_verifier_wrapper.sh"

GUARD_LINE = '[ -f /tmp/.sg_only_mode ] && [ -f /tests/sgonly_verifier_wrapper.sh ] && source /tests/sgonly_verifier_wrapper.sh'
GUARD_COMMENT = '# sg_only_env: restore full repo before verification (no-op for regular runs)'

# Source file extensions to truncate — must cover ALL readable code/config/doc
# formats so the agent cannot extract information from local files.
TRUNCATE_EXTENSIONS = (
    # Python
    '*.py', '*.pyx', '*.pyi',
    # JavaScript / TypeScript
    '*.js', '*.ts', '*.jsx', '*.tsx', '*.mjs', '*.cjs', '*.mts', '*.cts',
    # Go
    '*.go',
    # Java / JVM
    '*.java', '*.kt', '*.scala', '*.groovy', '*.clj',
    # C / C++ (including .cc used by Envoy, gRPC, Chromium, etc.)
    '*.c', '*.cc', '*.cpp', '*.cxx', '*.h', '*.hh', '*.hpp', '*.hxx',
    # Rust
    '*.rs',
    # Ruby
    '*.rb',
    # C# / .NET
    '*.cs', '*.fs',
    # Swift / Objective-C
    '*.swift', '*.m', '*.mm',
    # Web frameworks
    '*.vue', '*.svelte',
    # Shell
    '*.sh', '*.bash', '*.zsh',
    # Lua
    '*.lua',
    # Protobuf / gRPC / IDL
    '*.proto', '*.thrift', '*.avsc', '*.fbs',
    # Config / data (often contains structural info agents can exploit)
    '*.yaml', '*.yml', '*.toml', '*.json', '*.xml', '*.ini', '*.cfg',
    # Documentation (agents can extract architecture info)
    '*.md', '*.rst', '*.txt', '*.adoc',
    # Build files
    '*.cmake', '*.bzl', '*.bazel',
    # SQL
    '*.sql',
    # Erlang / Elixir
    '*.erl', '*.ex', '*.exs',
    # PHP
    '*.php',
    # Perl
    '*.pl', '*.pm',
    # R
    '*.r', '*.R',
)

# Build the find expression for truncation
def truncate_find_expr(workdir, extra_excludes=None):
    names = ' -o '.join(f'-name "{ext}"' for ext in TRUNCATE_EXTENSIONS)
    excludes = '! -path "*/.git/*"'
    if extra_excludes:
        for ex in extra_excludes:
            excludes += f' ! -path "{ex}"'
    return f'find {workdir} -type f \\( {names} \\) {excludes} -exec truncate -s 0 {{}} \\;'


def get_active_task_ids():
    """Get set of active task IDs from on-disk benchmarks, TASK_CATALOG.md, and swebenchpro MANIFEST."""
    tasks = {}  # task_id -> suite_name

    # Primary: scan benchmarks/ directories on disk (catches newly added tasks)
    for suite_dir in sorted(BENCHMARKS.iterdir()):
        if not suite_dir.is_dir() or not suite_dir.name.startswith('ccb_'):
            continue
        suite_name = suite_dir.name
        for task_dir in sorted(suite_dir.iterdir()):
            if not task_dir.is_dir():
                continue
            # Must have environment/Dockerfile to be a real task
            if (task_dir / "environment" / "Dockerfile").exists():
                tasks[task_dir.name] = suite_name
            # Also check tasks/ subdirectory pattern
            if task_dir.name == "tasks":
                for sub in sorted(task_dir.iterdir()):
                    if sub.is_dir() and (sub / "environment" / "Dockerfile").exists():
                        tasks[sub.name] = suite_name

    # SWE-bench Pro from MANIFEST (may have tasks not on disk)
    manifest_path = BENCHMARKS / "ccb_swebenchpro" / "MANIFEST.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for tid in manifest.get("task_ids", []):
            if tid not in tasks:
                tasks[tid] = "SWE-bench Pro"

    return tasks


def find_task_dir(task_id):
    """Find the task directory on disk for a given task ID."""
    # Direct match: benchmarks/suite/task_id/
    for d in BENCHMARKS.glob(f"*/{task_id}/environment/Dockerfile"):
        return d.parent.parent
    # Tasks subdirectory: benchmarks/suite/tasks/task_id/
    for d in BENCHMARKS.glob(f"*/tasks/{task_id}/environment/Dockerfile"):
        return d.parent.parent
    # SWE-bench Pro uses different naming (__ vs -, case differences)
    for variant in [task_id, task_id.replace("__", "-")]:
        for d in BENCHMARKS.glob(f"*/tasks/{variant}/environment/Dockerfile"):
            return d.parent.parent
        # Case-insensitive fallback
        lower = variant.lower()
        for d in BENCHMARKS.glob("*/tasks/*/environment/Dockerfile"):
            if d.parent.parent.name.lower() == lower:
                return d.parent.parent
    return None


def detect_workdir(dockerfile_text):
    """Detect the WORKDIR from a Dockerfile."""
    workdirs = re.findall(r'^WORKDIR\s+(\S+)', dockerfile_text, re.MULTILINE)
    return workdirs[-1] if workdirs else '/workspace'


def detect_clone_type(dockerfile_text):
    """Determine if a Dockerfile clones a repo and how."""
    # SWE-bench prebuilt images (FROM jefzda/sweap-images:...)
    if 'sweap-images' in dockerfile_text or 'swebench' in dockerfile_text.lower():
        return 'swebench'
    # Pre-built base images (FROM harbor-... or FROM ghcr.io/theagentcompany/...)
    if 'harbor-' in dockerfile_text or 'theagentcompany' in dockerfile_text:
        return 'prebuilt'
    # Git clone in the Dockerfile
    if re.search(r'git clone', dockerfile_text):
        return 'clone'
    # COPY repo from build context
    if re.search(r'COPY\s+repo\b', dockerfile_text):
        return 'copy_repo'
    return 'none'


def is_write_only_verifier(task_dir):
    """Check if the verifier just checks text output (no compilation/tests)."""
    test_sh = task_dir / "tests" / "test.sh"
    if not test_sh.exists():
        return False
    content = test_sh.read_text()
    # Write-only indicators: checks for file existence, grep patterns, LLM judge
    write_indicators = [
        'documentation.md', 'analysis.md', 'report.md', 'answer.md',
        'response.md', 'onboarding', 'handoff', 'review.json',
        'llm_judge', 'openai', 'claude', 'gpt-4',
        'checklist', 'EXPECTED_SECTIONS', 'grep -q',
    ]
    build_indicators = [
        'pytest', 'go test', 'go build', 'make', 'npm test',
        'cargo test', 'dotnet build', 'dotnet test', 'javac',
        'gcc ', 'g++ ', 'cmake', 'git apply', 'git diff',
        'patch ', 'PATCH_APPLY', 'regression_test',
    ]
    write_score = sum(1 for w in write_indicators if w in content)
    build_score = sum(1 for b in build_indicators if b in content)
    return write_score > build_score


def generate_write_only(task_dir, dockerfile_text):
    """Generate a write-only Dockerfile.sg_only (no repo clone)."""
    workdir = detect_workdir(dockerfile_text)
    base_image = 'ubuntu:22.04'

    # Try to detect the base image from original
    m = re.match(r'^FROM\s+(\S+)', dockerfile_text, re.MULTILINE)
    if m:
        orig_base = m.group(1)
        # Use a minimal base, not the original (which may have the repo)
        if 'python' in orig_base.lower():
            base_image = 'python:3.11-slim'
        elif 'golang' in orig_base.lower() or 'go:' in orig_base.lower():
            base_image = 'golang:1.23-bookworm'
        elif 'node' in orig_base.lower():
            base_image = 'node:22-bookworm-slim'
        elif 'eclipse-temurin' in orig_base.lower() or 'java' in orig_base.lower():
            base_image = 'eclipse-temurin:17-jdk'
        elif 'gcc' in orig_base.lower():
            base_image = 'gcc:13'
        elif 'debian' in orig_base.lower() or 'bookworm' in orig_base.lower():
            base_image = 'debian:bookworm-slim'

    task_name = task_dir.name
    return f"""# {task_name} — sg_only_env variant
# No local repo clone — agent uses Sourcegraph MCP exclusively for code access.

FROM {base_image}

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    ca-certificates \\
    python3 \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR {workdir}

# Empty git repo so agent can commit work
RUN git init && \\
    git config user.email "agent@example.com" && \\
    git config user.name "Agent"

RUN mkdir -p /logs/agent /logs/verifier

# Mark sg_only mode so verifiers can skip local-path checks
RUN touch /tmp/.sg_only_mode

ENTRYPOINT []
"""


def generate_build_requiring(task_dir, dockerfile_text):
    """Generate a build-requiring Dockerfile.sg_only from the original."""
    workdir = detect_workdir(dockerfile_text)
    clone_type = detect_clone_type(dockerfile_text)
    lines = dockerfile_text.rstrip().split('\n')

    # Determine extra excludes for truncation
    extra_excludes = []
    if 'node_modules' in dockerfile_text or 'npm install' in dockerfile_text:
        extra_excludes.append('*/node_modules/*')

    # For SWE-bench images, the repo is at /app
    if clone_type == 'swebench':
        repo_dir = '/app'
        workdir = '/app'
    elif clone_type == 'prebuilt':
        repo_dir = workdir
    else:
        repo_dir = workdir

    # Build the sg_only section to append
    sg_section = f"""
# --- sg_only_env: back up full repo, then truncate source ---
RUN cp -a {repo_dir} /repo_full
RUN {truncate_find_expr(repo_dir, extra_excludes)}
RUN touch /tmp/.sg_only_mode && echo '{repo_dir}' > /tmp/.sg_only_workdir
"""

    # Find insertion point: before the last ENTRYPOINT/CMD or at the end
    insert_idx = len(lines)
    for i in range(len(lines) - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped.startswith('ENTRYPOINT') or stripped.startswith('CMD'):
            insert_idx = i
            break

    # Build output
    task_name = task_dir.name
    header = f"# {task_name} — sg_only_env variant\n"
    header += "# Source files truncated so agent must use Sourcegraph MCP for code access.\n"
    header += "# Verifier wrapper restores full repo before running tests.\n\n"

    body_lines = lines[:insert_idx]
    tail_lines = lines[insert_idx:]

    result = header + '\n'.join(body_lines) + '\n' + sg_section
    if tail_lines:
        result += '\n'.join(tail_lines) + '\n'
    else:
        result += f'\nWORKDIR {workdir}\n\nENTRYPOINT []\n'

    return result


def inject_test_guard(task_dir):
    """Add the verifier wrapper guard to test.sh if not already present."""
    test_sh = task_dir / "tests" / "test.sh"
    if not test_sh.exists():
        return False

    content = test_sh.read_text()
    if 'sg_only_mode' in content:
        return False  # Already has guard

    lines = content.split('\n')

    # Find insertion point: after shebang and initial comments
    insert_idx = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('#!') or stripped.startswith('#') or stripped == '':
            insert_idx = i + 1
        else:
            break
    # But also look for 'set -e' which should come before the guard
    for i, line in enumerate(lines):
        if line.strip() == 'set -e':
            insert_idx = i + 1
            break

    guard_block = f'\n{GUARD_COMMENT}\n{GUARD_LINE}\n'
    lines.insert(insert_idx, guard_block)
    test_sh.write_text('\n'.join(lines))
    return True


def copy_wrapper(task_dir):
    """Copy sgonly_verifier_wrapper.sh to the task's tests/ directory."""
    tests_dir = task_dir / "tests"
    if not tests_dir.exists():
        return False
    dest = tests_dir / "sgonly_verifier_wrapper.sh"
    if dest.exists():
        return False
    if WRAPPER_SRC.exists():
        dest.write_text(WRAPPER_SRC.read_text())
        dest.chmod(0o755)
        return True
    return False


def main():
    dry_run = '--dry-run' in sys.argv
    verbose = '--verbose' in sys.argv or '-v' in sys.argv

    active_tasks = get_active_task_ids()
    print(f"Active tasks: {len(active_tasks)}")

    generated = 0
    skipped = 0
    guards_added = 0
    wrappers_copied = 0
    errors = []
    write_only_count = 0
    build_count = 0

    for task_id, suite in sorted(active_tasks.items(), key=lambda x: (x[1], x[0])):
        task_dir = find_task_dir(task_id)
        if task_dir is None:
            if verbose:
                print(f"  SKIP {task_id}: not found on disk")
            continue

        env_dir = task_dir / "environment"
        dockerfile = env_dir / "Dockerfile"
        sgonly = env_dir / "Dockerfile.sg_only"

        if sgonly.exists():
            skipped += 1
            continue

        if not dockerfile.exists():
            if verbose:
                print(f"  SKIP {task_id}: no Dockerfile")
            continue

        dockerfile_text = dockerfile.read_text()
        clone_type = detect_clone_type(dockerfile_text)
        # Write-only if: no repo in baseline, OR verifier only checks output
        # (doc-gen, analysis tasks). Write-only gives the agent an empty
        # workspace so it must use MCP — no confusing truncated file trees.
        write_only = (clone_type == 'none') or is_write_only_verifier(task_dir)

        try:
            if write_only:
                # No local code needed: minimal image, empty workspace
                content = generate_write_only(task_dir, dockerfile_text)
                write_only_count += 1
            else:
                # Verifier needs local code (compilation, test execution):
                # keep repo but truncate source files
                content = generate_build_requiring(task_dir, dockerfile_text)
                build_count += 1

            if dry_run:
                print(f"  {'WRITE-ONLY' if write_only else 'BUILD-REQ':>10} {suite:<25} {task_id}")
            else:
                sgonly.write_text(content)
                generated += 1
                if verbose:
                    print(f"  GENERATED {task_id} ({'write-only' if write_only else 'build-req'})")

                # For build-requiring tasks, add verifier guard and wrapper
                if not write_only:
                    if inject_test_guard(task_dir):
                        guards_added += 1
                    if copy_wrapper(task_dir):
                        wrappers_copied += 1

        except Exception as e:
            errors.append((task_id, str(e)))
            print(f"  ERROR {task_id}: {e}")

    print(f"\n{'DRY RUN - ' if dry_run else ''}Summary:")
    print(f"  Already had sg_only: {skipped}")
    print(f"  Generated: {generated} ({write_only_count} write-only, {build_count} build-requiring)")
    print(f"  test.sh guards added: {guards_added}")
    print(f"  Wrappers copied: {wrappers_copied}")
    if errors:
        print(f"  Errors: {len(errors)}")
        for tid, err in errors:
            print(f"    {tid}: {err}")


if __name__ == '__main__':
    main()
