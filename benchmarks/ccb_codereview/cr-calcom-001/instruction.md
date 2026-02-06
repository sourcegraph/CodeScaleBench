# Code Review: cal.com Feature Opt-In Scope Configuration

- **Repository**: calcom/cal.com
- **Difficulty**: hard
- **Category**: code-review
- **Task Type**: repo-clone

## Description

You are reviewing a recently merged pull request that adds scope configuration for the feature opt-in system. This PR allows features to be restricted to specific scopes (org, team, user) instead of being available at all levels. The changes span the service layer, configuration module, type definitions, and the tRPC router. However, several defects were introduced during the merge — both functional bugs and compliance violations.

Your task is to **find the defects, fix them in the code, and produce a structured review report**.

## Context

The feature opt-in scope configuration spans three key TypeScript source files:

1. **`packages/features/feature-opt-in/services/FeatureOptInService.ts`** — Service class: resolves feature states across teams with precedence rules, lists features for user/team scopes, and validates scope before setting states.
2. **`packages/features/feature-opt-in/config.ts`** — Configuration module: defines the opt-in feature allowlist with per-feature scope arrays, provides helper functions for scope filtering and validation.
3. **`packages/trpc/server/routers/viewer/featureOptIn/_router.ts`** — tRPC router: exposes endpoints for listing and setting feature states at user/team/org levels, validates slugs against the allowlist before mutations.

## Task

YOU MUST IMPLEMENT CODE CHANGES to complete this task.

Review the three files listed above for the following types of defects:

- **Functional bugs**: Logic errors that cause incorrect behavior (e.g., inverted filter conditions, missing validation checks, ignored configuration).
- **Compliance violations**: Deviations from the codebase's established patterns (e.g., hardcoded values where config should be used, missing scope validation).

For each defect you find:

1. **Fix the code** by editing the affected file in `/workspace/`.
2. **Record the defect** in your review report.

### Expected Output

After completing your review, write a JSON file at `/workspace/review.json` containing an array of defect objects:

```json
[
  {
    "file": "packages/features/feature-opt-in/services/FeatureOptInService.ts",
    "line": 160,
    "severity": "critical",
    "description": "Brief description of what is wrong and why",
    "fix_applied": true
  }
]
```

Each entry must include:
- `file` — Relative path from repository root
- `line` — Approximate line number where the defect occurs
- `severity` — One of: `critical`, `high`, `medium`, `low`
- `description` — What the defect is and what impact it has
- `fix_applied` — Boolean indicating whether you committed a fix

## Scoring

Your submission is scored on two equally weighted components:

1. **Detection score (50%)**: F1 score (harmonic mean of precision and recall) of your reported defects matched against the ground truth. A reported defect matches if it identifies the correct file and a related issue.
2. **Fix score (50%)**: Proportion of defects where you both identified the issue and applied a correct code fix (verified by checking for expected code patterns in the modified files).

**Final score** = 0.5 × detection_F1 + 0.5 × fix_score

## Testing

- **Time limit**: 1200 seconds
- Run `bash /workspace/tests/test.sh` to verify your changes
