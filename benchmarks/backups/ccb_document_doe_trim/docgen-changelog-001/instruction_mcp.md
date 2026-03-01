# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/terraform--a3dc5711`
- Use `repo:^github.com/sg-evals/terraform--a3dc5711$` filter in keyword_search
- Use `github.com/sg-evals/terraform--a3dc5711` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Task: Generate Terraform Changelog

**Repository:** github.com/sg-evals/terraform--a3dc5711 (mirror of hashicorp/terraform)
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
