# Code Review: Ghost Comment Likes Feature

- **Repository**: TryGhost/Ghost
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
