# Code Review: cal.com Feature Opt-In Scope Configuration

- **Repository**: calcom/cal.com
- **Difficulty**: hard
- **Category**: code-review
- **Task Type**: repo-clone

## Description

You are reviewing a recently merged pull request that adds scope configuration for the feature opt-in system. This PR allows features to be restricted to specific scopes (org, team, user) instead of being available at all levels. The changes span the service layer, configuration module, type definitions, and the tRPC router. However, several defects were introduced during the merge — both functional bugs and compliance violations.

Your task is to **find the defects and produce a structured review report with proposed fixes**.

## Context

The feature opt-in scope configuration spans three key TypeScript source files:

1. **`packages/features/feature-opt-in/services/FeatureOptInService.ts`** — Service class: resolves feature states across teams with precedence rules, lists features for user/team scopes, and validates scope before setting states.
2. **`packages/features/feature-opt-in/config.ts`** — Configuration module: defines the opt-in feature allowlist with per-feature scope arrays, provides helper functions for scope filtering and validation.
3. **`packages/trpc/server/routers/viewer/featureOptIn/_router.ts`** — tRPC router: exposes endpoints for listing and setting feature states at user/team/org levels, validates slugs against the allowlist before mutations.

## Task

Review the three files listed above for the following types of defects:

- **Functional bugs**: Logic errors that cause incorrect behavior (e.g., inverted filter conditions, missing validation checks, ignored configuration).
- **Compliance violations**: Deviations from the codebase's established patterns (e.g., hardcoded values where config should be used, missing scope validation).

For each defect you find:

1. **Describe the defect** in your review report.
2. **Write a fix** as a unified diff in the `fix_patch` field.

**Do NOT edit source files directly.** Express all fixes as unified diffs in your review report. The evaluation system will apply your patches and verify correctness.

### Expected Output

After completing your review, write a JSON file at `/workspace/review.json` containing an array of defect objects:

```json
[
  {
    "file": "packages/features/feature-opt-in/services/FeatureOptInService.ts",
    "line": 160,
    "severity": "critical",
    "description": "Brief description of what is wrong and why",
    "fix_patch": "--- a/packages/features/feature-opt-in/services/FeatureOptInService.ts\n+++ b/packages/features/feature-opt-in/services/FeatureOptInService.ts\n@@ -158,5 +158,5 @@\n-    old line\n+    new line\n"
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
