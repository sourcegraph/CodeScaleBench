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

# Add Composite Field Validator for Django Forms

**Repository:** github.com/sg-evals/django--674eda1c (mirror of django/django)
**Access Scope:** You may modify files in `django/forms/`. You may read any file to understand existing patterns.

## Context

Django has a rich validation ecosystem spread across multiple packages. Field-level validators are defined in one location, form-level validation in another, and utility functions for common validation patterns in yet another. When adding new validation capabilities, it's essential to understand how these scattered components work together — there is no single file that explains the full validation architecture.

## Feature Request

**From:** Platform Team
**Priority:** P2

We need a way to apply validation rules that span multiple form fields simultaneously. For example, validating that an end date is after a start date, or that a confirmed email matches the original email field. Currently, developers must override the form's clean method manually for every cross-field validation.

### Deliverables

Create a `CompositFieldValidator` class in Django's forms package that:

1. Can be attached to a form class to validate relationships between two or more named fields
2. Accepts a validation function, a list of field names to validate together, and an error message
3. Integrates with Django's existing form validation pipeline — study how form validation currently works by reading the source code across the relevant packages
4. Raises the appropriate Django validation error type when validation fails, using Django's existing error handling patterns
5. Can be used as a class attribute on form definitions, following the patterns used by existing form components

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. `CompositFieldValidator` class exists in Django's forms package
2. Must integrate with Django's existing validation pipeline (understand how `clean()` and field validation work by reading the source)
3. Must use Django's existing validation error classes (find them in the codebase)
4. Must handle the case where referenced fields don't exist on the form
5. Valid Python syntax
6. Changes limited to `django/forms/`

## Success Criteria

- `CompositFieldValidator` class exists in Django's forms package
- Integrates with form validation pipeline
- Uses Django's validation error types
- Handles missing field references gracefully
- Valid Python syntax
- Changes scoped to `django/forms/`
