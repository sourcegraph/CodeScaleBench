# Add Pre-Validation Signal to Django Models

**Repository:** django/django
**Access Scope:** You may modify files in `django/db/models/`. You may read any file to understand existing patterns.

## Context

Django's ORM provides a signal dispatching system that allows decoupled applications to get notified when certain actions occur. The framework has built-in signals for model lifecycle events (saving, deleting, etc.), but there is currently no signal fired before model validation occurs.

Your workspace contains architecture documentation that describes the signal system. However, internal documentation in large codebases can become outdated as the framework evolves. **Always verify how the signal system actually works by reading the source code** — the existing implementation is the source of truth, not documentation.

## Feature Request

**From:** Data Integrity Team
**Priority:** P2

We need a `pre_validate` signal that fires before Django's model validation runs. This will let us attach custom pre-validation hooks (e.g., normalizing data, checking external constraints) without subclassing every model.

### Deliverables

Add a `pre_validate` signal to Django's model signals module that:

1. **Follows the existing signal patterns** — study how the existing model lifecycle signals (like those for saving and deleting) are defined and dispatched. Follow the exact same pattern for the new signal. Do NOT rely solely on documentation; read the actual source code.

2. Is defined alongside the other model signals in the appropriate module

3. Is dispatched before model validation occurs, receiving the model instance and any validation-related arguments

4. Can be connected to by external code using the standard signal connection mechanism

5. Is importable from the same location as other model signals

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. `pre_validate` signal must exist in Django's model signals module
2. Must follow the **actual** signal dispatch pattern used by existing signals (read the source, not just docs)
3. Must be dispatched before validation in the model's validation flow
4. Valid Python syntax
5. Changes limited to `django/db/models/`

## Success Criteria

- `pre_validate` signal is defined in the model signals module
- Follows the real signal dispatch pattern (as used by existing model signals)
- Signal is dispatched before validation
- Valid Python syntax
- Changes scoped to `django/db/models/`
