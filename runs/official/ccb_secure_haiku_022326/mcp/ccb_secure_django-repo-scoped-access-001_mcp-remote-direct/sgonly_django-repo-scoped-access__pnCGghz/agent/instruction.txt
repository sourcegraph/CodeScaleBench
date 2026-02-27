# IMPORTANT: Source Code Access

**Local source files are not present.** Your workspace does not contain source code. You **MUST** use Sourcegraph MCP tools to discover, read, and understand code before making any changes.

**Target Repository:** `github.com/sg-evals/django--674eda1c`
- Use `repo:^github.com/sg-evals/django--674eda1c$` filter in keyword_search
- Use `github.com/sg-evals/django--674eda1c` as the `repo` parameter for go_to_definition/find_references/read_file


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

# Fix Admin Filter Sidebar Showing Empty Filters

**Repository:** github.com/sg-evals/django--674eda1c (mirror of django/django)
**Your Team:** Admin UI Team
**Access Scope:** You are assigned to the `django/contrib/admin/` package only.

## Context

You are a developer on the Django Admin UI team. Your access is limited to the `django/contrib/admin/` package. Other contrib packages (`django/contrib/auth/`, `django/contrib/sessions/`, etc.) belong to other teams — you may understand their public APIs by reading documentation and type signatures, but you must not modify or directly inspect their internal implementation files.

## Bug Report

**Reported by:** QA Team
**Severity:** Medium
**Environment:** Django admin site with models using ForeignKey relationships

When a model's admin page is configured to let users filter by a related model (via a ForeignKey), the filter widget appears in the sidebar even when there are zero related objects in the database. This creates a confusing user experience:

1. The filter section title appears in the sidebar with no useful choices
2. Only a generic "All" option is shown — no actual items to filter by
3. Clicking "All" triggers an unnecessary page reload
4. Users have filed support tickets asking why an empty filter exists

**Steps to reproduce:**
1. Register a `ModelAdmin` with `list_filter` set to include a ForeignKey field
2. Ensure the related model's database table has no rows
3. Visit the admin changelist page
4. Observe the filter sidebar — the empty filter is still rendered

**Expected behavior:** When there are no meaningful choices available for a filter, the filter should not appear in the sidebar at all.

## Task

Find the root cause in the admin's filter rendering pipeline and fix it so that filters backed by an empty set of choices are hidden from the sidebar entirely.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. The fix should prevent empty related-field filters from rendering in the admin sidebar
2. Filters that DO have choices must continue to display correctly
3. All changes must be within `django/contrib/admin/`

## Success Criteria

- Empty related-field filters no longer appear in the admin sidebar
- Filters with available choices continue to work normally
- Changes are limited to `django/contrib/admin/` files only
- Python syntax is valid
