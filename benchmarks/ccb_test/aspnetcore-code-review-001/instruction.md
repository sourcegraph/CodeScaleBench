# Code Review: ASP.NET Core Blazor DisplayName Feature

- **Repository**: dotnet/aspnetcore
- **Difficulty**: hard
- **Category**: code-review
- **Task Type**: repo-clone

## Description

You are reviewing a recently merged pull request that adds a `DisplayName<TValue>` component to Blazor. This component reads `[Display]` and `[DisplayName]` attributes from model properties and renders the display name in forms. The PR introduces the component class, an expression member accessor helper with caching, and updates to project templates. However, several defects were introduced during the merge — both functional bugs and compliance violations.

Your task is to **find the defects, fix them in the code, and produce a structured review report**.

## Context

The DisplayName feature spans two core C# source files:

1. **`src/Components/Web/src/Forms/DisplayName.cs`** — Component class: implements `IComponent`, accepts a `For` expression parameter, resolves the display name via `ExpressionMemberAccessor`, and renders it.
2. **`src/Components/Web/src/Forms/ExpressionMemberAccessor.cs`** — Static helper: caches expression-to-member mappings and member-to-display-name mappings, supports hot reload cache clearing, resolves display names from `[Display]` and `[DisplayName]` attributes.

## Task

YOU MUST IMPLEMENT CODE CHANGES to complete this task.

Review the two files listed above for the following types of defects:

- **Functional bugs**: Logic errors that cause incorrect behavior (e.g., wrong attribute precedence, missing null checks, broken cache invalidation).
- **Compliance violations**: Deviations from ASP.NET Core component conventions (e.g., unnecessary re-rendering, missing render optimization).

For each defect you find:

1. **Fix the code** by editing the affected file in `/workspace/`.
2. **Record the defect** in your review report.

### Expected Output

After completing your review, write a JSON file at `/workspace/review.json` containing an array of defect objects:

```json
[
  {
    "file": "src/Components/Web/src/Forms/ExpressionMemberAccessor.cs",
    "line": 60,
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
