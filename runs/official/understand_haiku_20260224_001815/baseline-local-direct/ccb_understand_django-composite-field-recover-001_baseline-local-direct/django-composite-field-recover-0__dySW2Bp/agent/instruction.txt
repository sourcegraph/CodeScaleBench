# Add Composite Field Validator for Django Forms

**Repository:** django/django
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
