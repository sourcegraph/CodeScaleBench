# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/Ghost--b43bfc85`
- Use `repo:^github.com/sg-evals/Ghost--b43bfc85$` filter in keyword_search
- Use `github.com/sg-evals/Ghost--b43bfc85` as the `repo` parameter for go_to_definition/find_references/read_file


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
1. Know the exact symbol? → `sg_keyword_search`
2. Know the concept, not the name? → `sg_nls_search`
3. Need definition of a symbol? → `sg_go_to_definition`
4. Need all callers/references? → `sg_find_references`
5. Need full file content? → `sg_read_file`

## Scoping (Always Do This)

```
repo:^github.com/ORG/REPO$           # Exact repo (preferred)
repo:github.com/ORG/                 # All repos in org
file:.*\.ts$                         # TypeScript only
file:src/api/                        # Specific directory
```

Start narrow. Expand only if results are empty.

## Efficiency Rules

- Chain searches logically: search → read → references → definition
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

# Code Review: Ghost Comment Likes Feature

- **Repository**: github.com/sg-evals/Ghost--b43bfc85 (mirror of TryGhost/Ghost)
- **Difficulty**: hard
- **Category**: code-review
- **Task Type**: repo-clone

## Description

You are reviewing a recently merged pull request that adds a "comment likes" feature to the Ghost blogging platform. The PR introduces a new API endpoint for browsing comment likes, along with supporting controller and service methods. However, several defects were introduced during the merge — both functional bugs and compliance violations.

Your task is to **find the defects and produce a structured review report with proposed fixes**.

## Context

The comment likes feature spans three backend files:

1. **`ghost/core/core/server/services/comments/comments-service.js`** — Service layer: `getCommentLikes()` method that queries the database for likes on a given comment.
2. **`ghost/core/core/server/services/comments/comments-controller.js`** — Controller layer: `getCommentLikes()` method that extracts the comment ID from the request frame and delegates to the service.
3. **`ghost/core/core/server/api/endpoints/comment-likes.js`** — API endpoint definition: `browse` action configuration including HTTP headers and query options.

## Task

Review the three files listed above for the following types of defects:

- **Functional bugs**: Logic errors that cause incorrect behavior (e.g., missing error handling, wrong variable references, broken data loading).
- **Compliance violations**: Deviations from Ghost's API conventions (e.g., incorrect cache control headers on read-only endpoints).

For each defect you find:

1. **Describe the defect** in your review report.
2. **Write a fix** as a unified diff in the `fix_patch` field.

**Do NOT edit source files directly.** Express all fixes as unified diffs in your review report. The evaluation system will apply your patches and verify correctness.

### Expected Output

After completing your review, write a JSON file at `/workspace/review.json` containing an array of defect objects:

```json
[
  {
    "file": "ghost/core/core/server/services/comments/comments-service.js",
    "line": 263,
    "severity": "critical",
    "description": "Brief description of what is wrong and why",
    "fix_patch": "--- a/ghost/core/core/server/services/comments/comments-service.js\n+++ b/ghost/core/core/server/services/comments/comments-service.js\n@@ -261,5 +261,5 @@\n-    old line\n+    new line\n"
  }
]
```

Each entry must include:
- `file` — Relative path from repository root
- `line` — Approximate line number where the defect occurs
- `severity` — One of: `critical`, `high`, `medium`, `low`
- `description` — What the defect is and what impact it has
- `fix_patch` — Unified diff showing the proposed fix (use `--- a/` and `+++ b/` prefix format)

## Evaluation

Your review will be evaluated on:
- **Detection accuracy** (50%): Precision and recall of reported defects
- **Fix quality** (50%): Whether your proposed patches correctly resolve the defects

## Constraints

- **Time limit**: 1200 seconds
- Do NOT edit source files directly — express fixes only in `fix_patch`
- Do NOT run tests — the evaluation system handles verification
