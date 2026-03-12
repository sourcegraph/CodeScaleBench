---
name: mine-tasks
description: Point at any repo (GitHub, GitLab, Bitbucket, Azure DevOps, self-hosted, or local) and get eval tasks that compare baseline coding agents vs MCP-augmented agents. Mines merged PRs/MRs for real code-change tasks, auto-generates ground truth from patches, produces runnable Docker environments for both configs. Works with private repos on any host. Triggers on mine tasks, propose tasks, discover tasks, find tasks, analyze repo for tasks, eval my repo, benchmark my repo.
user-invocable: true
---

# Mine Tasks

Point at a codebase — on any code host or locally — and get a baseline-vs-MCP comparison for AI coding agents. Mines real merged PRs/MRs to create eval tasks where agents must reproduce known fixes/features, then measures whether MCP tools (code search, semantic indexing) help agents find the right code faster.

Works with GitHub, GitLab, Bitbucket, Azure DevOps, self-hosted Gitea/Forgejo, or plain local git repos.

**Two workflows:**

- **Quick eval** (default): Mine 5-10 SDLC tasks from merged PRs/MRs, auto-generate ground truth, produce runnable Dockerfiles, print `docker run` commands. ~10 minutes to a working eval.
- **Full mining**: Deep analysis for contributing tasks to CodeScaleBench. Includes org-scale tasks, scoring, reviewer extraction, and `/scaffold-task` integration.

---

## Host Adapter Reference

All host-specific operations go through a detected adapter. The skill auto-detects the host from the URL and uses the appropriate CLI/API. When no API is available, it falls back to git-only mode.

### Host Detection

| URL Pattern | Host | CLI | Adapter |
|-------------|------|-----|---------|
| `github.com/*` | GitHub | `gh` | `github` |
| `gitlab.com/*` or self-hosted with `/api/v4/` | GitLab | `glab` | `gitlab` |
| `bitbucket.org/*` | Bitbucket | `curl` (REST v2) | `bitbucket` |
| `dev.azure.com/*` or `*.visualstudio.com/*` | Azure DevOps | `az repos` | `azure` |
| `*.gitea.*` or `*.forgejo.*` or user-specified | Gitea/Forgejo | `curl` (REST) | `gitea` |
| Local path (no remote) | — | — | `git_only` |
| Any other remote | — | — | `git_only` |

### Merge Request Operations

The skill needs these operations from each host. "MR" is used generically below (= PR on GitHub/Bitbucket, MR on GitLab, PR on Azure DevOps).

#### List merged MRs

```bash
# GitHub
gh pr list --repo {REPO} --state merged --limit {LIMIT} \
  --json number,title,body,labels,files,additions,deletions,closedAt,mergedAt

# GitLab
glab mr list --repo {REPO} --state merged --per-page {LIMIT} \
  --output json

# Bitbucket
curl -s -u "${BB_USER}:${BB_APP_PASSWORD}" \
  "https://api.bitbucket.org/2.0/repositories/{REPO}/pullrequests?state=MERGED&pagelen={LIMIT}"

# Azure DevOps
az repos pr list --organization {ORG_URL} --project {PROJECT} \
  --repository {REPO_NAME} --status completed --top {LIMIT} --output json

# Gitea / Forgejo
curl -s -H "Authorization: token ${GITEA_TOKEN}" \
  "{GITEA_URL}/api/v1/repos/{OWNER}/{REPO}/pulls?state=closed&sort=updated&limit={LIMIT}"

# git-only fallback (no API)
git log --merges --oneline --since="6 months ago" -n {LIMIT}
# Or for repos that use squash merges:
git log --oneline --since="6 months ago" --grep="fix\|feat\|bug\|refactor" -n {LIMIT}
```

#### Get MR diff

```bash
# GitHub
gh pr diff {NUMBER} --repo {REPO}

# GitLab
glab mr diff {NUMBER} --repo {REPO}

# Bitbucket
curl -s -u "${BB_USER}:${BB_APP_PASSWORD}" \
  "https://api.bitbucket.org/2.0/repositories/{REPO}/pullrequests/{NUMBER}/diff"

# Azure DevOps
az repos pr diff --id {NUMBER} --organization {ORG_URL} --output json
# Or: query the commits and diff them
az repos pr list --id {NUMBER} --query "[].{source: sourceRefName, target: targetRefName}" --output json

# Gitea / Forgejo
curl -s -H "Authorization: token ${GITEA_TOKEN}" \
  "{GITEA_URL}/api/v1/repos/{OWNER}/{REPO}/pulls/{NUMBER}.diff"

# git-only fallback
git diff {BASE_COMMIT}..{MERGE_COMMIT}
```

#### Get MR metadata (base commit, merge commit, author, linked issue)

```bash
# GitHub
gh pr view {NUMBER} --repo {REPO} --json mergeCommit,baseRefOid,author,title,body,labels

# GitLab
glab mr view {NUMBER} --repo {REPO} --output json
# Linked issues: parsed from MR description ("Closes #123") or via API
glab api "projects/{PROJECT_ID}/merge_requests/{NUMBER}/closes_issues"

# Bitbucket
curl -s -u "${BB_USER}:${BB_APP_PASSWORD}" \
  "https://api.bitbucket.org/2.0/repositories/{REPO}/pullrequests/{NUMBER}"

# Azure DevOps
az repos pr show --id {NUMBER} --organization {ORG_URL} --output json
# Linked work items:
az repos pr work-item list --id {NUMBER} --organization {ORG_URL} --output json

# Gitea / Forgejo
curl -s -H "Authorization: token ${GITEA_TOKEN}" \
  "{GITEA_URL}/api/v1/repos/{OWNER}/{REPO}/pulls/{NUMBER}"

# git-only fallback
# Parse from merge commit message: "Merge pull request #N" or "Fixes #N"
git log --format="%H %s" --merges -n 50 | grep -i "fix\|feat\|bug\|refactor"
# Base commit = first parent of merge commit
git rev-parse {MERGE_COMMIT}^1
```

#### Get linked issue

```bash
# GitHub
gh issue view {ISSUE_NUMBER} --repo {REPO} --json body,title,labels

# GitLab
glab issue view {ISSUE_NUMBER} --repo {REPO} --output json

# Bitbucket (Jira integration — limited)
# Parse from PR description; Bitbucket issues API is deprecated for most repos

# Azure DevOps
az boards work-item show --id {WORK_ITEM_ID} --organization {ORG_URL} --output json

# Gitea / Forgejo
curl -s -H "Authorization: token ${GITEA_TOKEN}" \
  "{GITEA_URL}/api/v1/repos/{OWNER}/{REPO}/issues/{ISSUE_NUMBER}"

# git-only fallback
# No issue data available — use the commit message as the task description
git log --format="%B" -1 {MERGE_COMMIT}
```

### Clone URLs and Auth

| Host | Public Clone | Private Clone (Docker build secret) |
|------|-------------|-------------------------------------|
| GitHub | `https://github.com/{REPO}.git` | `https://x-access-token:${TOKEN}@github.com/{REPO}.git` |
| GitLab | `https://gitlab.com/{REPO}.git` | `https://oauth2:${TOKEN}@gitlab.com/{REPO}.git` |
| Bitbucket | `https://bitbucket.org/{REPO}.git` | `https://x-token-auth:${TOKEN}@bitbucket.org/{REPO}.git` |
| Azure DevOps | `https://dev.azure.com/{ORG}/{PROJECT}/_git/{REPO}` | `https://user:${TOKEN}@dev.azure.com/{ORG}/{PROJECT}/_git/{REPO}` |
| Gitea/Forgejo | `https://{HOST}/{REPO}.git` | `https://user:${TOKEN}@{HOST}/{REPO}.git` |
| Self-hosted GitLab | `https://{HOST}/{REPO}.git` | `https://oauth2:${TOKEN}@{HOST}/{REPO}.git` |

The Dockerfile `{CLONE_COMMAND}` uses the detected host's pattern. The secret name is always `repo_token` (host-agnostic):

```dockerfile
# Public
RUN git clone --filter=blob:none {PUBLIC_CLONE_URL} /workspace && \
    cd /workspace && git checkout {BASE_COMMIT}

# Private (any host)
# Requires: docker build --secret id=repo_token,env=REPO_TOKEN .
RUN --mount=type=secret,id=repo_token \
    REPO_TOKEN=$(cat /run/secrets/repo_token) && \
    git clone --filter=blob:none {PRIVATE_CLONE_URL_TEMPLATE} /workspace && \
    cd /workspace && git checkout {BASE_COMMIT}
```

### Repo Validation

```bash
# Universal (works with any host)
git ls-remote {CLONE_URL} HEAD 2>/dev/null

# GitHub
gh repo view {REPO} --json name,isPrivate 2>/dev/null

# GitLab
glab repo view {REPO} --output json 2>/dev/null

# Others: git ls-remote is sufficient
```

### Contributor Discovery

```bash
# Universal (works with any host, no API needed)
# Top contributors for a path — this is the primary method
git -C {LOCAL_REPO} log --format='%an' --since="12 months ago" -- {PATH} \
  | sort | uniq -c | sort -rn | head -10

# GitHub (richer data: PR reviewers)
gh api repos/{REPO}/pulls/{NUMBER}/reviews --jq '.[].user.login'
gh api "repos/{REPO}/commits?path={PATH}&per_page=30" --jq '.[].author.login'

# GitLab (MR approvers)
glab api "projects/{PROJECT_ID}/merge_requests/{NUMBER}/approvals" --jq '.approved_by[].user.username'

# Azure DevOps (PR reviewers)
az repos pr reviewer list --id {NUMBER} --organization {ORG_URL} --output json

# Bitbucket (PR participants)
curl -s -u "${BB_USER}:${BB_APP_PASSWORD}" \
  "https://api.bitbucket.org/2.0/repositories/{REPO}/pullrequests/{NUMBER}" \
  | jq '.participants[] | select(.role == "REVIEWER") | .user.display_name'
```

---

## Phase 0: Eval Goals

Ask the user:

**Question 1** — Header: "What are you evaluating?"
- Question: "What do you want to measure?"
- Options:
  - **Quick eval: baseline vs MCP** — "Mine 5-10 tasks from my repo, auto-generate ground truth, get a runnable comparison in minutes"
  - **Full benchmark mining** — "Deep analysis for CodeScaleBench contribution — SDLC tasks, org-scale tasks, reviewer extraction, the works"

If **Quick eval**, set `QUICK_MODE=true`. Skip detailed questions — use sensible defaults (SDLC only, auto-discover, 5-10 tasks). Proceed to Phase 1 with just the repo source question.

If **Full mining**, set `QUICK_MODE=false`. Proceed to Phase 1 with all questions.

**Question 2** — Header: "MCP provider"
- Question: "Which MCP provider will the augmented agent use?"
- Options:
  - **Sourcegraph** — "Sourcegraph code search (keyword + semantic search via MCP server). Works with any code host."
  - **Custom MCP server** — "I'll provide my own MCP config JSON"
  - **Not sure yet** — "Generate both Dockerfiles, I'll configure MCP later"

Record the selection as `{MCP_PROVIDER}`. If "Custom MCP server", prompt for the MCP config JSON (or path to a `.mcp.json` file). If "Not sure yet", generate Dockerfiles with a placeholder MCP config and clear instructions for how to fill it in.

---

## Phase 1: Codebase Input

Ask the user:

**Question 1** — Header: "Codebase source"
- Question: "Which repo(s) should I analyze?"
- Options:
  - **Repo URL** — "Any git host: GitHub, GitLab, Bitbucket, Azure DevOps, Gitea, self-hosted — paste the URL"
  - **Multiple repos** — "Comma-separated URLs or owner/repo pairs (can mix hosts)"
  - **Local path** — "Absolute path to a locally cloned repo"

Collect the URL(s) or path.

#### Host Detection Logic

For each URL provided, detect the host:

```
https://github.com/owner/repo          → host=github, repo=owner/repo
https://gitlab.com/group/subgroup/repo → host=gitlab, repo=group/subgroup/repo
https://gitlab.mycompany.com/team/repo → host=gitlab_selfhosted, base=gitlab.mycompany.com, repo=team/repo
https://bitbucket.org/owner/repo       → host=bitbucket, repo=owner/repo
https://dev.azure.com/org/project/_git/repo → host=azure, org=org, project=project, repo=repo
https://gitea.example.com/owner/repo   → host=gitea, base=gitea.example.com, repo=owner/repo
owner/repo (no host)                   → prompt: "Which host? (github/gitlab/bitbucket/other)"
/path/to/local/repo                    → host=local, check for remote: git -C /path remote get-url origin
```

For self-hosted instances, ask which platform it runs (GitLab, Gitea, Forgejo, plain git) if not auto-detectable.

#### Validate Access

```bash
# Universal — works for any host
git ls-remote {CLONE_URL} HEAD 2>/dev/null && echo "accessible" || echo "inaccessible"
```

If inaccessible, check if it's a private repo:
- Suggest authenticating with the host's CLI (`gh auth login`, `glab auth login`, etc.)
- Or suggest using a local clone instead

If the repo is private, set `{PRIVATE_REPO}=true`.

**If QUICK_MODE**: skip remaining questions, set mining mode to SDLC, constraints to auto-discover, target 5-10 tasks. Go to Phase 2.

**Question 2** — Header: "Mining mode" *(full mining only)*
- Question: "What kind of benchmark tasks should I look for?"
- Options:
  - **SDLC tasks** — "Mine closed MRs/PRs for real bug fixes, features, and refactors (agent must reproduce the code change)"
  - **Org-scale tasks** — "Analyze codebase structure for discovery, tracing, compliance, and comprehension tasks (agent produces answer artifacts)"
  - **Both** — "Run both analyses and propose a mixed set"

**Question 3** — Header: "Constraints" *(full mining only)*
- Question: "Any constraints on what to look for?"
- Options:
  - **Auto-discover** — "Let me analyze the repo and propose the best candidates"
  - **Specific area** — "Focus on a specific package, module, or subsystem (I'll specify)"
  - **Use cases provided** — "I have specific scenarios I want turned into tasks (I'll list them)"

If "Specific area", prompt for the package/module path.
If "Use cases provided", prompt for a list of use case descriptions (free text).

---

## Phase 2: Codebase Reconnaissance

Before mining, gather structural information about the repo(s).

### Step 2a: Repo Metadata

Use the detected host adapter:

```bash
# GitHub
gh repo view {REPO} --json name,primaryLanguage,languages,defaultBranchRef,diskUsage,description,isPrivate

# GitLab
glab repo view {REPO} --output json

# Others or local: use git directly
git -C {REPO_PATH} log --oneline -1
# Detect primary language by file extension count
find {REPO_PATH} -type f \( -name '*.go' -o -name '*.py' -o -name '*.ts' -o -name '*.java' \
  -o -name '*.cpp' -o -name '*.rs' -o -name '*.cs' -o -name '*.rb' \) \
  | sed 's/.*\.//' | sort | uniq -c | sort -rn | head -3
```

Record: primary language, approximate size (LOC / disk), default branch, description, private/public.

### Step 2b: Structure Analysis

For local repos or after cloning:

```bash
# Top-level directory structure
ls -d */

# Find key build/config patterns
find . -name 'go.mod' -o -name 'package.json' -o -name 'Cargo.toml' -o -name 'setup.py' \
  -o -name 'pyproject.toml' -o -name '*.csproj' -o -name 'build.gradle' -o -name 'pom.xml' | head -20

# For Go: module path and key packages
head -5 go.mod 2>/dev/null
ls cmd/ pkg/ internal/ 2>/dev/null

# For multi-repo: cross-repo import analysis
rg -l 'import.*other-repo-module' --type go 2>/dev/null | head -20
```

### Step 2c: Code Search Tools (when available)

If Sourcegraph MCP tools are available (`SOURCEGRAPH_ACCESS_TOKEN` set), use them for deeper analysis. Sourcegraph works with repos on any host.

If neither Sourcegraph nor Deep Search is available, fall back to local `rg`/`grep` analysis. This is fine — mining works without any external tools.

---

## Phase 3: SDLC Task Mining

Skip this phase if user selected "Org-scale tasks" only.

### Step 3a: Find Candidate MRs

Use the detected host adapter to list merged MRs. See "List merged MRs" in the Host Adapter Reference.

**For git-only mode** (no API available): mine directly from git history.

```bash
# Find merge commits (standard merge workflow)
git log --merges --format="%H|%P|%s" --since="6 months ago" -n 100

# Find squash-merge commits (common in GitHub/GitLab)
git log --no-merges --format="%H|%s" --since="6 months ago" -n 100 \
  | grep -iE "(fix|feat|bug|refactor|resolve|patch|add|implement)"

# For each candidate commit, get file count and line changes
git diff --stat {COMMIT}~1..{COMMIT} | tail -1
```

In git-only mode, you won't have issue/MR descriptions — use commit messages as task descriptions and `git diff` for patches.

Filter for good eval candidates:
- Patch touches 1-15 files (not too small, not too large)
- Has test changes (indicates verifiable fix)
- Not a dependency bump, CI change, or trivial typo fix
- Has a clear problem description (from MR body or commit message)

**For QUICK_MODE**: limit to 30 recent MRs/commits, pick the top 5-10 by suitability score.

### Step 3b: Score and Rank Candidates

For each candidate, compute a suitability score:

| Criterion | Weight | Scoring |
|-----------|--------|---------|
| Patch size (files changed) | 0.25 | 1-3 files: 1.0, 4-8: 0.8, 9-15: 0.6, >15: 0.2 |
| Has test changes | 0.20 | Yes with fail-to-pass: 1.0, Yes: 0.7, No: 0.2 |
| Issue/MR description quality | 0.20 | Clear repro steps: 1.0, Good description: 0.7, Minimal/commit-only: 0.3 |
| Code complexity | 0.15 | Non-trivial logic: 1.0, Config/docs: 0.3, Trivial: 0.1 |
| Language diversity | 0.10 | Underrepresented in CSB: 1.0, Well-covered: 0.5 |
| Recency | 0.10 | <3 months: 1.0, 3-6 months: 0.8, 6-12 months: 0.6 |

### Step 3c: Classify Task Category

| Signal | Category |
|--------|----------|
| Labels/tags: bug, fix, hotfix, regression | `bug_fix` |
| Labels/tags: feature, enhancement, feat | `feature` |
| Labels/tags: refactor, cleanup, tech-debt | `refactoring` |
| Labels/tags: test, testing, coverage | `test` |
| Labels/tags: docs, documentation | `documentation` |
| Labels/tags: security, CVE, vulnerability | `security` |
| MR/commit title: "fix", "resolve", "patch" | `bug_fix` |
| MR/commit title: "add", "implement", "support" | `feature` |
| MR/commit title: "refactor", "clean", "simplify" | `refactoring` |

In git-only mode, classify based on commit message keywords only (no labels available).

### Step 3d: Extract Task Details + Ground Truth

Use the detected host adapter to get MR metadata. See "Get MR metadata" and "Get MR diff" in the Host Adapter Reference.

**For git-only mode:**

```bash
# Base commit = parent of the fix commit
BASE_COMMIT=$(git rev-parse {FIX_COMMIT}~1)

# Full diff
git diff {BASE_COMMIT}..{FIX_COMMIT}

# Files changed
git diff --name-status {BASE_COMMIT}..{FIX_COMMIT}

# Commit message as task description
git log --format="%B" -1 {FIX_COMMIT}
```

#### Auto-Generate Ground Truth

For each selected MR/commit, automatically generate ground truth from the patch:

```bash
# Extract files changed (works for any host — uses git directly)
git diff --name-status {BASE_COMMIT}..{MERGE_COMMIT}

# Extract full diff for verification
git diff {BASE_COMMIT}..{MERGE_COMMIT} > /tmp/task.patch

# Count additions/deletions
git diff --stat {BASE_COMMIT}..{MERGE_COMMIT} | tail -1
```

Generate `ground_truth.json`:

```json
{
  "files": [
    {
      "path": "pkg/server/handler.go",
      "status": "modified"
    },
    {
      "path": "pkg/server/handler_test.go",
      "status": "modified"
    }
  ],
  "patch_stats": {
    "additions": 45,
    "deletions": 12,
    "files_changed": 2
  },
  "source": {
    "type": "merge_request",
    "host": "{DETECTED_HOST}",
    "number": 1234,
    "url": "{MR_URL}",
    "merge_commit": "abc123",
    "base_commit": "def456"
  }
}
```

Note: `source.type` is `"merge_request"` for MR/PR-based tasks, `"commit"` for git-only tasks (where `number` and `url` may be null).

Generate `test.sh` that verifies the agent's changes:

```bash
#!/bin/bash
set -e
cd /workspace

mkdir -p /logs/verifier
git config --global --add safe.directory /workspace 2>/dev/null || true

# Check if any changes were made
CHANGES=$(git diff --stat 2>/dev/null | wc -l)
STAGED=$(git diff --cached --stat 2>/dev/null | wc -l)
UNTRACKED=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)
if [ "$CHANGES" -eq 0 ] && [ "$STAGED" -eq 0 ] && [ "$UNTRACKED" -eq 0 ]; then
    echo "No changes detected"
    echo "0.0" > /logs/verifier/reward.txt
    exit 0
fi

SCORE=0
MAX_SCORE=10

# Check 1: Expected files were modified (5 points)
EXPECTED_FILES=({EXPECTED_FILE_LIST})
MODIFIED=0
for f in "${EXPECTED_FILES[@]}"; do
    if git diff --name-only | grep -q "$f" || \
       git diff --cached --name-only | grep -q "$f" || \
       git log --oneline HEAD~1..HEAD --name-only 2>/dev/null | grep -q "$f"; then
        MODIFIED=$((MODIFIED + 1))
    fi
done
FILE_SCORE=$(awk "BEGIN {printf \"%.0f\", 5 * $MODIFIED / ${#EXPECTED_FILES[@]}}")
SCORE=$((SCORE + FILE_SCORE))
echo "Files modified: $MODIFIED/${#EXPECTED_FILES[@]} (${FILE_SCORE}/5 points)"

# Check 2: Tests pass (5 points)
# {LANGUAGE_SPECIFIC_TEST_COMMAND}
if {TEST_COMMAND} 2>&1; then
    echo "PASS: Tests pass"
    SCORE=$((SCORE + 5))
else
    echo "FAIL: Tests failed"
fi

FINAL_SCORE=$(awk "BEGIN {printf \"%.1f\", $SCORE / $MAX_SCORE}")
echo "$FINAL_SCORE" > /logs/verifier/reward.txt
echo "Score: $FINAL_SCORE (${SCORE}/${MAX_SCORE})"
```

Fill in `{EXPECTED_FILE_LIST}` from the changed files and `{TEST_COMMAND}` based on the language:

| Language | Test Command |
|----------|-------------|
| Go | `go test ./... -count=1 -timeout 120s` |
| Python | `python -m pytest -x --timeout=120` |
| TypeScript | `npm test` or `npx jest --forceExit` |
| Java | `./gradlew test` or `mvn test` |
| Rust | `cargo test` |
| C++ | `cmake --build build && ctest --test-dir build` |
| C# | `dotnet test` |
| Ruby | `bundle exec rake test` |

### Step 3e: Generate Dockerfiles (Baseline + MCP)

For each task, generate **two** Dockerfiles. Clone URLs and auth are determined by the detected host — see "Clone URLs and Auth" in the Host Adapter Reference.

#### Dockerfile.baseline — Full code, no MCP

```dockerfile
FROM {BASE_IMAGE}

RUN apt-get update && apt-get install -y git curl ripgrep && rm -rf /var/lib/apt/lists/*

# Install Node.js (for Claude Code CLI)
RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi
RUN npm install -g @anthropic-ai/claude-code

# Clone repo at the pre-fix commit
{CLONE_COMMAND}

RUN mkdir -p /workspace/tests /logs/verifier
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
```

`{CLONE_COMMAND}` uses the host-specific URL pattern:

**Public (any host):**
```dockerfile
RUN git clone --filter=blob:none {CLONE_URL} /workspace && \
    cd /workspace && git checkout {BASE_COMMIT}
```

**Private (any host):**
```dockerfile
# Requires: docker build --secret id=repo_token,env=REPO_TOKEN .
RUN --mount=type=secret,id=repo_token \
    REPO_TOKEN=$(cat /run/secrets/repo_token) && \
    git clone --filter=blob:none {AUTHENTICATED_CLONE_URL} /workspace && \
    cd /workspace && git checkout {BASE_COMMIT}
```

Where `{AUTHENTICATED_CLONE_URL}` is the host-specific pattern from the Clone URLs table (e.g., `https://oauth2:${REPO_TOKEN}@gitlab.com/...` for GitLab, `https://x-access-token:${REPO_TOKEN}@github.com/...` for GitHub).

#### Dockerfile.mcp — Truncated code + MCP tools

```dockerfile
FROM {BASE_IMAGE}

RUN apt-get update && apt-get install -y git curl ripgrep jq && rm -rf /var/lib/apt/lists/*

RUN if ! command -v node &> /dev/null; then \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs; \
    fi
RUN npm install -g @anthropic-ai/claude-code

# Clone repo (will be truncated below)
{CLONE_COMMAND}

# Truncate source files to stubs (signatures only, no bodies)
# This forces the agent to use MCP tools to understand the code
RUN find /workspace -type f \( -name '*.go' -o -name '*.py' -o -name '*.ts' -o -name '*.java' \
    -o -name '*.cpp' -o -name '*.rs' -o -name '*.c' -o -name '*.h' -o -name '*.cs' -o -name '*.rb' \) \
    -exec sh -c 'head -50 "$1" > "$1.stub" && mv "$1.stub" "$1"' _ {} \;

# MCP configuration
{MCP_CONFIG_BLOCK}

RUN mkdir -p /workspace/tests /logs/verifier
COPY tests/ /workspace/tests/
RUN chmod +x /workspace/tests/test.sh

WORKDIR /workspace
```

`{MCP_CONFIG_BLOCK}` depends on the provider selected in Phase 0:

**Sourcegraph** (works with any code host):
```dockerfile
RUN mkdir -p /root/.config/claude && \
    echo '{"mcpServers":{"sourcegraph":{"command":"npx","args":["-y","@sourcegraph/mcp-server"],"env":{"SRC_ACCESS_TOKEN":"__SG_TOKEN__","SOURCEGRAPH_URL":"__SG_URL__"}}}}' \
    > /root/.config/claude/mcp.json
```

**Custom MCP:**
```dockerfile
COPY mcp.json /root/.config/claude/mcp.json
```

**Placeholder (not sure yet):**
```dockerfile
# TODO: Add your MCP configuration here
# Create /root/.config/claude/mcp.json with your MCP server config
# See https://docs.anthropic.com/en/docs/claude-code/mcp for format
RUN mkdir -p /root/.config/claude && \
    echo '{"mcpServers":{}}' > /root/.config/claude/mcp.json
```

### Step 3f: Extract Reviewer Information *(full mining only)*

Use the detected host adapter for reviewer data. See "Contributor Discovery" in the Host Adapter Reference.

The **git log method** works universally regardless of host:

```bash
# Top contributors for changed paths (works everywhere)
for path in {CHANGED_DIRS}; do
    git -C {REPO_PATH} log --format='%an' --since="12 months ago" -- "$path" \
      | sort | uniq -c | sort -rn | head -5
done
```

For hosts with reviewer APIs (GitHub, GitLab, Azure DevOps), also pull MR reviewer data for richer results.

Filter out bot accounts (dependabot, renovate, bors, k8s-ci-robot, gitlab-bot, etc.).

### Difficulty Estimation

| Files Changed | Lines Changed | Cross-Package | Difficulty |
|---------------|---------------|---------------|------------|
| 1-2 | <50 | No | medium |
| 1-3 | 50-200 | No | hard |
| 3-8 | 50-500 | Yes | hard |
| 4-10 | 200-1000 | Yes | very_hard |
| 10+ | 500+ | Yes | expert |

---

## Phase 4: Org-Scale Task Mining *(full mining only)*

Skip this phase in quick eval mode or if user selected "SDLC tasks" only.

### Step 4a: Cross-Repo Dependency Analysis

For multi-repo inputs, identify cross-repo relationships:

```bash
# Go: find cross-module imports
rg 'import.*"(other-org/other-repo)' --type go -l

# Python: find cross-package imports
rg 'from (other_package) import|import (other_package)' --type py -l

# Proto/gRPC: find proto imports across repos
rg 'import ".*\.proto"' --type proto -l

# JS/TS: find cross-package requires/imports
rg "require\('(@other-org|other-package)" --type js -l

# C#: find cross-project references
rg 'using\s+(OtherProject)' --type cs -l
find . -name '*.csproj' -exec grep -l 'ProjectReference' {} \;
```

For single repos, analyze internal module boundaries:

```bash
# Go: list internal packages and their importers
go list ./... 2>/dev/null | head -50
rg 'import.*".*internal/' --type go -l | head -20

# Find interface definitions (potential tracing targets)
rg '(type|interface|trait|abstract class)\s+\w+' --type go --type java --type py -l | head -30
```

### Step 4b: Identify Org-Scale Task Patterns

| Pattern | Task Family | Detection Method |
|---------|-------------|-----------------|
| Shared proto/IDL definitions | `cross-repo-dep-trace` | Find `.proto` files imported across repos |
| Shared library packages | `cross-repo-dep-trace` | Find packages imported by 3+ consumers |
| Config propagation chains | `cross-repo-config-trace` | Find config structs used across module boundaries |
| API surface definitions | `onboarding-comprehension` | Find exported interfaces/types in `pkg/` or `api/` |
| Deprecated APIs | `migration-inventory` | Find `@Deprecated`, `// Deprecated:`, `#[deprecated]` |
| Security-sensitive patterns | `compliance-audit` | Find TLS configs, auth middleware, secret handling |
| Error handling chains | `incident-debug` | Find error types that propagate across packages |
| Plugin/extension points | `platform-knowledge` | Find plugin registries, factory patterns, hook systems |
| Domain model relationships | `domain-lineage` | Find entity types and their relationships |

### Step 4c: Generate Org-Scale Proposals

For each identified pattern, propose a task with a natural-language question:

- **Cross-repo dep trace**: "Which {language} source files in the `{package}/` tree of `{repo}` directly import `{dependency}`?"
- **Config trace**: "Trace how the `{ConfigType}` configuration defined in `{repo1}` gets consumed by `{repo2}`."
- **Compliance audit**: "Find all files in `{repo}` that configure TLS/SSL settings."
- **Migration inventory**: "Find all uses of the deprecated `{API}` across `{repo1}` and `{repo2}`."
- **Incident debug**: "Given that `{ErrorType}` is being thrown at runtime, trace the error origin across `{repo1}` and `{repo2}`."
- **Onboarding comprehension**: "Explain the architecture of the `{subsystem}` in `{repo}`."

### Step 4d: Extract Reviewer Information for Org Tasks

Use `git log` frequency analysis (works for any host):

```bash
for repo_path in {REPO_PATHS}; do
  for area in {CODE_AREAS}; do
    git -C "$repo_path" log --format='%an' --since="12 months ago" -- "$area" \
      | sort | uniq -c | sort -rn | head -5
  done
done
```

---

## Phase 5: Feasibility Checks

### SDLC Feasibility

For each SDLC proposal:

1. **Commit exists**: `git ls-remote {CLONE_URL} {SHA} 2>/dev/null` or, for local repos, `git cat-file -t {SHA}`
2. **Repo is cloneable**: `git ls-remote {CLONE_URL} HEAD 2>/dev/null`
3. **Patch is self-contained**: No external service deps, no DB migrations, no CI artifacts required.
4. **No secrets in patch**: Diff doesn't contain API keys, tokens, or credentials.

### Org-Scale Feasibility *(full mining only)*

1. **Repos accessible**: All referenced repos exist and user has access.
2. **Oracle is deterministic**: The question has a concrete, verifiable answer (file lists, symbol names).
3. **Task is non-trivial**: Requires searching at least 3 files.

---

## Phase 6: Generate Output

### Quick Eval Mode

Write all task files to a single output directory:

```
{REPO_NAME}-eval/
  tasks/
    {task-id-1}/
      instruction.md          # Task description from issue/MR/commit
      ground_truth.json        # Auto-generated from patch
      environment/
        Dockerfile.baseline    # Full code, no MCP
        Dockerfile.mcp         # Truncated code + MCP tools
      tests/
        test.sh                # Verifier script
  run_eval.sh                  # One-command runner (see below)
  README.md                    # How to interpret results
```

#### Generate run_eval.sh

This is a standalone runner that doesn't require Harbor or Daytona:

```bash
#!/bin/bash
# Run baseline-vs-MCP eval for {REPO_NAME}
# Usage: ./run_eval.sh [--tasks N] [--timeout SECONDS]
#
# Required environment variables:
#   ANTHROPIC_API_KEY    — Claude API key
# For private repos:
#   REPO_TOKEN           — Git host access token (GitHub PAT, GitLab token, etc.)
# Optional (for MCP variant):
#   {MCP_ENV_VARS}       — Provider-specific tokens

set -euo pipefail

TASKS_DIR="$(cd "$(dirname "$0")/tasks" && pwd)"
RESULTS_DIR="$(cd "$(dirname "$0")" && pwd)/results"
TIMEOUT="${2:-900}"
mkdir -p "$RESULTS_DIR"

TASK_DIRS=($(ls -d "$TASKS_DIR"/*/))

echo "=== {REPO_NAME} Eval ==="
echo "Tasks: ${#TASK_DIRS[@]}"
echo "Timeout per task: ${TIMEOUT}s"
echo ""

# Build args for private repos
BUILD_SECRET_ARGS=""
if [ -n "${REPO_TOKEN:-}" ]; then
    BUILD_SECRET_ARGS="--secret id=repo_token,env=REPO_TOKEN"
fi

for task_dir in "${TASK_DIRS[@]}"; do
    task_id=$(basename "$task_dir")
    echo "--- Task: $task_id ---"

    for config in baseline mcp; do
        dockerfile="$task_dir/environment/Dockerfile.$config"
        if [ ! -f "$dockerfile" ]; then
            echo "  SKIP $config (no Dockerfile)"
            continue
        fi

        result_dir="$RESULTS_DIR/$task_id/$config"
        mkdir -p "$result_dir"

        echo "  Building $config image..."
        docker build -f "$dockerfile" -t "eval-${task_id}-${config}" \
            $BUILD_SECRET_ARGS \
            "$task_dir/environment/" 2>"$result_dir/build.log" || {
            echo "  FAIL: build error (see $result_dir/build.log)"
            continue
        }

        echo "  Running $config agent (timeout: ${TIMEOUT}s)..."
        timeout "$TIMEOUT" docker run --rm \
            -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
            -v "$result_dir:/logs" \
            "eval-${task_id}-${config}" \
            bash -c "
                claude --print-only-result \
                    'Read /workspace/tests/instruction.md and complete the task. When done, run: bash /workspace/tests/test.sh' \
                    2>/logs/agent.log || true
                bash /workspace/tests/test.sh 2>&1 | tee /logs/test_output.log
            " 2>"$result_dir/run.log" || {
            echo "  TIMEOUT or error"
            echo "0.0" > "$result_dir/reward.txt"
        }

        # Extract score
        if [ -f "$result_dir/reward.txt" ]; then
            score=$(cat "$result_dir/reward.txt")
        else
            score="0.0"
        fi
        echo "  $config score: $score"

        # Cleanup image
        docker rmi "eval-${task_id}-${config}" 2>/dev/null || true
    done
    echo ""
done

# Print summary
echo "=== Results Summary ==="
echo ""
printf "%-40s %-10s %-10s %-10s\n" "Task" "Baseline" "MCP" "Delta"
printf "%-40s %-10s %-10s %-10s\n" "----" "--------" "---" "-----"

total_bl=0
total_mcp=0
count=0

for task_dir in "${TASK_DIRS[@]}"; do
    task_id=$(basename "$task_dir")
    bl_score=$(cat "$RESULTS_DIR/$task_id/baseline/reward.txt" 2>/dev/null || echo "N/A")
    mcp_score=$(cat "$RESULTS_DIR/$task_id/mcp/reward.txt" 2>/dev/null || echo "N/A")

    if [ "$bl_score" != "N/A" ] && [ "$mcp_score" != "N/A" ]; then
        delta=$(awk "BEGIN {printf \"%.1f\", $mcp_score - $bl_score}")
        total_bl=$(awk "BEGIN {print $total_bl + $bl_score}")
        total_mcp=$(awk "BEGIN {print $total_mcp + $mcp_score}")
        count=$((count + 1))
    else
        delta="N/A"
    fi

    printf "%-40s %-10s %-10s %-10s\n" "$task_id" "$bl_score" "$mcp_score" "$delta"
done

if [ "$count" -gt 0 ]; then
    avg_bl=$(awk "BEGIN {printf \"%.2f\", $total_bl / $count}")
    avg_mcp=$(awk "BEGIN {printf \"%.2f\", $total_mcp / $count}")
    avg_delta=$(awk "BEGIN {printf \"%.2f\", ($total_mcp - $total_bl) / $count}")
    echo ""
    printf "%-40s %-10s %-10s %-10s\n" "AVERAGE ($count tasks)" "$avg_bl" "$avg_mcp" "$avg_delta"
fi
```

Present the output directory and print the commands:

```
Quick Eval Ready!

  Output:  {REPO_NAME}-eval/
  Tasks:   {N} tasks mined from {REPO}
  Host:    {DETECTED_HOST}

To run the eval:

  export ANTHROPIC_API_KEY=sk-...
  # For private repos:
  export REPO_TOKEN=...          # Your {HOST_NAME} access token
  # For Sourcegraph MCP:
  export SOURCEGRAPH_ACCESS_TOKEN=sgp_...
  export SOURCEGRAPH_URL=https://sourcegraph.com

  cd {REPO_NAME}-eval
  bash run_eval.sh

Results will be written to {REPO_NAME}-eval/results/
```

### Full Mining Mode

Present proposals in a summary table:

```
=== SDLC Task Proposals ===

| # | Task ID | Category | Difficulty | Files | Score | Source |
|---|---------|----------|------------|-------|-------|--------|
| 1 | myrepo-leak-fix-001 | bug_fix | hard | 3 | 0.92 | MR !1234 |
| 2 | myrepo-auth-feat-001 | feature | medium | 2 | 0.85 | PR #5678 |

=== Org-Scale Task Proposals ===

| # | Task ID | Category | Difficulty | Repos | Pattern | Confidence |
|---|---------|----------|------------|-------|---------|------------|
| 1 | myrepo-dep-trace-001 | cross-repo-dep-trace | hard | 3 | shared_lib | high |
```

Then ask:

**Question** — Header: "Selection"
- Question: "Which proposals should I scaffold? (Enter numbers, 'all', or 'none')"

For each selected proposal, invoke `/scaffold-task` with pre-filled values.

---

## Phase 7: Summary

### Quick Eval Summary

```
Mining Complete
  Source:     {REPO_URL}
  Host:       {DETECTED_HOST}
  Language:   {LANGUAGE}
  MRs analyzed: {N}
  Tasks generated: {M}

Tasks:
  1. {task-id-1}  ({category}, {difficulty}) — MR !{NUM}
  2. {task-id-2}  ({category}, {difficulty}) — commit {SHORT_SHA}
  ...

Output: {REPO_NAME}-eval/

Run:
  export ANTHROPIC_API_KEY=sk-...
  cd {REPO_NAME}-eval && bash run_eval.sh
```

### Full Mining Summary

```
Mining Summary
  Source:     {REPO_URL} (+ N other repos)
  Host(s):   {DETECTED_HOSTS}
  Language:   {LANGUAGE}
  Analyzed:   {N} merged MRs, {M} cross-repo patterns

  SDLC proposals:      {A} found, {B} feasible, {C} scaffolded
  Org-scale proposals:  {D} found, {E} feasible, {F} scaffolded

Scaffolded tasks:
  1. myrepo-leak-fix-001   → benchmarks/csb_sdlc_fix/myrepo-leak-fix-001/
  2. myrepo-dep-trace-001  → benchmarks/csb_org_crossrepo/myrepo-dep-trace-001/

Next steps:
  1. Review instruction.md for each task — fill in TODOs
  2. Review reviewers.json — verify suggested reviewers are accurate
  3. Customize test.sh / oracle_checks.py with task-specific verification
  4. For SDLC tasks: verify the ground_truth_rev produces a passing test
  5. For org-scale tasks: populate task_spec.json with oracle checks
  6. Run /validate-tasks on each scaffolded task
```

---

## Language → Base Image Mapping

| Language | Base Image |
|----------|-----------|
| go | `golang:1.23-bookworm` |
| python | `python:3.11-bookworm` |
| cpp | `gcc:13-bookworm` |
| rust | `rust:1.75-bookworm` |
| typescript | `node:20-bookworm` |
| java | `eclipse-temurin:21-bookworm` |
| c | `gcc:13-bookworm` |
| csharp | `mcr.microsoft.com/dotnet/sdk:8.0` |
| ruby | `ruby:3.3-bookworm` |
| mixed | `ubuntu:22.04` |

---

## Fallback Strategies

### No host CLI available (no `gh`, `glab`, `az`)
- Fall back to **git-only mode** automatically.
- Mine from `git log` — merge commits and commit messages.
- No issue/MR descriptions — use commit messages as task descriptions.
- No reviewer API data — use `git log --format='%an'` for contributors.
- This is fully functional for generating eval tasks.

### Host CLI present but not authenticated
- Suggest: `gh auth login` / `glab auth login` / `az login` as appropriate.
- If user declines, fall back to git-only mode.
- Org-scale mining works with local repo analysis regardless.

### Private repo without auth
- Dockerfiles can't clone without a token.
- Print instructions: `docker build --secret id=repo_token,env=REPO_TOKEN .`
- Explain which token type is needed for their host (GitHub PAT, GitLab token, Bitbucket app password, Azure PAT).
- Alternatively, suggest cloning locally and using the "Local path" input.

### Mixed hosts (e.g., GitHub + GitLab repos)
- Detect host per-repo independently — each repo gets its own adapter.
- Clone URLs and auth patterns are per-repo, not global.
- The `REPO_TOKEN` secret in Dockerfiles works if both hosts use the same token (unlikely). For mixed-auth scenarios, generate separate secrets: `--secret id=github_token --secret id=gitlab_token`.

### No MCP provider configured
- Generate Dockerfile.baseline only and placeholder Dockerfile.mcp.
- Print instructions for adding MCP config later.
- The baseline eval still works standalone.

### Very large repo (>5GB)
- Use `--depth 1` shallow clone for analysis.
- Limit MR scanning to last 3 months.
- Focus on specific subsystems if user provided a focus area.

### No merged MRs found (or git-only with no merge commits)
- Fall back to analyzing recent commits directly.
- Look for commits with messages containing "fix", "bug", "resolve".
- Propose tasks based on commit diffs instead of MR metadata.

### Single repo for org-scale
- Analyze internal module boundaries as "cross-package" tasks.
- Propose comprehension, audit, and incident-debug tasks within a single repo.
- Suggest additional repos in the same ecosystem for cross-repo tasks.

### Self-hosted / unknown platform
- Ask user: "What platform is this? (GitLab / Gitea / Forgejo / plain git)"
- If GitLab: use `glab` with `--hostname` flag or REST API with base URL.
- If Gitea/Forgejo: use REST API with base URL.
- If unknown: fall back to git-only mode.
