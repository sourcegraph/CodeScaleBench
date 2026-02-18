# big-code-django-arch-001: Django ORM Query Compilation Pipeline

This repository is large (~350K LOC). Use comprehensive search strategies for broad architectural queries rather than narrow, single-directory scopes.

## Task Type: Architectural Understanding

Your goal is to analyze and explain how Django compiles ORM queries into SQL. Focus on:

1. **Component identification**: Find all major components in the query pipeline (Manager, QuerySet, Query, Compiler, Expressions, Lookups)
2. **Dependency mapping**: Trace the lazy evaluation chain from QuerySet API through compilation to execution
3. **Design pattern recognition**: Lazy evaluation, visitor pattern (compile/as_sql dispatch), backend abstraction via vendor dispatch
4. **Interface boundaries**: The `as_sql(compiler, connection)` protocol, `resolve_expression()`, and `RegisterLookupMixin`

## Output Format

Write your analysis to `/logs/agent/solution.md` with these required sections:

```markdown
## Files Examined
- path/to/file.ext — role in the architecture

## Dependency Chain
1. path/to/core.ext (foundational types/interfaces)
2. path/to/impl.ext (implementation layer)
3. path/to/integration.ext (integration/wiring layer)

## Analysis
[Your architectural analysis]
```

## Search Strategy

- Start with `django/db/models/query.py` (QuerySet) and `django/db/models/sql/compiler.py` (SQLCompiler)
- Explore `django/db/models/sql/query.py` for the internal Query representation
- Check `django/db/models/expressions.py` and `django/db/models/lookups.py` for the expression system
- Use `find_references` to trace how `as_sql` is called across the compilation pipeline
- Use `go_to_definition` to understand the backend dispatch mechanism
