#!/usr/bin/env python3
"""Generate Dockerfile.sg_only for all active tasks that don't have one.

Write-only tasks: minimal image with no repo clone.
Build-requiring tasks (v2): empty workspace with clone manifest — the verifier
clones mirrors at verification time instead of shipping /repo_full/ in the image.

Also injects the verifier wrapper guard into test.sh for build-requiring tasks
and copies sgonly_verifier_wrapper.sh into tests/.

NOTE: This script injects SOURCEGRAPH_REPOS env vars for tasks that have
explicit git clone commands in their Dockerfile (MCP-unique tasks). For SDLC
tasks that use prebuilt images (FROM sweap-images, FROM ccb-linux-base, etc.),
run inject_sg_repo_env.py afterward to add SOURCEGRAPH_REPO_NAME env vars
based on task.toml repo fields and instance_to_mirror.json mappings.

Workflow:
    python3 scripts/generate_sgonly_dockerfiles.py   # create/regenerate Dockerfiles
    python3 scripts/inject_sg_repo_env.py            # add repo env vars for prebuilt-image tasks
"""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BENCHMARKS = REPO_ROOT / "benchmarks"
WRAPPER_SRC = REPO_ROOT / "scripts" / "sgonly_verifier_wrapper.sh"

# Mapping from upstream GitHub repos (as they appear in Dockerfile git clone URLs)
# to their version-pinned sg-evals mirrors on Sourcegraph.
# Used to inject SOURCEGRAPH_REPOS env var into Dockerfile.sg_only / Dockerfile.artifact_only
# so the agent searches the correct version-pinned mirrors instead of HEAD on public repos.
UPSTREAM_TO_MIRROR = {
    "kubernetes/kubernetes": "sg-evals/kubernetes-kubernetes",
    "etcd-io/etcd": "sg-evals/etcd-io-etcd",
    "grafana/grafana": "sg-evals/grafana",
    "grafana/loki": "sg-evals/grafana-loki",
    "kubernetes/client-go": "sg-evals/kubernetes-client-go",
    "kubernetes/api": "sg-evals/kubernetes-api",
    "scikit-learn/scikit-learn": "sg-evals/scikit-learn",
    "numpy/numpy": "sg-evals/numpy",
    "pandas-dev/pandas": "sg-evals/pandas",
    "scipy/scipy": "sg-evals/scipy",
    "nodejs/node": "sg-evals/nodejs-node",
    "expressjs/express": "sg-evals/expressjs-express",
    "prometheus/prometheus": "sg-evals/prometheus",
}

# Mapping from ccb-repo-* image tags to their underlying base image and packages.
# Derived from base_images/Dockerfile.* files. Used by generate_build_requiring_v2()
# to emit lightweight Dockerfiles that don't depend on the ccb-repo images.
CCB_REPO_BASE_MAP = {
    "ccb-repo-camel-1006f047": {
        "from": "eclipse-temurin:17-jdk",
        "packages": ["git", "curl", "python3", "python3-pip"],
        "mirror": "sg-evals/camel--1006f047",
    },
    "ccb-repo-django-674eda1c": {
        "from": "python:3.11-slim",
        "packages": ["git", "curl"],
        "mirror": "sg-evals/django--674eda1c",
    },
    "ccb-repo-django-9e7cc2b6": {
        "from": "python:3.12-bookworm",
        "packages": ["git", "curl"],
        "mirror": "sg-evals/django--9e7cc2b6",
    },
    "ccb-repo-k8s-8c9c67c0": {
        "from": "golang:1.23-bookworm",
        "packages": ["git", "curl", "python3", "python3-pip"],
        "mirror": "sg-evals/kubernetes--8c9c67c0",
    },
    "ccb-repo-k8s-11602f08": {
        "from": "golang:1.23-bookworm",
        "packages": ["git", "curl", "python3", "python3-pip"],
        "mirror": "sg-evals/kubernetes--11602f08",
    },
    "ccb-repo-flipt-3d5a345f": {
        "from": "golang:1.23-bookworm",
        "packages": ["git", "curl"],
        "mirror": "sg-evals/flipt--3d5a345f",
    },
    "ccb-repo-envoy-1d0ba73a": {
        "from": "ubuntu:22.04",
        "packages": ["git", "curl", "python3", "ripgrep"],
        "mirror": "sg-evals/envoy--1d0ba73a",
    },
    "ccb-repo-envoy-d7809ba2": {
        "from": "ubuntu:22.04",
        "packages": ["git", "curl", "python3", "python3-pip", "ripgrep"],
        "mirror": "sg-evals/envoy--d7809ba2",
    },
    "ccb-repo-kafka-0753c489": {
        "from": "eclipse-temurin:17-jdk",
        "packages": ["git", "curl"],
        "mirror": "sg-evals/kafka--0753c489",
    },
    "ccb-repo-kafka-e678b4b": {
        "from": "eclipse-temurin:21-jdk",
        "packages": ["git", "curl", "python3", "ripgrep"],
        "mirror": "sg-evals/kafka--e678b4b",
    },
    "ccb-repo-flink-0cc95fcc": {
        "from": "eclipse-temurin:17-jdk",
        "packages": ["git", "curl", "python3", "python3-pip"],
        "mirror": "sg-evals/flink--0cc95fcc",
    },
    "ccb-repo-postgres-5a461dc4": {
        "from": "gcc:14-bookworm",
        "packages": ["git", "curl", "python3", "python3-pip", "bison", "flex",
                      "libreadline-dev", "zlib1g-dev"],
        "mirror": "sg-evals/postgres--5a461dc4",
    },
    "ccb-repo-strata-66225ca9": {
        "from": "eclipse-temurin:17-jdk",
        "packages": ["git", "curl", "python3", "python3-pip", "maven"],
        "mirror": "sg-evals/Strata--66225ca9",
    },
    "ccb-repo-curl-09e25b9d": {
        "from": "debian:bookworm-slim",
        "packages": ["git", "curl", "python3", "build-essential", "jq", "bc"],
        "mirror": "sg-evals/curl--09e25b9d",
    },
}


def extract_clone_layout(dockerfile_text):
    """Parse a baseline Dockerfile to extract clone URLs, target dirs, and commits.

    Returns a list of dicts: [{"mirror": "sg-evals/...", "target_dir": "." or "subdir"}]
    Also returns inject_defects path if the Dockerfile uses COPY inject_defects.sh.
    """
    repos = []
    inject_defects = None
    workdir = detect_workdir(dockerfile_text)

    for line in dockerfile_text.splitlines():
        stripped = line.strip()
        # Skip comments and continuation lines
        if stripped.startswith('#') or not stripped:
            continue

        # Extract full GitHub URL from git clone commands, then parse it
        url_match = re.search(r'git clone\b.*?(https://github\.com/\S+)', stripped)
        if url_match:
            url = url_match.group(1)
            # Strip .git suffix
            if url.endswith('.git'):
                url = url[:-4]
            repo_path = url.replace('https://github.com/', '')

            # Look for target directory after the URL (may have .git suffix in original)
            # Re-search for target: everything after the URL
            orig_url = url_match.group(1)
            after_url = stripped[url_match.end():]
            target_match = re.match(r'\s+(\S+)', after_url)
            target = target_match.group(1) if target_match else None

            # Determine mirror name
            if repo_path.startswith("sg-evals/"):
                mirror = repo_path
            else:
                mirror = UPSTREAM_TO_MIRROR.get(repo_path, f"sg-evals/{repo_path}")

            # Determine target_dir relative to workdir
            if target is None or target == '.' or target == workdir:
                target_dir = '.'
            elif target.startswith('/'):
                # Absolute path — compute relative to workdir
                if target == workdir or target == workdir + '/':
                    target_dir = '.'
                elif target.startswith(workdir + '/'):
                    target_dir = target[len(workdir) + 1:]
                else:
                    target_dir = '.'
            else:
                target_dir = target

            # Clean up flags/continuations that might have been captured as target
            if target_dir.startswith('-') or target_dir.startswith('&&') or target_dir.startswith('\\'):
                target_dir = '.'

            repos.append({"mirror": mirror, "target_dir": target_dir})

        # Detect inject_defects.sh
        if 'inject_defects.sh' in stripped and 'COPY' in stripped:
            inject_defects = '/tmp/inject_defects.sh'

    return repos, inject_defects


def _lookup_mirror_for_task(task_id):
    """Look up the sg-evals mirror for a task from inject_sg_repo_env.py data.

    Falls back to None if the mapping isn't found.
    """
    # Try to import from inject_sg_repo_env.py
    env_script = REPO_ROOT / "scripts" / "inject_sg_repo_env.py"
    if not env_script.exists():
        return None
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("inject_sg_repo_env", env_script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        # Check multi-repo first
        multi = getattr(mod, 'MULTI_REPO_TASKS', {})
        if task_id in multi:
            # Returns comma-separated mirrors
            return multi[task_id]
        # Check single-repo
        single = getattr(mod, 'SINGLE_REPO_TASKS', {})
        if task_id in single:
            return single[task_id]
    except Exception:
        pass
    return None


def extract_mirror_repos(dockerfile_text: str) -> list:
    """Extract upstream repos from git clone commands and map to sg-evals mirrors.

    Parses 'git clone ... https://github.com/{org}/{repo}' lines from the baseline
    Dockerfile to determine which repos are used, then maps each to its sg-evals
    mirror name. Also handles repos already cloned from sg-evals directly.
    """
    mirrors = []
    for line in dockerfile_text.splitlines():
        # Match: git clone ... https://github.com/{org}/{repo}[.git] ...
        match = re.search(r'github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?\s', line)
        if not match:
            # Also try URL at end of line (no trailing space)
            match = re.search(r'github\.com/([^/\s]+/[^/\s]+?)(?:\.git)?$', line.strip())
        if match:
            upstream = match.group(1)
            mirror = UPSTREAM_TO_MIRROR.get(upstream)
            if mirror:
                mirrors.append(mirror)
            elif upstream.startswith("sg-evals/"):
                # Already an sg-evals repo — pass through
                mirrors.append(upstream)
    return sorted(set(mirrors))

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
    # ccb-linux-base prebuilt images (contain kernel source at /workspace/)
    if re.search(r'^FROM\s+ccb-linux-base:', dockerfile_text, re.MULTILINE):
        return 'ccb_linux_base'
    # ccb-repo-* prebuilt images (contain cloned repo at /workspace/)
    if re.search(r'^FROM\s+ccb-repo-', dockerfile_text, re.MULTILINE):
        return 'ccb_repo'
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


def has_defect_injection(task_dir):
    """Check if the task uses inject_defects.sh (code review tasks)."""
    return (task_dir / "environment" / "inject_defects.sh").exists()


def has_sgonly_wrapper(task_dir):
    """Check if the task already has sgonly_verifier_wrapper.sh in tests/.

    Tasks with this wrapper are build-requiring — the wrapper restores /repo_full
    before verification, which requires the Dockerfile.sg_only to set up /repo_full.
    """
    return (task_dir / "tests" / "sgonly_verifier_wrapper.sh").exists()


def is_write_only_verifier(task_dir, ignore_wrapper=False):
    """Check if the verifier just checks text output (no compilation/tests).

    Tasks with inject_defects.sh are NEVER write-only — the verifier
    checks local source files. When ignore_wrapper=True (for --force
    regeneration), the sgonly_verifier_wrapper.sh presence is not used
    as a signal, since it may be left over from a previous classification.
    """
    if has_defect_injection(task_dir):
        return False
    if not ignore_wrapper and has_sgonly_wrapper(task_dir):
        return False
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

    # Extract mirror repos from baseline Dockerfile for SOURCEGRAPH_REPOS env var
    mirrors = extract_mirror_repos(dockerfile_text)
    sg_repos_env = ""
    if mirrors:
        sg_repos_env = f'ENV SOURCEGRAPH_REPOS="{",".join(mirrors)}"\n'

    return f"""# {task_name} — sg_only_env variant
# No local repo clone — agent uses Sourcegraph MCP exclusively for code access.

FROM {base_image}

ENV DEBIAN_FRONTEND=noninteractive
{sg_repos_env}
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


def generate_ccb_linux_base_sgonly(task_dir, dockerfile_text):
    """Generate sg_only for ccb-linux-base tasks (kernel source at /workspace/).

    Uses ubuntu:22.04 instead of ccb-linux-base to avoid Harbor test-upload
    failures that occur with ccb-linux-base derived images. In sg_only mode
    the agent uses Sourcegraph MCP for code access — kernel source not needed.
    Installs gawk for verifier scripts that use awk arithmetic.
    """
    task_name = task_dir.name
    return f"""# {task_name} — sg_only_env variant
# No local repo clone — agent uses Sourcegraph MCP exclusively for code access.
# Uses ubuntu:22.04 (replaces ccb-linux-base to fix Harbor test upload).

FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    ca-certificates \\
    python3 \\
    gawk \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Empty git repo so agent can commit work
RUN git init && \\
    git config user.email "agent@example.com" && \\
    git config user.name "Agent"

RUN mkdir -p /logs/agent /logs/verifier

# Mark sg_only mode so verifiers can skip local-path checks
RUN touch /tmp/.sg_only_mode

ENTRYPOINT []
"""


def _make_clone_manifest_json(workdir, repos, inject_defects=None):
    """Build the JSON string for /tmp/.sg_only_clone_manifest.json.

    Returns compact single-line JSON to avoid Docker parser issues — multi-line
    RUN echo with JSON keys (e.g. "workdir":) on their own line gets
    misinterpreted as unknown Dockerfile instructions.
    """
    manifest = {"workdir": workdir, "repos": repos}
    if inject_defects:
        manifest["inject_defects"] = inject_defects
    return json.dumps(manifest, separators=(",", ":"))


def _detect_from_image(dockerfile_text):
    """Extract the FROM image from a Dockerfile (first non-arg FROM)."""
    for line in dockerfile_text.splitlines():
        m = re.match(r'^FROM\s+(\S+)', line.strip())
        if m:
            return m.group(1)
    return 'ubuntu:22.04'


def _extra_packages_from_dockerfile(dockerfile_text):
    """Extract extra tool packages installed in the Dockerfile beyond base set."""
    extras = set()
    for line in dockerfile_text.splitlines():
        if 'nodejs' in line or 'nodesource' in line:
            extras.add('nodejs_setup')
        if 'ripgrep' in line:
            extras.add('ripgrep')
        if 'jq' in line and ('apt-get' in line or 'apk' in line):
            extras.add('jq')
        if 'bc' in line and 'apt-get' in line:
            extras.add('bc')
        if 'maven' in line and 'apt-get' in line:
            extras.add('maven')
    return extras


def generate_build_requiring(task_dir, dockerfile_text):
    """Generate a build-requiring Dockerfile.sg_only (v2: clone-at-verify, no /repo_full/).

    Instead of cloning the repo, backing up to /repo_full/, and truncating, we now
    generate a lightweight image with an empty workspace + a clone manifest. The
    verifier wrapper reads the manifest and clones mirrors at verification time.

    Subcategories handled:
    - ccb-repo-* tasks: use underlying base image from CCB_REPO_BASE_MAP
    - SWE-bench tasks: keep FROM jefzda/sweap-images, truncate but no backup
    - Inline-clone tasks: empty workspace with manifest
    - Code-review tasks: bake inject_defects.sh, reference in manifest
    - Multi-repo tasks: multiple entries in manifest repos list
    """
    task_name = task_dir.name
    workdir = detect_workdir(dockerfile_text)
    clone_type = detect_clone_type(dockerfile_text)
    from_image = _detect_from_image(dockerfile_text)

    # Extract mirror repos for SOURCEGRAPH_REPOS env var
    mirrors = extract_mirror_repos(dockerfile_text)

    # --- Determine clone layout from baseline Dockerfile ---
    repos, inject_defects = extract_clone_layout(dockerfile_text)

    # --- ccb-repo-* tasks: resolve base image from CCB_REPO_BASE_MAP ---
    if from_image.startswith('ccb-repo-'):
        info = CCB_REPO_BASE_MAP.get(from_image)
        if info:
            base_image = info['from']
            packages = info['packages']
            mirror = info['mirror']
            # Single repo cloned to workspace root
            if not repos:
                repos = [{"mirror": mirror, "target_dir": "."}]
        else:
            # Unknown ccb-repo image — fall back to ubuntu with clone layout from Dockerfile
            base_image = 'ubuntu:22.04'
            packages = ['git', 'ca-certificates', 'python3', 'curl']

        sg_repos_env = ""
        if mirrors:
            sg_repos_env = f'ENV SOURCEGRAPH_REPOS="{",".join(mirrors)}"\n'

        manifest_json = _make_clone_manifest_json(workdir, repos, inject_defects)
        pkg_lines = ' \\\n    '.join(packages)
        extra_pkgs = _extra_packages_from_dockerfile(dockerfile_text)

        nodejs_block = ""
        if 'nodejs_setup' in extra_pkgs:
            nodejs_block = """
# Install Node.js (needed by verifier)
RUN if ! command -v node > /dev/null 2>&1; then \\
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \\
    apt-get install -y --no-install-recommends nodejs; \\
    fi
"""
        extra_apt = ""
        for pkg in sorted(extra_pkgs - {'nodejs_setup'}):
            extra_apt += f"    {pkg} \\\n"

        return f"""# {task_name} — sg_only_env variant (v2: clone-at-verify)
# Empty workspace — agent uses Sourcegraph MCP for code access.
# Verifier clones mirror at verification time via clone manifest.

FROM {base_image}

ENV DEBIAN_FRONTEND=noninteractive
{sg_repos_env}
RUN apt-get update && apt-get install -y --no-install-recommends \\
    {pkg_lines} \\
    ca-certificates \\
{extra_apt}    && rm -rf /var/lib/apt/lists/*
{nodejs_block}
WORKDIR {workdir}

# Empty git repo so agent can commit work
RUN git init && \\
    git config user.email "agent@example.com" && \\
    git config user.name "Agent"

RUN mkdir -p /logs/agent /logs/verifier

# Clone manifest for verifier (clone-at-verify strategy)
RUN echo '{manifest_json}' > /tmp/.sg_only_clone_manifest.json

# Mark sg_only mode
RUN touch /tmp/.sg_only_mode

ENTRYPOINT []
"""

    # --- SWE-bench tasks: keep FROM sweap-images, truncate source but no /repo_full/ ---
    if clone_type == 'swebench':
        repo_dir = '/app'
        workdir = '/app'
        # Parse the rest of the Dockerfile for extra RUN commands
        extra_run_lines = []
        for line in dockerfile_text.splitlines():
            stripped = line.strip()
            if stripped.startswith('RUN') and 'cp -a' not in stripped:
                # Keep tool installation commands (uv, mkdir, etc.)
                if any(kw in stripped for kw in ['curl', 'uv/', 'mkdir', 'pip install', 'apt-get']):
                    extra_run_lines.append(stripped)

        # Determine extra excludes for truncation
        extra_excludes = []
        if 'node_modules' in dockerfile_text:
            extra_excludes.append('*/node_modules/*')

        # Build mirror info: the mirror is the single-repo mirror from inject_sg_repo_env.py
        # or extracted from baseline Dockerfile
        if not repos:
            # For SWE-bench, look up mirror from inject_sg_repo_env.py mapping
            fallback_mirror = mirrors[0] if mirrors else _lookup_mirror_for_task(task_name)
            if fallback_mirror and ',' not in (fallback_mirror or ''):
                repos = [{"mirror": fallback_mirror, "target_dir": "."}]
            elif fallback_mirror:
                # Multi-repo: split comma-separated mirrors
                repos = [{"mirror": m.strip(), "target_dir": "."} for m in fallback_mirror.split(',')]
            else:
                repos = [{"mirror": "MIRROR_NOT_FOUND", "target_dir": "."}]

        manifest_json = _make_clone_manifest_json(repo_dir, repos)
        sg_repos_env = ""
        if mirrors:
            sg_repos_env = f'\nENV SOURCEGRAPH_REPOS="{",".join(mirrors)}"'

        extra_run_block = ""
        if extra_run_lines:
            extra_run_block = '\n' + '\n'.join(extra_run_lines) + '\n'

        return f"""# {task_name} — sg_only_env variant (v2: clone-at-verify)
# Source files truncated — agent uses Sourcegraph MCP for code access.
# Verifier clones mirror at verification time to restore source.

FROM {from_image}
{sg_repos_env}
{extra_run_block}
WORKDIR {repo_dir}

# Truncate source files so agent cannot read them locally.
# .pyc files and package metadata are left intact to preserve venv.
RUN {truncate_find_expr(repo_dir, extra_excludes)}
# Recommit truncated state so git history cannot recover full files.
RUN cd {repo_dir} && git config user.email "agent@example.com" && \\
    git config user.name "Agent" && \\
    git add -A && git commit -m "sg_only truncation" --allow-empty --quiet

# Clone manifest for verifier (clone-at-verify strategy)
RUN echo '{manifest_json}' > /tmp/.sg_only_clone_manifest.json

# Mark sg_only mode
RUN touch /tmp/.sg_only_mode && echo '{repo_dir}' > /tmp/.sg_only_workdir

ENTRYPOINT []
"""

    # --- Code-review tasks (inject_defects.sh): empty workspace + baked defect script ---
    if has_defect_injection(task_dir):
        inject_defects = '/tmp/inject_defects.sh'
        if not repos:
            fallback_mirror = mirrors[0] if mirrors else _lookup_mirror_for_task(task_name)
            repos = [{"mirror": fallback_mirror or "MIRROR_NOT_FOUND", "target_dir": "."}]
        manifest_json = _make_clone_manifest_json(workdir, repos, inject_defects)

        # Detect base image and packages from the Dockerfile
        base_image = 'ubuntu:22.04'
        if 'python' in from_image.lower():
            base_image = from_image
        elif 'golang' in from_image.lower():
            base_image = from_image

        sg_repos_env = ""
        if mirrors:
            sg_repos_env = f'ENV SOURCEGRAPH_REPOS="{",".join(mirrors)}"\n'

        extra_pkgs = _extra_packages_from_dockerfile(dockerfile_text)
        nodejs_block = ""
        if 'nodejs_setup' in extra_pkgs or 'nodesource' in dockerfile_text:
            nodejs_block = """
# Install Node.js (needed by verifier)
RUN if ! command -v node > /dev/null 2>&1; then \\
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \\
    apt-get install -y --no-install-recommends nodejs; \\
    fi
"""
        extra_apt_list = sorted(extra_pkgs - {'nodejs_setup'})
        extra_apt = ""
        for pkg in extra_apt_list:
            extra_apt += f"    {pkg} \\\n"

        return f"""# {task_name} — sg_only_env variant (v2: clone-at-verify)
# Empty workspace — agent uses Sourcegraph MCP for code access.
# Verifier clones mirror, injects defects, then overlays agent changes.

FROM {base_image}

ENV DEBIAN_FRONTEND=noninteractive
{sg_repos_env}
RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    ca-certificates \\
    python3 \\
    curl \\
{extra_apt}    && rm -rf /var/lib/apt/lists/*
{nodejs_block}
WORKDIR {workdir}

# Empty git repo so agent can commit work
RUN git init && \\
    git config user.email "agent@example.com" && \\
    git config user.name "Agent"

# Bake inject_defects.sh into image for verifier to re-run after cloning
COPY inject_defects.sh /tmp/inject_defects.sh
RUN chmod +x /tmp/inject_defects.sh

RUN mkdir -p {workdir}/tests /logs/verifier /logs/agent

# Clone manifest for verifier (clone-at-verify strategy)
RUN echo '{manifest_json}' > /tmp/.sg_only_clone_manifest.json

# Mark sg_only mode
RUN touch /tmp/.sg_only_mode

ENTRYPOINT []
"""

    # --- Generic inline-clone / multi-repo tasks: empty workspace + manifest ---
    if not repos:
        fallback_mirror = mirrors[0] if mirrors else _lookup_mirror_for_task(task_name)
        if fallback_mirror and ',' not in (fallback_mirror or ''):
            repos = [{"mirror": fallback_mirror, "target_dir": "."}]
        elif fallback_mirror:
            repos = [{"mirror": m.strip(), "target_dir": "."} for m in fallback_mirror.split(',')]
        else:
            repos = [{"mirror": "MIRROR_NOT_FOUND", "target_dir": "."}]
    manifest_json = _make_clone_manifest_json(workdir, repos, inject_defects)

    # Pick a sensible base image
    base_image = 'ubuntu:22.04'
    if 'python' in from_image.lower():
        base_image = from_image
    elif 'golang' in from_image.lower() or 'go:' in from_image.lower():
        base_image = from_image
    elif 'node' in from_image.lower():
        base_image = from_image
    elif 'eclipse-temurin' in from_image.lower() or 'java' in from_image.lower():
        base_image = from_image
    elif 'gcc' in from_image.lower():
        base_image = from_image
    elif 'rust' in from_image.lower():
        base_image = from_image
    elif 'debian' in from_image.lower():
        base_image = from_image

    sg_repos_env = ""
    if mirrors:
        sg_repos_env = f'ENV SOURCEGRAPH_REPOS="{",".join(mirrors)}"\n'
    extra_pkgs = _extra_packages_from_dockerfile(dockerfile_text)
    nodejs_block = ""
    if 'nodejs_setup' in extra_pkgs or 'nodesource' in dockerfile_text:
        nodejs_block = """
# Install Node.js (needed by verifier)
RUN if ! command -v node > /dev/null 2>&1; then \\
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \\
    apt-get install -y --no-install-recommends nodejs; \\
    fi
"""
    extra_apt_list = sorted(extra_pkgs - {'nodejs_setup'})
    extra_apt = ""
    for pkg in extra_apt_list:
        extra_apt += f"    {pkg} \\\n"

    # Detect if alpine-based (uses apk instead of apt-get)
    is_alpine = 'alpine' in base_image.lower()
    if is_alpine:
        install_block = f"""RUN apk add --no-cache \\
    git \\
    python3 \\
    curl \\
    bash"""
    else:
        install_block = f"""RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    ca-certificates \\
    python3 \\
    curl \\
{extra_apt}    && rm -rf /var/lib/apt/lists/*"""

    return f"""# {task_name} — sg_only_env variant (v2: clone-at-verify)
# Empty workspace — agent uses Sourcegraph MCP for code access.
# Verifier clones mirror(s) at verification time via clone manifest.

FROM {base_image}

ENV DEBIAN_FRONTEND=noninteractive
{sg_repos_env}
{install_block}
{nodejs_block}
WORKDIR {workdir}

# Empty git repo so agent can commit work
RUN git init && \\
    git config user.email "agent@example.com" && \\
    git config user.name "Agent"

RUN mkdir -p /logs/agent /logs/verifier

# Clone manifest for verifier (clone-at-verify strategy)
RUN echo '{manifest_json}' > /tmp/.sg_only_clone_manifest.json

# Mark sg_only mode
RUN touch /tmp/.sg_only_mode

ENTRYPOINT []
"""


def generate_artifact_only_mcp(task_dir, dockerfile_text):
    """Generate a Dockerfile.artifact_only for MCP-unique tasks.

    Identical to the write-only sg_only variant but uses .artifact_only_mode marker
    instead of .sg_only_mode. These are used by the artifact_full config where the
    agent produces answer.json instead of editing source files.
    """
    workdir = detect_workdir(dockerfile_text)
    base_image = 'ubuntu:22.04'

    m = re.match(r'^FROM\s+(\S+)', dockerfile_text, re.MULTILINE)
    if m:
        orig_base = m.group(1)
        if 'python' in orig_base.lower():
            base_image = 'python:3.11-slim'
        elif 'golang' in orig_base.lower() or 'go:' in orig_base.lower():
            base_image = 'golang:1.23-bookworm'
        elif 'node' in orig_base.lower():
            base_image = 'node:22-bookworm-slim'

    task_name = task_dir.name
    mirrors = extract_mirror_repos(dockerfile_text)
    sg_repos_env = ""
    if mirrors:
        sg_repos_env = f'ENV SOURCEGRAPH_REPOS="{",".join(mirrors)}"\n'

    return f"""# {task_name} — artifact_only variant
# No local repo clone — agent uses Sourcegraph MCP exclusively for code access.
# Agent produces answer.json artifact; verifier scores the artifact.

FROM {base_image}

ENV DEBIAN_FRONTEND=noninteractive
{sg_repos_env}
RUN apt-get update && apt-get install -y --no-install-recommends \\
    git \\
    ca-certificates \\
    python3 \\
    curl \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR {workdir}

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


def generate_artifact_baseline(task_dir, dockerfile_text):
    """Generate a Dockerfile.artifact_baseline for MCP-unique tasks.

    Uses the original baseline Dockerfile (with local repo clones if any) but adds
    the .artifact_only_mode sentinel so the verifier parses answer.json instead of
    checking git diffs.  This is the correct Dockerfile for baseline-local-artifact:
    the agent has local code access but produces an artifact.
    """
    task_name = task_dir.name
    # Strip any trailing whitespace/newlines, then append the sentinel
    content = dockerfile_text.rstrip()

    # Inject the sentinel before the final ENTRYPOINT if present
    if 'ENTRYPOINT' in content:
        content = content.replace(
            'ENTRYPOINT []',
            '# Mark artifact-only mode — verifier parses answer.json\n'
            'RUN touch /tmp/.artifact_only_mode\n\n'
            'ENTRYPOINT []'
        )
    else:
        content += '\n\n# Mark artifact-only mode — verifier parses answer.json\n'
        content += 'RUN touch /tmp/.artifact_only_mode\n'

    # Add header comment
    header = (
        f"# {task_name} — artifact_baseline variant\n"
        f"# Baseline with local code + artifact mode (verifier parses answer.json).\n"
    )
    # Replace first line if it's a comment, otherwise prepend
    lines = content.split('\n')
    if lines[0].startswith('#'):
        # Find first non-comment line
        idx = 0
        while idx < len(lines) and lines[idx].startswith('#'):
            idx += 1
        lines = header.rstrip().split('\n') + [''] + lines[idx:]
        content = '\n'.join(lines)
    else:
        content = header + '\n' + content

    return content + '\n'


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


def copy_wrapper(task_dir, force=False):
    """Copy sgonly_verifier_wrapper.sh to the task's tests/ directory.

    With force=True, overwrites existing wrappers (needed to push v2 wrapper).
    """
    tests_dir = task_dir / "tests"
    if not tests_dir.exists():
        return False
    dest = tests_dir / "sgonly_verifier_wrapper.sh"
    if dest.exists() and not force:
        # Check if content differs — update if so
        if WRAPPER_SRC.exists() and dest.read_text() == WRAPPER_SRC.read_text():
            return False
    if WRAPPER_SRC.exists():
        dest.write_text(WRAPPER_SRC.read_text())
        dest.chmod(0o755)
        return True
    return False


def main():
    dry_run = '--dry-run' in sys.argv
    verbose = '--verbose' in sys.argv or '-v' in sys.argv
    force = '--force' in sys.argv

    active_tasks = get_active_task_ids()
    print(f"Active tasks: {len(active_tasks)}")
    if force:
        print("Force mode: regenerating ALL Dockerfile.sg_only files")

    generated = 0
    skipped = 0
    guards_added = 0
    wrappers_copied = 0
    wrappers_updated = 0
    artifact_generated = 0
    artifact_baseline_generated = 0
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
        artifact_only = env_dir / "Dockerfile.artifact_only"
        artifact_baseline = env_dir / "Dockerfile.artifact_baseline"

        if sgonly.exists() and not force:
            skipped += 1
            # Even if sg_only exists, check if artifact variants need generation
            # for MCP-unique suites (ccb_mcp_*)
            if suite.startswith("ccb_mcp") and dockerfile.exists():
                try:
                    dockerfile_text = dockerfile.read_text()
                    if not artifact_only.exists():
                        art_content = generate_artifact_only_mcp(task_dir, dockerfile_text)
                        if not dry_run:
                            artifact_only.write_text(art_content)
                            artifact_generated += 1
                            if verbose:
                                print(f"  GENERATED {task_id} (artifact_only)")
                        else:
                            print(f"  {'ARTIFACT-ONLY':>18} {suite:<25} {task_id}")
                    if not artifact_baseline.exists() or force:
                        abl_content = generate_artifact_baseline(task_dir, dockerfile_text)
                        if not dry_run:
                            artifact_baseline.write_text(abl_content)
                            artifact_baseline_generated += 1
                            if verbose:
                                print(f"  GENERATED {task_id} (artifact_baseline)")
                        else:
                            print(f"  {'ARTIFACT-BL':>18} {suite:<25} {task_id}")
                except Exception as e:
                    errors.append((task_id, f"artifact_only: {e}"))
            else:
                # In non-force mode, still update wrapper if it exists and differs
                if has_sgonly_wrapper(task_dir) and WRAPPER_SRC.exists():
                    if copy_wrapper(task_dir, force=False):
                        wrappers_updated += 1
            continue

        if not dockerfile.exists():
            if verbose:
                print(f"  SKIP {task_id}: no Dockerfile")
            continue

        dockerfile_text = dockerfile.read_text()
        clone_type = detect_clone_type(dockerfile_text)
        # ccb-linux-base images need special handling: use same base but remove kernel source
        is_linux_base = (clone_type == 'ccb_linux_base')
        # ccb-repo-* images have repo pre-cloned; never write-only
        is_ccb_repo = (clone_type == 'ccb_repo')
        # Write-only if: no repo in baseline, OR verifier only checks output
        # (doc-gen, analysis tasks). Write-only gives the agent an empty
        # workspace so it must use MCP — no confusing truncated file trees.
        # ccb-repo-* tasks are never write-only (they have repos in the base image).
        # With --force, ignore existing wrapper files for classification (they may
        # be left over from a previous generation with different classification).
        write_only = (not is_linux_base) and (not is_ccb_repo) and (
            (clone_type == 'none') or is_write_only_verifier(task_dir, ignore_wrapper=force)
        )

        try:
            if is_linux_base:
                # ccb-linux-base has Claude Code pre-installed; remove kernel source for sg_only
                content = generate_ccb_linux_base_sgonly(task_dir, dockerfile_text)
                write_only_count += 1
                label = 'linux-base-sgonly'
            elif write_only:
                # No local code needed: minimal image, empty workspace
                content = generate_write_only(task_dir, dockerfile_text)
                write_only_count += 1
                label = 'write-only'
            else:
                # Verifier needs local code (compilation, test execution):
                # keep repo but truncate source files
                content = generate_build_requiring(task_dir, dockerfile_text)
                build_count += 1
                label = 'build-req'

            if dry_run:
                print(f"  {label.upper():>18} {suite:<25} {task_id}")
            else:
                sgonly.write_text(content)
                generated += 1
                if verbose:
                    print(f"  GENERATED {task_id} ({label})")

                # For build-requiring tasks, add verifier guard and wrapper
                if not write_only and not is_linux_base:
                    if inject_test_guard(task_dir):
                        guards_added += 1
                    if copy_wrapper(task_dir, force=force):
                        wrappers_copied += 1

            # For MCP-unique suites, also generate Dockerfile.artifact_only + artifact_baseline
            if suite.startswith("ccb_mcp"):
                if not artifact_only.exists() or force:
                    art_content = generate_artifact_only_mcp(task_dir, dockerfile_text)
                    if dry_run:
                        print(f"  {'ARTIFACT-ONLY':>18} {suite:<25} {task_id}")
                    else:
                        artifact_only.write_text(art_content)
                        artifact_generated += 1
                        if verbose:
                            print(f"  GENERATED {task_id} (artifact_only)")
                if not artifact_baseline.exists() or force:
                    abl_content = generate_artifact_baseline(task_dir, dockerfile_text)
                    if dry_run:
                        print(f"  {'ARTIFACT-BL':>18} {suite:<25} {task_id}")
                    else:
                        artifact_baseline.write_text(abl_content)
                        artifact_baseline_generated += 1
                        if verbose:
                            print(f"  GENERATED {task_id} (artifact_baseline)")

        except Exception as e:
            errors.append((task_id, str(e)))
            print(f"  ERROR {task_id}: {e}")

    print(f"\n{'DRY RUN - ' if dry_run else ''}Summary:")
    print(f"  Already had sg_only: {skipped}")
    print(f"  Generated sg_only: {generated} ({write_only_count} write-only, {build_count} build-requiring)")
    print(f"  Generated artifact_only: {artifact_generated}")
    print(f"  Generated artifact_baseline: {artifact_baseline_generated}")
    print(f"  test.sh guards added: {guards_added}")
    print(f"  Wrappers copied: {wrappers_copied}")
    if wrappers_updated:
        print(f"  Wrappers updated (content changed): {wrappers_updated}")
    if errors:
        print(f"  Errors: {len(errors)}")
        for tid, err in errors:
            print(f"    {tid}: {err}")


if __name__ == '__main__':
    main()
