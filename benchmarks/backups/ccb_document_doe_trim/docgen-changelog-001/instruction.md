# Task: Generate Terraform Changelog

**Repository:** hashicorp/terraform
**Output:** Write your changelog to `/workspace/CHANGELOG.md`

## Objective

Generate a structured changelog entry for Terraform covering significant changes in the repository. Analyze the commit history, existing CHANGELOG.md, and source changes to produce a well-categorized changelog.

## Scope

Analyze the repository to identify:
- **New features**: New commands, configuration options, provider capabilities
- **Bug fixes**: Resolved issues with state management, plan/apply correctness, or CLI behavior
- **Breaking changes**: Any changes that require user action or break backward compatibility
- **Deprecations**: Features or behaviors being phased out
- **Performance improvements**: Changes that improve plan/apply speed or memory usage

Focus on changes visible in the `internal/`, `command/`, and `backend/` directories.

## Output Format

Write to `/workspace/CHANGELOG.md` using Terraform's established format:

```markdown
## [Unreleased] / next release

### Breaking Changes

- **[component]**: Description of breaking change and migration path

### New Features

- **[component]**: Description of new feature with usage example if applicable

### Bug Fixes

- **[component]**: Description of the bug and what was fixed

### Performance Improvements

- **[component]**: Description

### Deprecations

- **[component]**: What is deprecated and what to use instead
```

## Quality Bar

- Every entry must reference a specific component (e.g., `backend/s3`, `command/apply`, `internal/states`)
- Breaking changes must include a migration path or workaround
- At least 3 entries per category that has changes
- Do not fabricate entries — base everything on actual code/commit evidence

## Anti-Requirements

- Do not copy the existing CHANGELOG.md verbatim
- Do not include changes that are not evidenced in the codebase
