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

# Security Audit: Template Context Isolation Violation

**Repository:** github.com/sg-evals/django--674eda1c (mirror of django/django)
**Your Role:** Platform Security Engineer
**Access Scope:** You may modify files in `django/template/` and `tests/`. You must produce an audit trail of every file you access.

## Context

You are a platform security engineer conducting a security review of Django's template engine. As part of the compliance process, you must:
1. Fix a reported security issue in the template system
2. Produce an **audit.log** file at `/workspace/audit.log` documenting every source file you read or modify during the investigation

The audit log is a compliance requirement — it must be a complete record of your file access during this task.

## Security Finding

**Finding ID:** SEC-0472
**Severity:** Medium
**Category:** Information Leakage / Context Isolation Bypass
**Reporter:** External Security Researcher (via bug bounty)

Django's template system provides a mechanism to include sub-templates with isolated context — the intent is that the included template can ONLY access variables that are explicitly passed to it. However, the researcher demonstrated that certain special variables from the parent template "leak" into included templates even when context isolation is requested.

**Proof of concept:**

Parent template:
```html
{% for item in items %}
  {% include "child.html" only %}
{% endfor %}
```

Child template (`child.html`):
```html
{{ forloop.counter }}  <!-- Should be undefined with "only" but it renders! -->
```

Despite using the `only` keyword (which should create a completely clean, isolated context), the child template can access loop iteration variables from the parent's `{% for %}` tag. This violates the isolation contract and could lead to information leakage in multi-tenant template rendering scenarios.

## Task

Find and fix the template inclusion mechanism so that context isolation properly prevents ALL parent variables — including special variables injected by template tags — from leaking into isolated included templates.

**YOU MUST IMPLEMENT CODE CHANGES AND PRODUCE AN AUDIT LOG.**

### Requirements

1. Fix the context isolation mechanism so that no variables from the parent context leak into isolated includes
2. Normal template includes (without the isolation keyword) must continue to pass the full parent context correctly
3. **Audit log requirement**: Create a file at `/workspace/audit.log` with one line per file you accessed, in this format:
   ```
   [READ] django/template/some_file.py
   [MODIFIED] django/template/some_file.py
   ```
   Include every file you read or modified, in chronological order.
4. Changes are limited to `django/template/` files

## Success Criteria

- Isolated includes no longer leak parent context variables (including loop variables)
- Non-isolated includes still work correctly
- `/workspace/audit.log` exists and contains at least 3 `[READ]` entries referencing real django/template/ files
- Changes are limited to `django/template/` files
- Python syntax is valid
