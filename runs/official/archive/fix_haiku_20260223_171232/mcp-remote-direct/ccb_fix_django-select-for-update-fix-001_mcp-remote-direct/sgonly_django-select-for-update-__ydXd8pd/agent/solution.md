# Django select_for_update(of=...) Crash with Annotation Expressions - Bug Analysis

## Files Examined
- `django/db/models/sql/compiler.py` — examined for `get_select_for_update_of_arguments()` method and the buggy `.target.model` access
- `django/db/models/sql/query.py` — examined for `set_values()` method to understand how `values_list()` builds the SELECT list
- `django/db/models/query.py` — examined for `values_list()` method to understand user-facing API
- `django/db/models/expressions.py` — examined to understand the `Col` class and `.target` attribute
- `tests/select_for_update/tests.py` — examined for existing test coverage

## Dependency Chain

1. **Symptom observed in**: User code
   - Queryset: `Person.objects.select_for_update(of=("self",)).values_list(Concat(Value("Dr. "), F("name")), "born")`
   - Error: `AttributeError` on accessing `.target.model`

2. **Called from**: `SQLCompiler.get_select_for_update_of_arguments()` in `django/db/models/sql/compiler.py` line 1405
   - Called during SQL compilation to generate the `FOR UPDATE OF` clause

3. **Bug triggered by**: Line 1424 and line 1440 in `django/db/models/sql/compiler.py`
   - Tries to access `.target.model` on all items in `self.select`
   - Fails when items are annotation expressions (which don't have `.target`)

## Root Cause

- **File**: `django/db/models/sql/compiler.py`
- **Functions**:
  - `get_select_for_update_of_arguments()` (line 1405)
    - Nested function `_get_parent_klass_info()` (line 1411)
    - Nested function `_get_first_selected_col_from_model()` (line 1430)

- **Line(s)**:
  - Line 1424-1425 (in `_get_parent_klass_info`)
  - Line 1440 (in `_get_first_selected_col_from_model`)

- **Explanation**:

The bug occurs because the `get_select_for_update_of_arguments()` method assumes that every item in `self.select` is a `Col` expression object with a `.target` attribute. However, when `values_list()` is combined with annotation expressions, the SELECT list can contain non-`Col` expressions (like `Concat`, `Value`, `F`, etc.) that don't have a `.target` attribute.

### How the bug manifests:

1. When `values_list(Concat(...), "born")` is called, it creates annotation expressions
2. The `_values()` method calls `annotate()` to register the annotation
3. Then `set_values()` in `Query` builds a `selected` dictionary that preserves the order of fields as passed to `values_list()`
4. In `get_select()` of `SQLCompiler`, when `self.query.selected` is not None, it builds the `select` list by iterating through `selected.items()`, which means annotations can appear before model field columns
5. When `get_select_for_update_of_arguments()` is called, it tries to access `.target.model` on items in `self.select`
6. If an annotation expression is at index 0 (or any position before model fields), accessing `.target` raises an `AttributeError`

### Why this wasn't caught before:

Prior to the `values()`/`values_list()` field ordering change, model field columns were always placed first in the SELECT clause (before annotations). This meant that when looking for model fields by checking `.target.model`, the code would always find them at the expected positions. The bug only manifests when annotations can appear before model field columns in the SELECT list.

## Proposed Fix

The fix adds defensive `hasattr()` checks before accessing `.target` on select expressions. This ensures that annotation expressions (which don't have `.target`) are safely skipped.

### Change 1: Fix _get_parent_klass_info() (lines 1423-1426)

**Before:**
```python
if (
    self.select[select_index][0].target.model == parent_model
    or self.select[select_index][0].target.model in all_parents
)
```

**After:**
```python
if (
    hasattr(self.select[select_index][0], "target")
    and (
        self.select[select_index][0].target.model == parent_model
        or self.select[select_index][0].target.model in all_parents
    )
)
```

### Change 2: Fix _get_first_selected_col_from_model() (lines 1439-1441)

**Before:**
```python
for select_index in klass_info["select_fields"]:
    if self.select[select_index][0].target.model == concrete_model:
        return self.select[select_index][0]
```

**After:**
```python
for select_index in klass_info["select_fields"]:
    if (
        hasattr(self.select[select_index][0], "target")
        and self.select[select_index][0].target.model == concrete_model
    ):
        return self.select[select_index][0]
```

### Complete Unified Diff

```diff
--- a/django/db/models/sql/compiler.py
+++ b/django/db/models/sql/compiler.py
@@ -1420,9 +1420,10 @@ class SQLCompiler(BaseSQL):
                     "select_fields": [
                         select_index
                         for select_index in klass_info["select_fields"]
                         # Selected columns from a model or its parents.
-                        if (
+                        if (hasattr(self.select[select_index][0], "target")
+                            and (
                             self.select[select_index][0].target.model == parent_model
                             or self.select[select_index][0].target.model in all_parents
-                        )
+                            )
+                        )
                     ],
                 }

@@ -1437,7 +1438,9 @@ class SQLCompiler(BaseSQL):
             """
             concrete_model = klass_info["model"]._meta.concrete_model
             for select_index in klass_info["select_fields"]:
-                if self.select[select_index][0].target.model == concrete_model:
+                if (
+                    hasattr(self.select[select_index][0], "target")
+                    and self.select[select_index][0].target.model == concrete_model
+                ):
                     return self.select[select_index][0]
```

## Justification for Using hasattr() Check

The proposed fix using `hasattr(expr, "target")` is consistent with existing Django code in the same file. At line 213 in the GROUP BY logic, the code already uses:

```python
hasattr(expr, "target")
and expr.target.primary_key
```

This confirms that:
1. The `hasattr()` approach is the established pattern in Django for handling mixed expression types
2. The fix is consistent with the codebase's defensive programming practices
3. Expressions can have or not have a `.target` attribute, and both cases must be handled

## Alternative Fix (Using isinstance)

Using `isinstance()` check instead of `hasattr()`:

```python
from django.db.models.expressions import Col

# In _get_first_selected_col_from_model:
for select_index in klass_info["select_fields"]:
    expr = self.select[select_index][0]
    if isinstance(expr, Col) and expr.target.model == concrete_model:
        return expr
```

However, the `hasattr()` approach is preferred because:
1. It's already established in this file at line 213
2. It's more flexible if other expression types with `.target` are added in the future
3. It doesn't require importing `Col`

## Analysis

### How values_list() builds the SELECT list:

1. `values_list(*fields, **expressions)` in `query.py:1369` takes positional arguments (fields) and keyword arguments (annotations)
2. It calls `_values(*_fields, **expressions)` where `expressions` are added via `annotate()`
3. `set_values(fields)` in `query.py:2492` builds the `selected` dictionary:
   - For each field, it checks if it's an extra, annotation, or regular field
   - If it's an annotation, it stores the annotation name as a string: `selected[f] = f`
   - If it's a regular field, it stores the index: `selected[f] = len(field_names)`
   - The order in `selected` matches the order of fields passed to `values_list()`

4. `get_select()` in `compiler.py:230` processes the `selected` dictionary:
   ```python
   for alias, expression in self.query.selected.items():
       if isinstance(expression, str):
           expression = self.query.annotations[expression]  # Get the annotation expression
       elif isinstance(expression, int):
           expression = cols[expression]  # Get the column
       selected.append((alias, expression))
   ```
   - This preserves the order from `self.query.selected`
   - If annotations come first in the user's `values_list()` call, they appear first in `selected` and then in `self.select`

### Why the fix works:

The fix adds a check `hasattr(self.select[select_index][0], "target")` before accessing `.target`. This ensures that:

1. Only `Col` expressions (which represent actual database columns) are considered for `select_for_update(of=...)`
2. Annotation expressions are safely skipped, as they don't represent model columns that need locking
3. The method correctly identifies which model fields are present in the SELECT list, regardless of annotation ordering

This is semantically correct because:
- `select_for_update(of=(...))` is designed to lock specific tables/models in the database
- Only `Col` expressions represent actual database columns that need locking
- Annotations are computed values that don't correspond to specific table columns, so they shouldn't affect which tables are locked

### Testing recommendation:

Add a test case to `tests/select_for_update/tests.py`:
```python
@skipUnlessDBFeature("has_select_for_update_of")
def test_for_update_of_with_values_list_annotation(self):
    """
    select_for_update(of=...) should work correctly when values_list()
    contains annotation expressions before model fields.
    """
    with transaction.atomic():
        # This should not raise AttributeError
        values = list(
            Person.objects.select_for_update(of=("self",)).values_list(
                Concat(Value("Dr. "), F("name")), "pk"
            )
        )
    self.assertEqual(len(values), 1)
    self.assertTrue(values[0][0].startswith("Dr. "))
```

