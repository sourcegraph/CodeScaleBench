# Sourcegraph Benchmark: Baseline vs MCP Detailed Analysis

**Date**: 2026-03-11
**Run ID**: `sourcegraph_sonnet_20260311_012119`
**Model**: Claude Sonnet 4.6 (`claude-sonnet-4-6`)
**Tasks**: 6 (3 code comprehension / audit, 2 bug fix, 1 security analysis)

---

## Executive Summary

After correcting two infrastructure bugs in baseline Dockerfiles (missing `claude` user permissions; missing `.netrc` for Go private module auth), the baseline configuration **outperforms MCP by 0.057 points on average** across 6 Sourcegraph monorepo tasks.

| Config | Mean Score | Median |
|--------|:---------:|:------:|
| Baseline (original, broken) | 0.493 | 0.610 |
| **Baseline (fixed)** | **0.827** | **0.850** |
| MCP (sg_only) | 0.770 | 0.787 |

The MCP advantage previously reported (+0.277) was an artifact of two broken baseline Dockerfiles that produced 0.0 scores. With infrastructure parity, the **baseline wins on 4/6 tasks**, MCP wins on 1, and 1 is tied.

---

## 1. Environment Setup

### 1.1 Baseline Configuration (`baseline-local-direct`)

The baseline agent runs inside a Docker container with **full local source code** cloned at a pinned commit.

**Typical Dockerfile pattern:**
```dockerfile
FROM golang:1.26-bookworm
ARG GITHUB_TOKEN

RUN git clone https://x-access-token:${GITHUB_TOKEN}@github.com/sourcegraph/sourcegraph.git /workspace && \
    cd /workspace && git checkout <pinned-commit>

# Pre-create claude user and set ownership at build time
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true) && \
    for d in /workspace /app /testbed /logs; do [ -d "$d" ] && chown -R claude:claude "$d"; done || true
```

**Available tools**: Bash, Read, Write, Edit, Glob, Grep (all local filesystem tools).

### 1.2 MCP Configuration (`mcp-remote-direct` / sg_only)

The MCP agent runs in a container where **all source files are truncated to zero bytes**. The agent must use Sourcegraph MCP tools for code discovery and reading.

**Typical Dockerfile.sg_only pattern:**
```dockerfile
FROM golang:1.26-bookworm
ARG GITHUB_TOKEN

# Clone and checkout (same as baseline)
RUN git init /workspace && cd /workspace && \
    git remote add origin https://x-access-token:${GITHUB_TOKEN}@github.com/sourcegraph/sourcegraph.git && \
    git fetch --depth=1 origin <pinned-commit> && \
    git checkout FETCH_HEAD

# Truncate ALL source files so agent cannot read them locally
RUN find /workspace -type f \( -name "*.go" -o -name "*.ts" -o ... \) \
    ! -path "*/.git/*" -exec truncate -s 0 {} \;

# Recommit so git history cannot recover files
RUN git add -A && git commit -m "sg_only truncation" --allow-empty --quiet

# Clone manifest for verifier (restores source at verification time)
RUN echo '{"workdir":"/workspace","repos":[...]}' > /tmp/.sg_only_clone_manifest.json
```

**Available tools**: Bash, Read, Write, Edit, Glob, Grep (local — but source files are empty) **plus** Sourcegraph MCP tools:
- `sg_keyword_search` — code search with Sourcegraph query syntax
- `sg_nls_search` — natural language semantic search
- `sg_read_file` — read file contents from Sourcegraph index
- `sg_list_files` — list files in a directory
- `sg_list_repos` — list available repositories

### 1.3 Task Instructions

Both configurations receive nearly identical instructions. The MCP variant adds a single preamble line:

```markdown
> **Note:** You have access to Sourcegraph MCP tools for code search and navigation.
> Use `sg_keyword_search` and `sg_nls_search` to explore the codebase efficiently.
```

For audit/comprehension tasks (sgauth-301, sgcompletion-302, sgencrypt-305), both instructions include the same output schema (`answer.json` with `files`, `symbols`, `chain`, `summary`).

For implementation tasks (gitlab-ratelimit, anchor-fix, imgbomb-fix), both instructions include the same success criteria and task contract.

### 1.4 Verifier Architecture

**Audit tasks** use a Python-based F1 scorer:
```
composite = 0.80 × file_F1 + 0.20 × symbol_recall
```
where `file_F1 = 2 × precision × recall / (precision + recall)` comparing agent-discovered files against an oracle answer.

**Implementation tasks** use `go test` or `vitest` with partial credit:
```
reward = tests_passed / (tests_passed + tests_failed)
```

---

## 2. Per-Task Analysis

### 2.1 ccx-sgauth-301 — Auth Chain Audit (Baseline 0.54, MCP 0.29)

**Task**: Map the complete authentication and authorization middleware chain — 12+ auth providers, 8 code host authz providers, middleware registration, session management, and repository-level access control.

**Instruction excerpt** (identical for both):
> Map the complete authentication and authorization middleware chain in Sourcegraph's frontend service. Identify all authentication provider middlewares, how they register and create sessions, and how the authorization layer enforces repository-level access permissions across all supported code hosts.

#### Verifier Results

| Metric | Baseline | MCP |
|--------|:--------:|:---:|
| Agent files found | 53 | 42 |
| Oracle files | 56 | 56 |
| Correct overlap | 32 | 18 |
| Precision | 60.4% | 42.9% |
| Recall | 57.1% | 32.1% |
| File F1 | 0.587 | 0.367 |
| Symbol score | 0.333 | 0.000 |
| **Composite** | **0.536** | **0.294** |

#### Baseline Tool Call Trace (32 calls, 2.5 min)

The baseline agent used a systematic **enumerate-then-read** strategy:

```
 #1  ToolSearch  → load Read, Grep, Glob, Bash
 #2  Glob        → internal/auth/**/*.go                    → 5 files
 #3  Glob        → cmd/frontend/**/*.go                     → 100 files
 #4  Glob        → enterprise/cmd/frontend/**/*.go          → 0 files
 #5  Glob        → internal/authz/**/*.go                   → 59 files
 #6  Grep        → "auth.*Middleware|RegisterProvider"       → 96 matching files
 #7  Glob        → internal/authn/**/*.go                   → 0 files
 #8  Read        → cmd/frontend/internal/auth/init.go
 #9  Read        → cmd/frontend/internal/cli/http.go
#10  Read        → cmd/frontend/auth/auth.go
#11  Read        → cmd/frontend/auth/non_public.go
#12  Glob        → cmd/frontend/internal/authz/**/*.go      → 12 files
#13  Read        → cmd/frontend/internal/authz/init.go
#14  Read        → cmd/frontend/internal/authz/middleware.go
#15  Read        → cmd/frontend/internal/auth/providers/providers.go
#16  Read        → internal/authz/providers/authz.go
#17  Read        → internal/authz/iface.go                  ← SubRepoPermissionChecker (symbol hit)
#18  Read        → cmd/frontend/internal/auth/session/session.go
#19  Read        → cmd/frontend/internal/auth/oauth/middleware.go
#20  Glob        → cmd/frontend/internal/auth/accesstoken/**/*.go → 6 files
#21  Read        → cmd/frontend/internal/auth/accesstoken/auth.go
#22  Read        → cmd/frontend/internal/auth/httpheader/middleware.go
#23  Read        → cmd/frontend/auth/user.go
#24  Glob        → cmd/frontend/internal/auth/idp/**/*.go   → 46 files
#25  Read        → cmd/frontend/internal/auth/oidc/config.go
#26  Read        → cmd/frontend/internal/auth/saml/provider.go
#27  Read        → cmd/frontend/internal/auth/userpasswd/init.go
#28  Read        → cmd/frontend/internal/auth/idp/oauthtoken/auth.go
#29  Read        → cmd/frontend/internal/auth/sourcegraphoperator/provider.go
#30  Read        → cmd/frontend/internal/auth/sourcegraphaccounts/provider.go
#31  Write       → /workspace/answer.json
```

**Key pattern**: 7 Glob calls to enumerate directories, 1 Grep to find cross-cutting patterns, then targeted Reads. The agent explored auth providers methodically: OAuth → OIDC → SAML → HTTP Header → Access Token → IDP → Sourcegraph Operator → Sourcegraph Accounts.

#### MCP Tool Call Trace (21 calls, 3.4 min)

The MCP agent used a **search-then-read** strategy with far fewer discovery steps:

```
 #1  ToolSearch       → load SG MCP tools
 #2  sg_keyword_search → "file:middleware auth middleware handler"
 #3  sg_nls_search     → "authentication middleware chain frontend"
 #4  sg_read_file      → cmd/frontend/internal/cli/http.go
 #5  sg_list_files     → cmd/frontend/internal/auth
 #6  sg_read_file      → cmd/frontend/auth/non_public.go
 #7  sg_read_file      → cmd/frontend/internal/authz/middleware.go
 #8  sg_read_file      → cmd/frontend/internal/auth/providers (dir)
 #9  sg_read_file      → cmd/frontend/internal/auth/accesstoken (dir)
#10  sg_nls_search     → "authz provider repository permissions check"
#11  sg_read_file      → internal/authz/iface.go
#12  sg_list_files     → internal/authz/providers
#13  sg_read_file      → cmd/frontend/internal/auth/providers/providers.go
#14  sg_read_file      → cmd/frontend/internal/auth/accesstoken/auth.go
#15  sg_read_file      → internal/authz/providers/authz.go
#16  sg_read_file      → cmd/frontend/internal/auth/session/session.go (lines 1-100)
#17  sg_read_file      → cmd/frontend/internal/auth/init.go
#18  sg_keyword_search → "RegisterProviderFactory" in auth dir
#19  Write (FAILED)    → wrong tool schema
#20  ToolSearch        → load Write tool
#21  Write             → /workspace/answer.json
```

**Key gaps**:
- Only 2 `sg_keyword_search` + 2 `sg_nls_search` calls (vs 7 Globs + 1 Grep for baseline)
- No exploration of individual provider directories (Azure, Bitbucket Cloud/Server, Gerrit, GitHub, GitLab, Perforce)
- 2 wasted calls on Write failure + ToolSearch retry
- Zero symbols found (0/3) because MCP reads don't support pattern matching across files

#### Root Cause

This is an **exhaustive enumeration task**. The oracle expects 56 files spanning 12+ auth providers and 8 authz providers. Baseline's `Glob` can sweep entire directory trees in a single call; MCP's `sg_keyword_search` returns ranked results that miss files whose names/content don't match the search terms. The agent would need ~20+ targeted searches to match what 7 Globs cover instantly.

---

### 2.2 sg-gitlab-ratelimit-fix-001 — Bug Fix (Baseline 1.00, MCP 0.86)

**Task**: Fix GitLab `allowGroups` membership check that paginates all user groups, triggering rate limiting. Replace with targeted `/api/v4/groups/{id}/members/all/{user_id}` endpoint.

**Instruction excerpt** (identical for both):
> When `allowGroups` is configured for GitLab OAuth, the membership check iterates through all user groups via pagination (`ListGroups`). For users who are members of hundreds of subgroups, this triggers GitLab API rate limiting, causing authentication failures.
>
> 1. Update the calling path to use the new flow.
> 2. Update existing tests to reflect the new behavior.

#### Verifier Results

| Metric | Baseline | MCP |
|--------|:--------:|:---:|
| Go tests passed | 64 | 42 |
| Go tests failed | 0 | 7 |
| **Score** | **1.000** | **0.857** |

#### Baseline Tool Call Trace (47 calls, 10.3 min, 3.1M tokens)

The baseline agent followed a disciplined **read → understand → implement → test** cycle:

```
 #1  ToolSearch    → load tools
 #2  Glob          → **/gitlab/**/*.go in /workspace/internal
 #3  Bash          → grep -l "allowGroups" across workspace
 #4  Bash          → go test gitlaboauth/... (initial test run)
 #5  Read          → session.go (calling code)
 #6  Read          → session_test.go
 #7  Read          → groups.go (existing ListGroups)
 #8  Read          → mock.go
 #9  Read          → groups_test.go
#10  Read          → members.go (existing member functions)
#11  Grep          → HTTPError patterns in gitlab package
#12  Read          → client.go (HTTP error handling)
#13  Edit          → members.go — add GetGroupMember() function
#14  Edit          → mock.go — add MockGetGroupMember
#15  Edit          → session.go — rewire verifyAllowedGroups to use new API
#16  Edit          → session_test.go — update test mocks (multiple iterations)
#17  Bash          → go test gitlaboauth/... (PASS)
#18  Bash          → go test gitlab/... (PASS)
#19  Bash          → gofmt -w on modified files
```

**Files modified**: `members.go` (new `GetGroupMember` API), `mock.go` (mock hook), `session.go` (caller), `session_test.go` (tests). All in the correct packages.

#### MCP Tool Call Trace (150 calls, 183 min, 22.5M tokens)

The MCP agent spent the **vast majority of its time reconstructing local source files** from remote MCP reads:

```
 #1-3   ToolSearch/TodoWrite  → plan
 #4-10  sg_keyword_search/sg_read_file → discover and read session.go, groups.go, etc.
#11     Bash                  → go test (FAILS — all local .go files are 0 bytes)
#12-28  Bash/sg_read_file     → discover empty files, read from MCP, Write locally
#29     TodoWrite             → "Plan: write ALL empty files from SG source"
#30-57  Write/Read (×28)      → MANUALLY RECREATE source files from MCP reads
#58-91  Bash (×34)            → struggle with build: empty files, missing deps,
                                 sourceflow private module, go module cache
#92     Agent (sub-agent)     → "Populate ALL required Go packages from Sourcegraph"
#93-128 Bash/Edit (×36)       → fight sourceflow dep, edit go.mod replace directives,
                                 attempt builds repeatedly
#129-141 Bash/sg_read_file    → populate testutil, version packages
#142-150 Bash/Edit            → final edits to repos/gitlab.go (WRONG FILE)
```

**Critical failure**: The MCP agent edited `internal/repos/gitlab.go` instead of the correct files (`internal/extsvc/gitlab/members.go`, `cmd/frontend/internal/auth/gitlaboauth/session.go`). After spending 89 Bash calls and 3 hours fighting build issues, it never implemented the core `GetGroupMember()` function.

**Failing MCP tests** (7 failures in `internal/extsvc/gitlab` package):
- `TestGetAuthenticatedUserOAuthScopes` — VCR fixture files missing (truncated)
- `TestClient_GetGroupsByIDs_VCR` — VCR fixtures missing
- `TestClient_ListUserGroups_VCR` — VCR fixtures missing
- `TestClient_ForkProject/success` — SIGSEGV (nil pointer from incomplete mock)
- `TestCreateMergeRequest_Archived` / `TestUpdateMergeRequest_Archived` — missing test data

#### Root Cause

The sg_only mode truncates ALL source files, but the verifier restores them at verification time via a clone manifest. The agent, however, must **write code into zero-byte files** during its run. The MCP agent:

1. Discovered the empty files immediately (`go test` failed)
2. Spent 150+ calls and 3 hours trying to reconstruct the workspace from MCP reads
3. Got lost in dependency resolution (`sourcegraph/sourceflow` private module)
4. Eventually edited the wrong files, never implementing the actual fix

**Comparison**:
| Metric | Baseline | MCP |
|--------|:-:|:-:|
| Tool calls | 47 | 150 |
| Wall clock | 10.3 min | 183.4 min |
| Input tokens | 3.1M | 22.5M |
| Output tokens | 19K | 47K |
| Files edited correctly | 4/4 | 0/4 |

---

### 2.3 ccx-sgcompletion-302 — Completions Trace (Baseline 0.72, MCP 0.70)

**Task**: Trace the complete request path for LLM completions from GraphQL API through Cody Gateway to downstream providers. Identify every rate limiting layer and auth checkpoint.

**Instruction excerpt** (identical for both):
> A customer reports intermittent 429 errors when using Cody completions. Trace the complete request path from the GraphQL completions API on the frontend, through the Cody Gateway proxy service, to the downstream LLM provider. Identify every rate limiting layer, authentication check, and provider selection decision point along the way.

#### Verifier Results

| Metric | Baseline | MCP |
|--------|:--------:|:---:|
| Agent files found | 29 | 28 |
| Correct overlap | 28 | 27 |
| Precision | 96.6% | 96.4% |
| Recall | 75.7% | 73.0% |
| File F1 | 0.849 | 0.831 |
| Symbol score | 0.200 | 0.200 |
| **Composite** | **0.719** | **0.705** |

#### Baseline Trace (27 calls, 2.8 min)

```
 #1  ToolSearch  → load tools
 #2  Glob        → **/completions/**/*.go, **/cody-gateway/**/*.go
 #3  Grep        → "completions" in httpapi/
 #4  Read ×19    → systematic walk: httpapi/completions/ → internal/completions/client/ →
                    cmd/cody-gateway/internal/{auth,actor,httpapi,featurelimiter}
 #5  Write       → answer.json
```

#### MCP Trace (33 calls, 4.3 min)

```
 #1-3  ToolSearch (×3) → load MCP tools (multiple attempts)
 #4    sg_keyword_search → "completions GraphQL resolver"
 #5    sg_keyword_search → "file:schema.graphql completions"
 #6    sg_read_file ×5   → same files as baseline
 #7    sg_keyword_search → "file:httpapi/completions rate limit handler"
 #8    sg_keyword_search → "file:internal/completions/client func Get"
 #9    sg_read_file ×8   → cody-gateway auth, actor, httpapi files
#10    sg_keyword_search → "file:cody-gateway auth middleware actor"
#11-12 sg_keyword_search → sources, IsEnabled
#13    sg_read_file ×4   → more cody-gateway internals
#14    Write (FAILED)    → wrong parameter name (path vs file_path)
#15    ToolSearch        → load Write
#16    Write             → answer.json
```

**MCP overhead**: 4 ToolSearch calls (vs 1), 1 failed Write + retry. 55% longer, 35% more tokens.

#### Root Cause

The gap is a **single missed file** (28 correct vs 27 correct). Both agents achieved nearly identical precision (~96%) and symbol recall (0.20). The missed file likely ranked outside MCP's top-N search results or didn't match any of the 8 search queries. Baseline found it via exhaustive Glob traversal.

---

### 2.4 ccx-sgencrypt-305 — Encryption Audit (Baseline 0.70, MCP 0.77)

**The one task where MCP outperformed baseline.**

| Metric | Baseline | MCP |
|--------|:--------:|:---:|
| Agent files found | 33 | 19 |
| Correct overlap | 18 | 15 |
| Precision | 54.5% | 78.9% |
| Recall | 85.7% | 71.4% |
| File F1 | 0.667 | 0.750 |
| Symbol score | 0.833 | 0.833 |
| **Composite** | **0.700** | **0.767** |

MCP won here because the baseline agent **over-discovered** (33 files, only 18 correct — 45% false positive rate) while MCP was more precise (19 files, 15 correct — 21% false positive rate). For targeted security audits where precision matters, MCP's ranked search naturally filters noise.

---

### 2.5 sg-deepsearch-anchor-fix-001 — Bug Fix (Both 1.00)

Both configs scored perfectly. This is a TypeScript/Vitest task where the agent creates a test file for ProseMirror anchor detection. The baseline now works correctly after the Dockerfile fix (adding `claude` user + `chown`).

### 2.6 sg-deepsearch-imgbomb-fix-001 — Bug Fix (Both 1.00)

Both configs scored perfectly. No infrastructure issues.

---

## 3. Cross-Task Patterns

### 3.1 Resource Consumption

| Task | Config | Tool Calls | Wall Clock | Input Tokens | Output Tokens |
|------|--------|:----------:|:----------:|:------------:|:-------------:|
| sgauth-301 | Baseline | 32 | 2.5 min | 1.78M | 9K |
| sgauth-301 | MCP | 21 | 3.4 min | 1.18M | 15K |
| gitlab-fix | Baseline | 47 | 10.3 min | 3.1M | 19K |
| gitlab-fix | **MCP** | **150** | **183 min** | **22.5M** | **47K** |
| completion-302 | Baseline | 27 | 2.8 min | 2.14M | 11K |
| completion-302 | MCP | 33 | 4.3 min | 2.89M | 17K |

The gitlab MCP run is a dramatic outlier: **18× longer** and **7× more tokens** than baseline, with a lower score. The agent spent most of its time trying to reconstruct the local workspace from remote reads — a task the sg_only design was not intended to require.

### 3.2 Tool Call Distribution

**Baseline** tools (across all tasks):
- `Read` (dominant) — direct file access is the primary exploration method
- `Glob` — directory-level enumeration, critical for audit tasks
- `Grep` — cross-cutting pattern search
- `Edit`/`Write` — code changes and output
- `Bash` — test execution and build verification

**MCP** tools (across all tasks):
- `sg_read_file` (dominant) — individual file reads via Sourcegraph
- `sg_keyword_search` — ranked code search (4-8 queries per task)
- `sg_nls_search` — semantic search (1-2 queries per task)
- `sg_list_files` — directory listing (1-2 per task)
- `Write`/`Bash` — local output and test execution
- `ToolSearch` — loading tool schemas (2-4 per task, overhead)

### 3.3 Task Type → Config Advantage

| Task Type | Winner | Delta | Why |
|-----------|--------|:-----:|-----|
| Exhaustive audit (sgauth) | Baseline | +0.24 | Glob enumerates all directories; search misses long-tail files |
| Implementation/fix (gitlab) | Baseline | +0.14 | Full source → correct file identification; truncated source → wrong files |
| Targeted trace (completion) | Baseline | +0.01 | Nearly tied; one file missed by search ranking |
| Precision-focused audit (encrypt) | **MCP** | **+0.07** | Search naturally filters noise; baseline over-discovers |
| Simple fix (anchor, imgbomb) | Tie | 0.00 | Both have sufficient capability |

---

## 4. Structural Issues with sg_only Mode

### 4.1 The Workspace Reconstruction Problem

The sg_only Dockerfile truncates all source files to zero bytes. For **comprehension tasks** (audit, trace), this is by design — the agent should use MCP to discover and read code, then write `answer.json`. This works reasonably well.

For **implementation tasks** (bug fix), the agent must:
1. Understand the codebase via MCP
2. Write code into zero-byte files
3. Have the verifier restore full source at test time (via clone manifest)

In practice, the MCP agent on the gitlab task spent 150 calls trying to **reconstruct the entire workspace** from remote reads — filling in every empty `.go` file it needed for `go build` to succeed. This is fundamentally the wrong workflow. The verifier restores source at test time, but the agent doesn't know this and reasonably assumes it needs a buildable workspace.

### 4.2 Search Coverage Gaps

MCP's `sg_keyword_search` returns ranked, truncated results. For tasks requiring exhaustive enumeration (sgauth-301: 56 oracle files across 12+ provider directories), the agent would need ~20+ well-targeted queries to match what 7 Glob calls cover. In practice, agents make 4-8 search calls — insufficient for comprehensive mapping.

### 4.3 Symbol Discovery Limitation

The `sg_keyword_search` tool can find symbol definitions, but the agent must know what to search for. For symbol recall scoring, the agent needs to identify specific function/type names (e.g., `SubRepoPermissionChecker`, `SetActor`). Baseline agents discover these via `Grep` patterns across the whole codebase; MCP agents have no equivalent "find all implementations of interface X" operation.

### 4.4 ToolSearch Overhead

MCP agents consistently spend 2-4 tool calls on `ToolSearch` to discover available MCP tools, versus 1 call for baseline. The first `Write` call also frequently fails due to parameter name confusion (`path` vs `file_path`), requiring another ToolSearch + retry. This wastes 3-5 calls per task.

---

## 5. Recommendations

### 5.1 For MCP Tool Improvements

1. **Add `sg_glob` / `sg_find`**: A file enumeration tool that returns all files matching a glob pattern (e.g., `**/middleware.go`). This would close the biggest gap between MCP and baseline for audit tasks.

2. **Add `sg_grep` / `sg_search_symbols`**: A tool specifically for cross-cutting pattern search (e.g., "all implementations of interface X" or "all files containing `RegisterProvider`"). This would address the symbol discovery limitation.

3. **Increase search result limits**: If `sg_keyword_search` returns top-10 by default, increasing to top-50 would improve recall for comprehensive tasks without degrading precision significantly.

4. **Pre-load MCP tool schemas**: Inject MCP tool definitions into the agent's initial context to eliminate the 2-4 ToolSearch overhead calls per task.

### 5.2 For Benchmark Design

5. **Separate implementation from comprehension scoring**: The gitlab task's failure mode (workspace reconstruction) is a fundamentally different problem than the audit tasks' recall gaps. Consider scoring implementation tasks only on the changed files, not on build success of reconstructed source.

6. **Provide build stubs for sg_only implementation tasks**: Instead of truncating ALL files, keep build-critical files (imports, interfaces, type definitions) and only truncate implementation bodies. This would let the agent focus on the actual fix rather than workspace reconstruction.

7. **Route task types to appropriate configs**: Exhaustive mapping tasks should use a hybrid config (local source + MCP for cross-repo lookups). Truncated-source configs should be reserved for tasks where search-based discovery is naturally sufficient.

### 5.3 For MCP Prompt Engineering

8. **Add exploration guidance**: The MCP instruction preamble should suggest iterative search strategies: "For comprehensive mapping tasks, start with broad searches, then enumerate subdirectories with `sg_list_files`, then search within each subdirectory."

9. **Warn against workspace reconstruction**: For implementation tasks, add: "The verifier will restore full source code at test time. Focus on writing only the files you need to modify — do not attempt to recreate the entire workspace."

10. **Include tool parameter documentation**: Pre-inject the exact parameter names (`file_path` not `path`) to eliminate the Write failure + retry pattern.

---

## Appendix A: Infrastructure Fixes Applied

### sg-deepsearch-anchor-fix-001 Baseline Dockerfile

**Problem**: Dockerfile missing `claude` user creation — agent couldn't write files to root-owned `/workspace` directories.

**Fix**: Added user creation and `chown`:
```dockerfile
RUN mkdir -p /logs/agent /logs/verifier
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true) && \
    for d in /workspace /app /testbed /logs; do [ -d "$d" ] && chown -R claude:claude "$d"; done || true
ENTRYPOINT []
```

### sg-gitlab-ratelimit-fix-001 Baseline Dockerfile

**Problem**: No `.netrc` for `GITHUB_TOKEN` — `go mod download` couldn't fetch private transitive dependency `sourcegraph/sourceflow`.

**Fix**: Added `.netrc` configuration and user setup:
```dockerfile
RUN echo "machine github.com login x-access-token password ${GITHUB_TOKEN}" > /root/.netrc && chmod 600 /root/.netrc
# ... (after dependency download) ...
RUN (adduser --disabled-password --gecos '' claude 2>/dev/null || true) && \
    cp /root/.netrc /home/claude/.netrc && chown claude:claude /home/claude/.netrc && \
    for d in /workspace /app /testbed /logs; do [ -d "$d" ] && chown -R claude:claude "$d"; done || true
```

---

## Appendix B: Full Score Table

| Task | Type | Baseline (fixed) | MCP | Delta | Winner |
|------|------|:-:|:-:|:-:|--------|
| ccx-sgauth-301 | Audit (exhaustive) | 0.54 | 0.29 | -0.25 | Baseline |
| ccx-sgcompletion-302 | Trace (targeted) | 0.72 | 0.70 | -0.02 | Baseline |
| ccx-sgencrypt-305 | Audit (precision) | 0.70 | 0.77 | +0.07 | **MCP** |
| sg-deepsearch-anchor-fix-001 | Bug fix (TS) | 1.00 | 1.00 | 0.00 | Tie |
| sg-deepsearch-imgbomb-fix-001 | Bug fix (TS) | 1.00 | 1.00 | 0.00 | Tie |
| sg-gitlab-ratelimit-fix-001 | Bug fix (Go) | 1.00 | 0.86 | -0.14 | Baseline |
| **Mean** | | **0.827** | **0.770** | **-0.057** | **Baseline** |
