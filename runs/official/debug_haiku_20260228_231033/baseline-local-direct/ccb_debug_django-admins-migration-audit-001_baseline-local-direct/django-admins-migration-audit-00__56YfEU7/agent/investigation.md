# Investigation Report: Django ADMINS/MANAGERS Settings Format Migration

**Investigation Date:** 2026-02-28
**Repository:** django/django (Mirror at aed303aff57ac990894b6354af001b0e8ea55f71)
**Task:** Audit codebase for ADMINS/MANAGERS format migration from `[(name, email), ...]` tuples to `[email, ...]` strings

---

## Summary

Django's `ADMINS` and `MANAGERS` settings currently use a tuple format `[(Full Name, email@example.com), ...]` that is unpacked in multiple locations to extract email addresses. A planned migration to a simple string list format `[email@example.com, ...]` will require changes across:
- 2 core mail/logging modules that validate and unpack the tuple format
- 1 email sending utility function
- Multiple test files using the old format
- Documentation describing the tuple format

**Total files requiring changes: 9 files** (2 core, 1 utility, 2 tests, 4+ docs)

---

## Root Cause

The current implementation in `django/core/mail/__init__.py` at line 135-142 validates that ADMINS and MANAGERS are lists of 2-tuples and unpacks them with `a[1]` to extract only the email address portion:

```python
# Line 135-136: Validation requiring 2-tuples
if not all(isinstance(a, (list, tuple)) and len(a) == 2 for a in recipients):
    raise ValueError(f"The {setting_name} setting must be a list of 2-tuples.")

# Line 142: Unpacking format - [a[1] for a in recipients]
to=[a[1] for a in recipients],
```

This pattern is replicated in:
1. The validation logic in `_send_server_message()`
2. Test fixtures that use `@override_settings()` decorators
3. Documentation examples throughout the codebase

---

## Evidence

### Core Implementation Files

#### 1. **django/core/mail/__init__.py** (Lines 122-148)
**Function:** `_send_server_message()`

Current code unpacks 2-tuples:
```python
# Line 131: Get recipients from settings
recipients = getattr(settings, setting_name)

# Line 135-136: VALIDATES 2-tuple format
if not all(isinstance(a, (list, tuple)) and len(a) == 2 for a in recipients):
    raise ValueError(f"The {setting_name} setting must be a list of 2-tuples.")

# Line 142: UNPACKS tuples - extracts email from position [1]
to=[a[1] for a in recipients],
```

**Called by:**
- `mail_admins()` at line 150-161 (passes `setting_name="ADMINS"`)
- `mail_managers()` at line 164-175 (passes `setting_name="MANAGERS"`)

**Impact:** These are the primary functions users call to send emails to admins/managers. Changing this breaks the tuple format contract.

#### 2. **django/utils/log.py** (Lines 79-101)
**Class:** `AdminEmailHandler` (logging handler)

```python
# Line 97: Checks if ADMINS setting is truthy
if (
    not settings.ADMINS
    and self.send_mail.__func__ is AdminEmailHandler.send_mail
):
    return
```

**Current behavior:** Checks if ADMINS is non-empty. The handler calls `mail.mail_admins()` internally (line 138), which will validate the tuple format.

**Impact:** Needs validation that the new string format doesn't break this check.

---

### Test Files Using Old Tuple Format

#### 3. **tests/mail/test_sendtestemail.py** (Lines 6-14)
Uses `@override_settings()` with 2-tuple format:
```python
@override_settings(
    ADMINS=(
        ("Admin", "admin@example.com"),
        ("Admin and Manager", "admin_and_manager@example.com"),
    ),
    MANAGERS=(
        ("Manager", "manager@example.com"),
        ("Admin and Manager", "admin_and_manager@example.com"),
    ),
)
```

**Tests using this:**
- Lines 61-75: `test_manager_receivers()` - expects email extraction from tuple[1]
- Lines 77-91: `test_admin_receivers()` - expects email extraction from tuple[1]
- Lines 93-115: `test_manager_and_admin_receivers()` - expects email extraction from tuple[1]

#### 4. **tests/logging_tests/tests.py** (Lines 250-283)
Uses `@override_settings()` with 2-tuple format in `AdminEmailHandlerTest`:
```python
@override_settings(
    ADMINS=[("whatever admin", "admin@example.com")],
    EMAIL_SUBJECT_PREFIX="-SuperAwesomeSubject-",
)
```

**Tests using this:**
- Lines 254-280: `test_accepts_args()` - expects ADMINS as list of tuples
- Line 283+: Additional tests with ADMINS override

Also uses single-element tuples in another test (line 283).

#### 5. **tests/view_tests/tests/test_debug.py** (Lines 1454, 1490, 1533)
Uses `@override_settings()` with 2-tuple format in multiple debug view tests:
```python
with self.settings(ADMINS=[("Admin", "admin@fattie-breakie.com")]):
```

**Tests affected:** Multiple email report validation tests.

#### 6. **tests/middleware/tests.py** (Line 392)
Uses `@override_settings()` with 2-tuple format:
```python
@override_settings(
    IGNORABLE_404_URLS=[re.compile(r"foo")],
    MANAGERS=[("PHD", "PHB@dilbert.com")],
)
```

**Tests using this:** `BrokenLinkEmailsMiddlewareTest` class (lines 394-486)

#### 7. **tests/mail/tests.py**
Large test file with extensive mail testing. References to mail_admins/mail_managers throughout but doesn't show explicit ADMINS/MANAGERS overrides in the examined section.

---

### Documentation Files

#### 8. **docs/ref/settings.txt** (Lines 43-58)
**ADMINS Setting:**
```
Each item in the list should be a tuple of (Full name, email address). Example::

    [("John", "john@example.com"), ("Mary", "mary@example.com")]
```

**MANAGERS Setting (Lines 2066-2075):**
```
A list in the same format as :setting:`ADMINS` that specifies who should get
broken link notifications...
```

#### 9. **docs/topics/email.txt**
Documents `mail_admins()` and `mail_managers()` functions with references to ADMINS/MANAGERS settings.

#### 10. **docs/howto/error-reporting.txt**
Documents error reporting which mentions ADMINS setting format.

#### 11. **docs/ref/logging.txt**
Documents AdminEmailHandler which uses ADMINS.

#### 12. **docs/ref/middleware.txt**
Documents BrokenLinkEmailsMiddleware which uses MANAGERS.

---

## Affected Components

### Email System (`django.core.mail`)
- **Module:** `django/core/mail/__init__.py`
- **Key functions:** `mail_admins()`, `mail_managers()`, `_send_server_message()`
- **Change required:** Update validation and unpacking logic
- **Backward compatibility impact:** **HIGH** - existing settings will break

### Logging System (`django.utils.log`)
- **Module:** `django/utils/log.py`
- **Key class:** `AdminEmailHandler`
- **Change required:** Verify compatibility after core mail changes
- **Backward compatibility impact:** **MEDIUM** - depends on `mail_admins()` changes

### Management Command (`django.core.management.commands`)
- **Module:** `django/core/management/commands/sendtestemail.py`
- **Change required:** Update command to handle new format (if settings are changed)
- **Backward compatibility impact:** **LOW** - command doesn't validate format directly

### Middleware (`django.middleware`)
- **Module:** `django/middleware/common.py`
- **Key class:** `BrokenLinkEmailsMiddleware`
- **Change required:** Verify compatibility after core mail changes
- **Backward compatibility impact:** **MEDIUM** - depends on `mail_managers()` changes

### Default Settings (`django.conf`)
- **Module:** `django/conf/global_settings.py`
- **Change required:** Update comments on lines 24-25 and 172-174
- **Current:** Documents old tuple format
- **Backward compatibility impact:** **LOW** - documentation only

---

## Third-Party Compatibility Concerns

### Breaking Changes for Users

1. **Settings Validation Error:** Users with old-format settings will get a `ValueError` at runtime when `mail_admins()` or `mail_managers()` is called:
   ```
   ValueError: The ADMINS setting must be a list of 2-tuples.
   ```
   This occurs in production when errors happen and need to be reported.

2. **No Migration Path:** The migration needs a deprecation period with:
   - A warning when old format is detected
   - Support for both formats during transition
   - Clear documentation of migration steps

3. **Integration Points:** Third-party packages that:
   - Override ADMINS/MANAGERS settings
   - Read these settings directly
   - Use `mail_admins()` or `mail_managers()`

   Will all break unless they update their code.

### Data Validation

The requirement `len(a) == 2` will immediately break if changed to string list. Must handle:
- Strings (new format)
- Tuples (old format - for deprecation period)
- Lists (old format - technically also valid)

---

## Migration Checklist

### Phase 1: Prepare (Add deprecation warning)

- [ ] **django/core/mail/__init__.py** - Lines 135-142
  - **Change needed:** Update `_send_server_message()` to:
    - Accept both tuple format `(name, email)` and string format `email`
    - Add deprecation warning for tuple format
    - Update validation to `isinstance(a, str)` OR `(isinstance(a, (list, tuple)) and len(a) == 2)`
    - Update unpacking to `a if isinstance(a, str) else a[1]`
  - **Files to update:** `_send_server_message()` function

- [ ] **django/conf/global_settings.py** - Lines 24-26, 172-174
  - **Change needed:** Update comments to mention deprecation
  - **Current:** Comments describe tuple format only
  - **New:** Add note about string format being preferred

### Phase 2: Update Validation & Documentation

- [ ] **django/conf/global_settings.py** - Lines 24-26
  - **File:** `django/conf/global_settings.py`
  - **Change:** Update comment from:
    ```
    # [('Full Name', 'email@example.com'), ('Full Name', 'anotheremail@example.com')]
    ```
    To mention both formats during transition period

- [ ] **django/conf/global_settings.py** - Lines 172-174
  - **File:** `django/conf/global_settings.py`
  - **Change:** Update MANAGERS comment similarly

- [ ] **docs/ref/settings.txt** - Lines 43-58 (ADMINS)
  - **File:** `docs/ref/settings.txt`
  - **Change:** Update example and description to note the new string format is preferred
  - **Add deprecation notice:** Old tuple format is deprecated

- [ ] **docs/ref/settings.txt** - Lines 2066-2075 (MANAGERS)
  - **File:** `docs/ref/settings.txt`
  - **Change:** Similarly update MANAGERS documentation

- [ ] **docs/topics/email.txt**
  - **File:** `docs/topics/email.txt`
  - **Change:** Update examples for `mail_admins()` and `mail_managers()`
  - **Add:** Migration guide noting format change

- [ ] **docs/howto/error-reporting.txt**
  - **File:** `docs/howto/error-reporting.txt`
  - **Change:** Update to reflect new string format

- [ ] **docs/ref/logging.txt**
  - **File:** `docs/ref/logging.txt`
  - **Change:** Update AdminEmailHandler documentation

- [ ] **docs/ref/middleware.txt**
  - **File:** `docs/ref/middleware.txt`
  - **Change:** Update BrokenLinkEmailsMiddleware documentation

### Phase 3: Update Tests

- [ ] **tests/mail/test_sendtestemail.py** - Lines 6-14
  - **File:** `tests/mail/test_sendtestemail.py`
  - **Change:** Update `@override_settings()` to use new string format
  - **Current:**
    ```python
    ADMINS=(("Admin", "admin@example.com"), ...)
    MANAGERS=(("Manager", "manager@example.com"), ...)
    ```
  - **New:**
    ```python
    ADMINS=["admin@example.com", ...]
    MANAGERS=["manager@example.com", ...]
    ```
  - **Tests affected:** All methods in `SendTestEmailManagementCommand` class

- [ ] **tests/logging_tests/tests.py** - Lines 250-283+
  - **File:** `tests/logging_tests/tests.py`
  - **Change:** Update `@override_settings()` decorators for ADMINS
  - **Classes affected:** `AdminEmailHandlerTest`
  - **Update all instances:** Line 251, 283, and any others

- [ ] **tests/view_tests/tests/test_debug.py** - Lines 1454, 1490, 1533
  - **File:** `tests/view_tests/tests/test_debug.py`
  - **Change:** Update `self.settings(ADMINS=...)` calls
  - **Methods affected:** `verify_unsafe_email()`, `verify_safe_email()`, `verify_paranoid_email()`

- [ ] **tests/middleware/tests.py** - Line 392
  - **File:** `tests/middleware/tests.py`
  - **Change:** Update `@override_settings(MANAGERS=...)` decorator
  - **Class affected:** `BrokenLinkEmailsMiddlewareTest`

- [ ] **tests/mail/tests.py**
  - **File:** `tests/mail/tests.py`
  - **Change:** Review entire file for any ADMINS/MANAGERS overrides
  - **Action:** Update any found to use new format

### Phase 4: Implement Core Changes (After deprecation period)

- [ ] **django/core/mail/__init__.py** - Lines 135-142
  - **Change needed:** Remove deprecation warning and tuple support
  - **Simplify validation:** `if not all(isinstance(a, str) for a in recipients):`
  - **Simplify unpacking:** `to=recipients` (no unpacking needed)
  - **Update ValueError:** Better error message for new format

- [ ] **django/utils/log.py** - Review after mail changes
  - **File:** `django/utils/log.py`
  - **Change:** Verify AdminEmailHandler still works correctly
  - **Test:** Ensure compatibility with new mail system

---

## Backward Compatibility Strategy

### Recommended Approach

1. **Deprecation Period (Django X.X - Y.Y):**
   - Support both formats
   - Issue `RemovedInDjangoZZ00Warning` when old format detected
   - Update documentation to recommend new format

2. **Migration Steps for Users:**
   - Convert `ADMINS = [("Name", "email@example.com")]`
   - To `ADMINS = ["email@example.com"]`
   - Convert `MANAGERS = [("Name", "email@example.com")]`
   - To `MANAGERS = ["email@example.com"]`

3. **Breaking Change (Future Django version):**
   - Remove support for tuple format
   - Only accept string lists

---

## System Test Coverage Notes

The following test classes/methods validate the current ADMINS/MANAGERS behavior and will need updates:

1. **SendTestEmailManagementCommand** - 5 test methods
2. **AdminEmailHandlerTest** - Multiple test methods
3. **Debug view tests** - Multiple verify_* methods
4. **BrokenLinkEmailsMiddlewareTest** - 6+ test methods
5. **Mail tests** - Various comprehensive email tests

All these tests use `@override_settings()` decorators with the current tuple format and will need conversion to the new string format.

---

## Conclusion

The migration from tuple-based ADMINS/MANAGERS to string-list format is a **breaking change** that requires:

1. **Code changes in 2 core modules** (mail, logging)
2. **Documentation updates across 6+ files**
3. **Test updates in 5 test files**
4. **Deprecation period** to warn existing users
5. **Clear migration guide** for end users

The changes are scoped and contained primarily to the email sending pipeline (`_send_server_message()`) and its callers. The implementation is straightforward but affects public API contracts, requiring careful rollout.

**Estimated scope:** Medium-sized change suitable for minor/major Django version bump with deprecation cycle.
