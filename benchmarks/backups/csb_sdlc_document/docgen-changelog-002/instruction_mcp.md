# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/flipt--3d5a345f`
- Use `repo:^github.com/sg-evals/flipt--3d5a345f$` filter in keyword_search
- Use `github.com/sg-evals/flipt--3d5a345f` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Task: Generate Flipt Release Notes

**Repository:** github.com/sg-evals/flipt--3d5a345f (mirror of flipt-io/flipt)
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
