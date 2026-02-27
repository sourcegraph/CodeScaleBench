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

# Fix Template Engine Regression: Nested Block Inheritance

**Repository:** github.com/sg-evals/django--674eda1c (mirror of django/django)
**Access Scope:** You may modify files in `django/template/`. You may read any file to understand existing patterns.

## Context

Django's template engine supports template inheritance through block tags. A regression has been introduced that affects how nested blocks behave when multiple levels of template inheritance are involved.

The original developer who maintained this part of the template engine left the organization six months ago. Their commit messages were generally terse (e.g., "fix", "update", "wip"), and no internal documentation exists for the template compilation and rendering internals. You will need to understand the template engine's architecture by reading the source code directly.

## Incident Report

**Filed by:** Platform Reliability
**Severity:** P1
**Incident ID:** INC-7823
**Affected Service:** Content rendering pipeline

### Symptoms

When a template uses three or more levels of inheritance (e.g., `base.html` -> `layout.html` -> `page.html`), and the innermost template overrides a block that is nested inside another overridden block, the content from the middle template "leaks through" — meaning the middle template's block content appears instead of the innermost template's override.

This regression was introduced sometime recently. The template engine's block resolution logic handles two-level inheritance correctly but fails at three or more levels.

### Expected Behavior

The innermost template's block content should always take precedence, regardless of how many inheritance levels exist. This is standard template inheritance semantics.

### What We Know

- The issue is in the template compilation or rendering phase, not in template loading
- Two-level inheritance works correctly
- The bug appears when blocks are nested inside other blocks (not top-level blocks)
- No tests exist for this specific three-level nested scenario

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Fix the nested block inheritance resolution to correctly handle 3+ levels
2. Study the template engine's block compilation and rendering code to understand how block resolution works
3. The fix should handle arbitrary depth of template inheritance
4. Must not break existing two-level inheritance behavior
5. Valid Python syntax
6. Changes limited to `django/template/`

## Success Criteria

- Nested blocks at 3+ inheritance levels render correctly
- Fix is in `django/template/` package
- Existing template inheritance behavior preserved
- Valid Python syntax
