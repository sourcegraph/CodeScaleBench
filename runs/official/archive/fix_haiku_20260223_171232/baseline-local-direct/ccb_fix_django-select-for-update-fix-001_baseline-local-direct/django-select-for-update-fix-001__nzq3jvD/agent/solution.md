# Django Bug Analysis: select_for_update(of) Crash with Annotation Expressions

## Files Examined

- `django/db/models/sql/compiler.py` — Entry point containing the buggy `get_select_for_update_of_arguments()` method
- `django/db/models/expressions.py` — Expression classes to understand structure of `Col` and other expressions
- `tests/select_for_update/tests.py` — Test suite for select_for_update functionality
- `tests/select_for_update/models.py` — Test models used for select_for_update tests

## Dependency Chain

1. **Symptom observed in**: User code combining `select_for_update(of=("self",))` with `values_list()` containing annotation expressions
   ```python
   Person.objects.select_for_update(of=("self",)).values_list(
       Concat(Value("Dr. "), F("name")), "born"
   )
   ```

2. **Called from**: `django/db/models/sql/compiler.py::SQLCompiler.as_sql()` (line 884)
   - This method calls `self.get_select_for_update_of_arguments()` to generate the FOR UPDATE OF clause

3. **Bug triggered by**: `django/db/models/sql/compiler.py::SQLCompiler.get_select_for_update_of_arguments()` (lines 1424-1425, 1440)
   - Nested functions `_get_parent_klass_info()` and `_get_first_selected_col_from_model()` access `.target.model` without checking if the attribute exists

## Root Cause

- **File**: `django/db/models/sql/compiler.py`
- **Function**: `get_select_for_update_of_arguments()` (nested functions)
- **Lines**: 1424-1425 (in `_get_parent_klass_info()`) and 1440 (in `_get_first_selected_col_from_model()`)

### Explanation

The bug occurs because of an assumption in the code that all expressions in `self.select` have a `.target` attribute. This assumption was previously valid because:

1. Prior to the field ordering change in Django, when using `values()`/`values_list()`, model field columns were always placed first in the SELECT clause.
2. Only `Col` expressions (which have a `.target` attribute pointing to model fields) would appear in the positions that `get_select_for_update_of_arguments()` processed.

However, after the field ordering change:

1. Annotation expressions (like `Concat(Value("Dr. "), F("name"))`) can now appear before model field columns in the SELECT clause.
2. These annotation expressions are stored in `self.select` as arbitrary expression objects that don't have a `.target` attribute.
3. When the code tries to access `.target.model` on these annotation expressions, it raises an `AttributeError`.

### Specific Issues

**Issue 1** - Line 1424-1425 in `_get_parent_klass_info()`:
```python
# OLD CODE (BUGGY):
if (
    self.select[select_index][0].target.model == parent_model
    or self.select[select_index][0].target.model in all_parents
)
```
This code filters `select_fields` to only include those that correspond to columns from a given parent model. However, it assumes all expressions have `.target.model`, which fails for annotation expressions.

**Issue 2** - Line 1440 in `_get_first_selected_col_from_model()`:
```python
# OLD CODE (BUGGY):
if self.select[select_index][0].target.model == concrete_model:
    return self.select[select_index][0]
```
This code searches for the first selected column from a specific model. Again, it assumes all expressions have `.target.model`.

## Proposed Fix

The fix adds `hasattr(...)` checks before accessing the `.target` attribute, following the pattern already used elsewhere in the compiler at line 213:

```python
# Pattern from line 213 (correct usage):
if (
    hasattr(expr, "target")
    and expr.target.primary_key
    and self.connection.features.allows_group_by_selected_pks_on_model(
        expr.target.model
    )
)
```

### Fix 1: _get_parent_klass_info()

```diff
- "select_fields": [
-     select_index
-     for select_index in klass_info["select_fields"]
-     # Selected columns from a model or its parents.
-     if (
-         self.select[select_index][0].target.model == parent_model
-         or self.select[select_index][0].target.model in all_parents
-     )
- ],

+ "select_fields": [
+     select_index
+     for select_index in klass_info["select_fields"]
+     # Selected columns from a model or its parents.
+     if (
+         hasattr(self.select[select_index][0], "target")
+         and (
+             self.select[select_index][0].target.model == parent_model
+             or self.select[select_index][0].target.model in all_parents
+         )
+     )
+ ],
```

### Fix 2: _get_first_selected_col_from_model()

```diff
  for select_index in klass_info["select_fields"]:
-     if self.select[select_index][0].target.model == concrete_model:
+     if (
+         hasattr(self.select[select_index][0], "target")
+         and self.select[select_index][0].target.model == concrete_model
+     ):
          return self.select[select_index][0]
```

## Analysis

### Why This Fix Works

1. **Minimal Change**: The fix only adds necessary checks without altering the overall logic.

2. **Correct Filtering**: By checking `hasattr(expr, "target")` first, the code now:
   - Skips annotation expressions that don't have a `.target` attribute
   - Only processes `Col` expressions (and other expressions with `.target`)
   - This ensures that only actual model field columns are considered for the FOR UPDATE OF clause

3. **Semantic Correctness**: The FOR UPDATE OF clause is meant to lock specific tables. When `values_list()` includes annotation expressions:
   - The annotations themselves shouldn't be locked (they're computed values, not table columns)
   - Only the actual table columns that are selected should be locked
   - By skipping annotations, the fix correctly identifies which tables to lock

4. **Follows Existing Patterns**: This approach is consistent with how the same issue is handled at line 213 of the same file, where `hasattr(expr, "target")` is used before accessing `expr.target.primary_key`.

### Execution Flow After Fix

1. User calls:
   ```python
   Person.objects.select_for_update(of=("self",)).values_list(
       Concat(Value("Dr. "), F("name")), "born"
   )
   ```

2. Query compilation calls `get_select_for_update_of_arguments()` which needs to determine which tables to lock.

3. The method iterates through `self.klass_info["select_fields"]` which contains indices into `self.select`.

4. For each index, it now checks `hasattr(self.select[select_index][0], "target")`:
   - If it's a `Col` expression (has `.target`): The check passes, and the model is evaluated
   - If it's an annotation (no `.target`): The check fails, and the expression is skipped

5. Only actual model columns are used to determine which tables to lock, allowing the query to execute successfully.

## Testing

A test was added to the test suite to verify this fix:

```python
@skipUnlessDBFeature("has_select_for_update_of")
def test_for_update_of_followed_by_values_list_with_annotation(self):
    """
    select_for_update(of=['self']) followed by values_list() with
    annotation expressions.
    """
    from django.db.models import Value, F
    from django.db.models.functions import Concat

    with transaction.atomic():
        values = list(
            Person.objects.select_for_update(of=("self",)).values_list(
                Concat(Value("Dr. "), F("name")), "born__name"
            )
        )
    self.assertEqual(len(values), 1)
    self.assertEqual(values[0][0], "Dr. Reinhardt")
    self.assertEqual(values[0][1], self.city1.name)
```

All existing tests pass after applying the fix.
