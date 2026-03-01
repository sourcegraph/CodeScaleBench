# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/django--e295033`
- Use `repo:^github.com/sg-evals/django--e295033$` filter in keyword_search
- Use `github.com/sg-evals/django--e295033` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Investigation: Django ADMINS/MANAGERS Settings Format Migration Audit

**Repository:** github.com/sg-evals/django--e295033 (mirror of django/django)
**Task Type:** Migration Audit (investigation only — no code changes)

## Scenario

Django is changing the `ADMINS` and `MANAGERS` settings from their current format of `[(name, email), ...]` tuples to simple `[email, ...]` string lists. This is tracked in ticket #36138. Before executing this migration, the team needs a comprehensive audit of all code that reads, validates, or processes these settings.

## Your Task

Produce a migration audit report at `/logs/agent/investigation.md`.

Your report MUST cover:
1. Every file that reads `settings.ADMINS` or `settings.MANAGERS`
2. Every file that validates or type-checks the settings format
3. Every file that unpacks the tuple format (e.g., `for name, email in settings.ADMINS`)
4. All documentation references that show the old tuple format
5. Test files that use the old format in fixtures or assertions
6. Third-party compatibility concerns (what breaks for users with old-format settings)
7. A migration checklist: each file that needs changes, what change is needed

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding>

## Root Cause
<Core code paths that consume the tuple format>

## Evidence
<Code references with file paths and line numbers>

## Affected Components
<List of modules/packages impacted>

## Recommendation
<Migration checklist with specific files and changes needed>
```

## Constraints

- Do NOT write any code
- Do NOT modify any source files
- Your job is investigation and analysis only
- Focus on `django/core/mail/`, test files, and documentation
