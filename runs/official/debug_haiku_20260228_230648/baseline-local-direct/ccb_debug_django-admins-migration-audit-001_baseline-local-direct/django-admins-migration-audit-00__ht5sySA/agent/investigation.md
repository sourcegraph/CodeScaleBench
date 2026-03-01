# Django ADMINS/MANAGERS Settings Format Migration Audit

## Summary

Django's `ADMINS` and `MANAGERS` settings currently use a tuple-based format `[(name, email), ...]` that is validated, consumed, and unpacked by core mail functions. A migration to a simple string list format `[email, ...]` requires changes to validation logic in `django/core/mail/__init__.py`, test fixtures across 5 test modules, and documentation updates across 6 documentation files. Third-party code using tuple unpacking will break unless deprecation warnings are provided.

## Root Cause

The core validation and consumption of the tuple format occurs in a single critical function: `_send_server_message()` in `django/core/mail/__init__.py:122-147`, which:
1. Validates the setting is a list of 2-tuples (line 135-136)
2. Unpacks email addresses from index [1] of each tuple (line 142)
3. Is called by both `mail_admins()` and `mail_managers()` public APIs

## Evidence

### Core Code Paths (Tuple Format Consumption)

**Primary validation and unpacking:**
- **File:** `django/core/mail/__init__.py:135-142`
  ```python
  if not all(isinstance(a, (list, tuple)) and len(a) == 2 for a in recipients):
      raise ValueError(f"The {setting_name} setting must be a list of 2-tuples.")
  # ...
  to=[a[1] for a in recipients]  # Extracts email from tuple[1]
  ```
  This is the ONLY place in core Django that directly consumes the tuple format.

**Functions that depend on _send_server_message():**
- `django/core/mail/__init__.py:150-161` - `mail_admins()`
- `django/core/mail/__init__.py:164-175` - `mail_managers()`

**Secondary usage (indirectly consumes via mail_admins/mail_managers):**
- `django/core/management/commands/sendtestemail.py:43, 46` - Calls `mail_managers()` and `mail_admins()`
- `django/middleware/common.py:129` - Calls `mail_managers()` for 404 error notifications
- `django/utils/log.py:97-101` - `AdminEmailHandler.emit()` checks `if not settings.ADMINS` to determine if email should be sent, then calls `mail.mail_admins()` at line 138

### Test Files (Using Tuple Format)

1. **File:** `tests/mail/test_sendtestemail.py:6-14`
   - Lines 6-14: `@override_settings` decorators with tuple format
   - Example: `ADMINS=(("Admin", "admin@example.com"), ...)`

2. **File:** `tests/mail/tests.py:1780-1803` (Critical test coverage)
   - Lines 1782-1789: Test data with various tuple formats
   - Line 1802: **Tuple unpacking:** `for _, address in value` (extracts email from position [1])
   - Also includes validation test for wrong format: lines 1862-1879

3. **File:** `tests/logging_tests/tests.py` (Multiple occurrences)
   - Lines 251, 283, 322, 344, 375, 396: `@override_settings` with tuple format
   - Example at line 251: `ADMINS=[("whatever admin", "admin@example.com")]`

4. **File:** `tests/view_tests/tests/test_debug.py:1454, 1490, 1533`
   - `@override_settings` with tuple format
   - Example: `ADMINS=[("Admin", "admin@fattie-breakie.com")]`

5. **File:** `tests/middleware/tests.py:392`
   - `MANAGERS=[("PHD", "PHB@dilbert.com")]`

### Documentation Files (Format Specifications)

1. **File:** `docs/ref/settings.txt`
   - **ADMINS setting definition:** Explicitly documents format with example:
     ```
     Each item in the list should be a tuple of (Full name, email address). Example::
         [("John", "john@example.com"), ("Mary", "mary@example.com")]
     ```
   - **MANAGERS setting definition:** States "in the same format as ADMINS"

2. **File:** `docs/topics/email.txt`
   - Documents `mail_admins()` and `mail_managers()` functions
   - Indirectly references tuple format through setting link

3. **File:** `docs/howto/error-reporting.txt`
   - Explains ADMINS and MANAGERS usage in error reporting context
   - Lists ADMINS as recipients in "Server errors" section

4. **File:** `docs/topics/logging.txt`
   - Mentions `mail_admins` handler that emails ADMINS
   - References AdminEmailHandler

5. **File:** `docs/ref/logging.txt`
   - Documents `AdminEmailHandler` class
   - States: "This handler sends an email to the site ADMINS"

6. **File:** `docs/ref/django-admin.txt`
   - References sendtestemail command that uses ADMINS/MANAGERS

### Default Settings

**File:** `django/conf/global_settings.py:34-35`
```python
# People who get code error notifications. In the format
# [('Full Name', 'email@example.com'), ('Full Name', 'anotheremail@example.com')]
ADMINS = []
```
The comment explicitly documents tuple format.

## Affected Components

### Django Core Modules
1. **django.core.mail** - Primary consumer via `_send_server_message()`
2. **django.utils.log** - AdminEmailHandler depends on ADMINS existence
3. **django.core.management.commands** - sendtestemail command
4. **django.middleware.common** - BrokenLinkEmailsMiddleware for 404 notifications

### Testing Framework
1. **tests.mail** - Mail-specific tests with extensive tuple format usage
2. **tests.logging_tests** - Logging and error handling tests
3. **tests.view_tests** - Debug view tests
4. **tests.middleware** - Middleware tests

### Documentation
1. **Settings reference** - Format specification
2. **Email topics** - Function documentation
3. **Logging topics** - Handler documentation
4. **Error reporting guide** - User-facing documentation
5. **Admin management commands** - Command documentation

## Third-Party Compatibility

**Breaking Change Impact:**
- Any third-party code that unpacks ADMINS/MANAGERS tuples will break:
  ```python
  # Currently works:
  for name, email in settings.ADMINS:
      send_notification(email)

  # Will fail after migration to string list format:
  for email in settings.ADMINS:  # Would need to change to this
      send_notification(email)
  ```

**Recommendation for Compatibility:**
- Provide a **deprecation period** (1-2 releases) where both formats are supported
- Add validation that accepts both tuple format (with deprecation warning) and string format
- Update `_send_server_message()` to detect format and warn users
- Consider providing a migration utility/function for users

## Recommendation: Migration Checklist

### Phase 1: Add Dual-Format Support (Release N)

**File:** `django/core/mail/__init__.py:122-147`
- **Change Required:** Update `_send_server_message()` to accept both formats
- **Details:**
  - Add logic to detect tuple vs. string format
  - If tuple format: issue `DeprecationWarning`
  - Extract emails from appropriate position based on format
  - Document deprecation in docstring
- **Lines affected:** 135-142 (validation and unpacking)

**File:** `django/conf/global_settings.py:34-35`
- **Change Required:** Update comment to indicate new format is preferred
- **Details:** Update default value comment to show string list format

### Phase 2: Update Tests (Release N - same as Phase 1)

**File:** `tests/mail/test_sendtestemail.py:6-14`
- **Change Required:** Convert ADMINS/MANAGERS to string format
- **Lines affected:** 6-14
- **New format example:** `ADMINS=("admin@example.com", "admin_and_manager@example.com")`

**File:** `tests/mail/tests.py:1780-1803`
- **Change Required:** Multiple updates
  - Lines 1782-1789: Update test data to string format
  - Line 1802: Update tuple unpacking `for address in value` (remove `_,`)
  - Lines 1862-1879: Update validation test to check for string format

**File:** `tests/logging_tests/tests.py:251, 283, 322, 344, 375, 396`
- **Change Required:** Convert all ADMINS/MANAGERS settings to string format

**File:** `tests/view_tests/tests/test_debug.py:1454, 1490, 1533`
- **Change Required:** Convert ADMINS settings to string format

**File:** `tests/middleware/tests.py:392`
- **Change Required:** Convert MANAGERS to string format

### Phase 3: Documentation Updates (Release N)

**File:** `docs/ref/settings.txt`
- **Change Required:** Update ADMINS and MANAGERS documentation
- **Details:**
  - Update format description from tuple to string list
  - Update examples: `["john@example.com", "mary@example.com"]`
  - If providing deprecation period: mention old format is deprecated
- **Section:** ADMINS and MANAGERS setting definitions

**File:** `docs/conf/global_settings.txt` (if exists)
- **Change Required:** Update comment example

**File:** `docs/howto/error-reporting.txt`
- **Change Required:** Minor - may need no changes or clarification
- **Potential update:** Clarify that email addresses are now provided as strings

**File:** `docs/topics/email.txt`
- **Change Required:** Ensure examples match new format

**File:** `docs/topics/logging.txt`
- **Change Required:** Minor - no direct format change needed

**File:** `docs/ref/logging.txt`
- **Change Required:** Minor - no direct format change needed

**File:** `docs/ref/django-admin.txt`
- **Change Required:** Minor - if examples are present, update them

### Phase 4: Remove Tuple Format Support (Release N+1 or N+2)

**File:** `django/core/mail/__init__.py:122-147`
- **Change Required:** Remove tuple format handling and deprecation warning
- **Details:** Keep only string format validation
- **Result:** Simpler, faster validation code

**File:** `django/conf/global_settings.py:34-35`
- **Change Required:** Update comment to show final format

## Implementation Notes

### Validation Logic Changes

**Current (tuple only):**
```python
if not all(isinstance(a, (list, tuple)) and len(a) == 2 for a in recipients):
    raise ValueError(f"The {setting_name} setting must be a list of 2-tuples.")
to=[a[1] for a in recipients]
```

**Target (string only):**
```python
if not all(isinstance(a, str) for a in recipients):
    raise ValueError(f"The {setting_name} setting must be a list of email strings.")
to=recipients  # Already a list of email strings
```

**Intermediate (dual format with deprecation):**
```python
emails = []
for item in recipients:
    if isinstance(item, (list, tuple)) and len(item) == 2:
        import warnings
        warnings.warn(
            f"The {setting_name} setting now expects email strings, not (name, email) tuples. "
            "Update your settings.",
            DeprecationWarning,
            stacklevel=2
        )
        emails.append(item[1])
    elif isinstance(item, str):
        emails.append(item)
    else:
        raise ValueError(f"The {setting_name} setting must be a list of email strings.")
to=emails
```

### Risk Assessment

- **Low Risk:** Core code change is localized to single function
- **Medium Risk:** Test coverage is extensive; migrations must be thorough
- **Medium Risk:** Documentation must clearly communicate change
- **High Risk:** Third-party code depending on tuple format will break (mitigated by deprecation period)

### Testing Strategy for Migration

1. Test tuple format still works with deprecation warning (Phase 1)
2. Test string format works correctly (Phase 1)
3. Test mixed formats fail or warn appropriately (Phase 1)
4. Ensure all tests pass with new string format (Phase 2)
5. Remove tuple support and verify tests still pass (Phase 4)

## Summary of Changed Files

| Component | File | Changes | Priority |
|-----------|------|---------|----------|
| Core | `django/core/mail/__init__.py` | Update `_send_server_message()` validation | **Critical** |
| Config | `django/conf/global_settings.py` | Update comment | Minor |
| Tests | `tests/mail/test_sendtestemail.py` | Convert fixtures to string format | High |
| Tests | `tests/mail/tests.py` | Update test data and assertions | High |
| Tests | `tests/logging_tests/tests.py` | Convert settings to string format | High |
| Tests | `tests/view_tests/tests/test_debug.py` | Convert settings to string format | High |
| Tests | `tests/middleware/tests.py` | Convert settings to string format | High |
| Docs | `docs/ref/settings.txt` | Update ADMINS/MANAGERS descriptions | High |
| Docs | `docs/howto/error-reporting.txt` | Clarify new format if needed | Medium |
| Docs | `docs/topics/email.txt` | Update function descriptions | Medium |
| Docs | Multiple other docs | Minor clarifications | Low |
