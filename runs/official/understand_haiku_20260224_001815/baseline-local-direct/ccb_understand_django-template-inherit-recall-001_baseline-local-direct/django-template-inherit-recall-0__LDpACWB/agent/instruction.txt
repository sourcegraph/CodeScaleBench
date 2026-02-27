# Fix Template Engine Regression: Nested Block Inheritance

**Repository:** django/django
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
