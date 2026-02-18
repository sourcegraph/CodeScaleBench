# big-code-django-arch-001: Django ORM Query Compilation Pipeline

## Task

Map the Django ORM query compilation pipeline from QuerySet to SQL. Trace how a high-level QuerySet API call (e.g., `Model.objects.filter(...)`) is lazily constructed, compiled into SQL, and executed against the database, including the expression/lookup system and backend-specific vendor dispatch.

## Context

- **Repository**: django/django (Python, ~350K LOC)
- **Category**: Architectural Understanding
- **Difficulty**: hard
- **Subsystem Focus**: django/db/models/ and django/db/backends/ — the ORM query compilation layer

## Requirements

1. Identify all files involved in the query compilation pipeline (Manager, QuerySet, Query, Compiler, Expressions, Lookups, Backend)
2. Trace the dependency chain from `Manager.get_queryset()` through lazy query building, compilation via `as_sql()`, to `execute_sql()`
3. Document the `compile(node)` vendor dispatch mechanism (`as_{vendor}()` pattern)
4. Explain how the WhereNode tree structure, Expression protocol, and Lookup system compose to produce SQL

## Expected Output

Write your analysis to `/logs/agent/solution.md` with the following structure:

```
## Files Examined
- path/to/file1.ext — role in architecture
- path/to/file2.ext — role in architecture
...

## Dependency Chain
1. Entry point: path/to/entry.ext
2. Calls: path/to/next.ext (via function/method name)
3. Delegates to: path/to/impl.ext
...

## Analysis
[Detailed architectural analysis including:
- Design patterns identified
- Component responsibilities
- Data flow description
- Interface contracts between components]

## Summary
[Concise 2-3 sentence summary answering the task question]
```

## Evaluation Criteria

- File recall: Did you find the correct set of architecturally relevant files?
- Dependency accuracy: Did you trace the correct dependency/call chain?
- Architectural coherence: Did you correctly identify the design patterns and component relationships?
