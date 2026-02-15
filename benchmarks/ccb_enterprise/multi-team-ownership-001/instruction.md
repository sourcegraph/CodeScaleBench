# Fix ModelChoiceField Value Display with Custom to_field

**Repository:** django/django
**Your Team:** Forms Team
**Access Scope:** You own `django/forms/`. You may read `django/db/models/` to understand ORM field contracts, but all code changes must be in `django/forms/`.

## Context

You are a developer on the Django Forms team. The ORM Team owns `django/db/models/` and `django/db/backends/`. Your team owns all form rendering, validation, and field logic in `django/forms/`.

A user has reported a bug: when a `ModelChoiceField` is backed by a `ForeignKey` that uses a custom `to_field` (e.g., `to_field="slug"` instead of the default primary key), the initial value display in the rendered `<select>` widget is broken. The selected option shows the wrong item because `prepare_value()` falls back to `.pk` even when `to_field_name` is set.

## Bug Details

When `ForeignKey(to_field="slug")` generates a form field via `formfield()`, it passes `to_field_name="slug"` to `ModelChoiceField`. The field stores this in `self.to_field_name`. However, when the form is rendered with an initial model instance value, the `prepare_value()` method in `ModelChoiceField` does not consistently use `to_field_name` for value extraction, causing a mismatch between the `<option value="...">` attributes and the selected value.

## Task

Fix `ModelChoiceField.prepare_value()` in `django/forms/models.py` so that when `to_field_name` is set, it correctly extracts the value using that field rather than defaulting to `.pk`.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Read `django/forms/models.py` to find the `ModelChoiceField` class and its `prepare_value()` method
2. Read `django/db/models/fields/related.py` to understand how `ForeignKey.formfield()` passes `to_field_name` to the form field — this tells you what the form field receives
3. Trace how `ModelChoiceIterator` in `django/forms/models.py` generates `<option>` values — each option's value comes from `self.field.prepare_value(obj)`. The selected value must match one of these
4. Fix `prepare_value()` to use `self.to_field_name` when available. Specifically:
   - If the value is a model instance (has `_meta` attribute) and `self.to_field_name` is set, use `value.serializable_value(self.to_field_name)`
   - If `self.to_field_name` is not set, fall back to `value.pk`
5. Also check `_get_choices()` and the `ModelChoiceIterator.choice()` method to ensure option values are generated consistently with the fix
6. Write a small test in `django/forms/models.py` or a standalone test file is NOT required — the verifier checks the fix directly

### Hints

- `ModelChoiceField` is defined around line 1400+ in `django/forms/models.py`
- `prepare_value()` is a short method — look at what it does with `hasattr(value, '_meta')`
- `ModelChoiceIterator.choice()` calls `self.field.prepare_value(obj)` to get each option's value
- The `to_python()` method also uses `self.to_field_name` — compare its logic to `prepare_value()`
- You need to understand 8+ files: `models.py` (forms), `related.py`, `fields/__init__.py` (models), `options.py`, `base.py` in models, plus the widget rendering chain

## Success Criteria

- `ModelChoiceField.prepare_value()` correctly uses `to_field_name` when set
- The fix is consistent with how `to_python()` uses `to_field_name`
- All changes are within `django/forms/` only
- Python syntax is valid: `python3 -c "import ast; ast.parse(open('django/forms/models.py').read())"`
