# Fix Form Dropdown Showing Wrong Selection for Non-PK Foreign Keys

**Repository:** django/django
**Your Team:** Forms Team
**Access Scope:** You own `django/forms/`. You may read `django/db/models/` to understand ORM field contracts, but all code changes must be in `django/forms/`.

## Context

You are a developer on the Django Forms team. The ORM Team owns `django/db/models/` and `django/db/backends/`. Your team owns all form rendering, validation, and field logic in `django/forms/`.

## Bug Report

**Reported by:** Django Forum user
**Severity:** High
**Django version:** Current main branch

When a model has a ForeignKey that references a non-primary-key field (using the `to_field` parameter), forms generated from that model display the wrong selected option in dropdown (`<select>`) widgets.

**Steps to reproduce:**

```python
# Models
class Country(models.Model):
    code = models.CharField(max_length=2, unique=True)  # e.g., "US", "GB"
    name = models.CharField(max_length=100)

class City(models.Model):
    name = models.CharField(max_length=100)
    country = models.ForeignKey(Country, to_field="code", on_delete=models.CASCADE)

# Form for City — the country dropdown shows wrong selection
form = CityForm(instance=existing_city)
```

The `<option>` elements in the dropdown are generated with `value="US"`, `value="GB"`, etc. (using the `code` field as expected). But when rendering a form with an existing City instance, the initial selected value resolves to the Country's numeric primary key (integer ID) instead of the `code` value. This causes a mismatch — the form renders with no option selected, or the wrong option highlighted.

**Expected behavior:** When a ForeignKey uses `to_field="code"`, the form field should use the `code` field consistently — both for generating `<option>` values AND for determining which option is currently selected.

**Observed behavior:** Option values use `code`, but the selected value comparison uses the primary key, causing a mismatch.

## Task

Find and fix the inconsistency in how Django's model-backed choice fields extract values when a non-default foreign key field is configured.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. The form field must consistently use the configured foreign key field (not the primary key) for value extraction
2. The fix must be consistent with how the same field validates incoming submitted data
3. All changes must be within `django/forms/` only
4. Python syntax must be valid

## Success Criteria

- Form dropdowns correctly show the selected option for non-PK foreign keys
- The fix is consistent with the field's existing validation logic
- All changes are within `django/forms/` only
- Python syntax is valid
