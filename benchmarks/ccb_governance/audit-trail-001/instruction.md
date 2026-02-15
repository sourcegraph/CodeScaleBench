# Fix Template Include Tag Context Isolation Bug + Audit Trail

**Repository:** django/django
**Your Role:** Platform Security Engineer
**Access Scope:** You may modify files in `django/template/` and `tests/`. You must produce an audit trail of every file you access.

## Context

You are a platform security engineer auditing Django's template engine. As part of the security review process, you must:
1. Fix a reported bug in the template system
2. Produce an **audit.log** file at `/workspace/audit.log` documenting every source file you read or modify during the investigation

The audit log is a compliance requirement — it must be a complete record of your file access during this task.

## Bug Report

Django's `{% include %}` template tag with the `only` keyword should isolate the included template's context — passing only explicitly specified variables. However, the current implementation in `django/template/loader_tags.py` has a bug: when `{% include "child.html" only %}` is used, the included template can still access `forloop` variables from an enclosing `{% for %}` loop in the parent template.

This is a context isolation violation — the `only` keyword should create a completely clean context, but `forloop` leaks through because it is added to the context by the `{% for %}` tag at a different stage than normal variable resolution.

## Task

Fix the `IncludeNode` in `django/template/loader_tags.py` so that `{% include ... only %}` properly isolates the context, preventing `forloop` and other special variables from leaking into the included template.

**YOU MUST IMPLEMENT CODE CHANGES AND PRODUCE AN AUDIT LOG.**

### Requirements

1. Fix the `IncludeNode.render()` method in `django/template/loader_tags.py` to ensure that when `isolated_context=True` (the `only` keyword), no variables from the parent context leak through — including special variables like `forloop`
2. Trace how context works in Django templates:
   - `django/template/context.py` — `Context`, `RenderContext`, `RequestContext` classes
   - `django/template/loader_tags.py` — `IncludeNode`, `BlockNode`, `ExtendsNode`
   - `django/template/defaulttags.py` — `ForNode` adds `forloop` to context
   - `django/template/base.py` — `Template.render()`, `NodeList.render()`
3. The fix should ensure `Context.new()` creates a truly isolated context without special variables from the parent
4. **Audit log requirement**: Create a file at `/workspace/audit.log` with one line per file you accessed, in this format:
   ```
   [READ] django/template/loader_tags.py
   [READ] django/template/context.py
   [MODIFIED] django/template/loader_tags.py
   ```
   Include every file you read or modified, in chronological order.

### Hints

- `IncludeNode.render()` is in `django/template/loader_tags.py` — look for where `isolated_context` is checked
- When `isolated_context=True`, `IncludeNode` calls `context.new(values)` to create a new context
- `Context.new()` is defined in `django/template/context.py` — check what it copies from the parent
- `ForNode` in `django/template/defaulttags.py` pushes `forloop` onto the context stack — understand at what level this exists
- The `RenderContext` (separate from the template `Context`) may also carry state — check if it leaks

## Success Criteria

- `{% include "child.html" only %}` no longer leaks `forloop` or other parent context variables
- Normal `{% include %}` (without `only`) still passes parent context correctly
- `/workspace/audit.log` exists and contains at least 3 `[READ]` entries referencing real django/template/ files
- Changes are limited to `django/template/` files
- Python syntax is valid
