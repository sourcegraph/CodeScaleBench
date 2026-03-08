# Task: Generate Flipt Release Notes

**Repository:** flipt-io/flipt
**Output:** Write your release notes to `/workspace/RELEASE_NOTES.md`

## Objective

Generate comprehensive release notes for Flipt summarizing API changes. Flipt is an open-source feature flag management system with REST and gRPC APIs. Analyze the codebase to identify what changed in terms of the public API surface.

## Scope

Analyze the following areas for API changes:
- `rpc/flipt/` — protobuf API definitions (gRPC surface)
- `internal/server/` — REST API handlers
- `internal/storage/` — storage backend changes
- `ui/` — frontend changes if any significant ones exist
- `CHANGELOG.md` in the repository (use as reference, not as copy)

## Output Format

Write to `/workspace/RELEASE_NOTES.md`:

```markdown
# Flipt Release Notes

## Breaking Changes

> These changes require action from users upgrading.

- **[API/Storage/Config]**: Description + migration path

## New Features

- **[component]**: Description with API example if applicable

## Deprecations

- **[component]**: What is deprecated, what to use instead, when it will be removed

## Bug Fixes

- **[component]**: Description

## Upgrade Guide

Step-by-step instructions for users upgrading from the previous version.
```

## Quality Bar

- Every breaking change must include a migration path
- Every deprecation must specify the replacement
- New features must reference the specific API endpoint or config option
- The upgrade guide must be actionable (numbered steps)

## Anti-Requirements

- Do not copy the existing CHANGELOG.md
- Do not fabricate API endpoints — verify in rpc/ or internal/server/
