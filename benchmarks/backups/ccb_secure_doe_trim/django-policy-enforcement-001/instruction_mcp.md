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

# Add Bulk Soft-Delete Manager Method to Django ORM

**Repository:** github.com/sg-evals/django--674eda1c (mirror of django/django)
**Access Scope:** You may modify files in `django/db/models/`. You may read any file to understand existing patterns.

## Context

You are adding a new ORM feature to Django. Your organization enforces strict coding policies for all contributions to the ORM layer.

## Company Coding Policies

**MANDATORY — All code changes MUST comply:**

1. **ORM-Only Policy:** All database interactions must use Django's ORM (QuerySet methods, model managers, F() expressions, etc.). Direct SQL queries using `cursor.execute()`, `raw()`, `connection.cursor()`, or any raw SQL strings are **strictly prohibited**.

2. **No Hardcoded Credentials:** Code must not contain hardcoded passwords, API keys, secrets, or connection strings. Use Django settings or environment variables.

3. **Documentation Required:** All new public functions, classes, and methods must have docstrings explaining their purpose, parameters, and return values.

4. **Type Safety:** All new functions should include type hints for parameters and return values.

## Feature Request

**From:** Backend Team
**Priority:** P2

We need a custom model manager that provides bulk soft-delete functionality — marking multiple records as deleted without actually removing them from the database. This is a common pattern for audit compliance — we need to keep records but mark them inactive.

### Deliverables

Add a custom manager class to Django's model manager module that:

1. Provides a method to perform bulk soft-deletion, accepting either a queryset or a list of IDs, with an optional parameter to record who performed the deletion
2. Marks matching records with a deleted flag and timestamp using ORM update operations
3. Returns the count of records soft-deleted
4. Works with Django's existing manager and queryset infrastructure — study how existing managers are implemented
5. Includes a method to restore (undo) soft-deletes

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. A custom manager class in Django's model managers module
2. Bulk soft-delete and restore methods
3. Must use ORM operations exclusively (QuerySet.update, F expressions, etc.)
4. Must comply with ALL company coding policies listed above
5. Valid Python syntax
6. Changes limited to `django/db/models/`

## Success Criteria

- Custom manager class with bulk soft-delete and restore methods
- Uses ORM exclusively (no raw SQL)
- All new functions have docstrings
- No hardcoded credentials
- Valid Python syntax
- Changes scoped to `django/db/models/`
