# Investigation Report: Django ADMINS/MANAGERS Settings Format Migration

## Summary

Django is transitioning the `ADMINS` and `MANAGERS` settings from tuple format `[(name, email), ...]` to string list format `[email, ...]`. The deprecation is already in place (Django 6.0), with removal planned for Django 7.0. A comprehensive code audit reveals 4 core modules, 6 test files, and multiple documentation files require attention to complete the migration.

## Root Cause

The current implementation in `_send_server_message()` (django/core/mail/__init__.py:127-166) contains backward-compatibility code that:
1. Checks if all items are (name, email) tuples (lines 141-148)
2. Issues a `RemovedInDjango70Warning` deprecation warning
3. Extracts just the email address (`a[1]` from tuples)
4. Validates that recipients are email strings (lines 150-155)

This deprecation handling code must be removed when the migration is complete, along with all code paths that support the tuple format.

## Evidence

### Core Implementation Files

#### 1. **django/core/mail/__init__.py** (CRITICAL)
- **Lines 127-166**: `_send_server_message()` function
  - Lines 141-148: Tuple format detection and deprecation warning
  - Lines 150-155: String format validation
  - This is the ONLY place where the tuple format is actually handled
  - Remove tuple handling (lines 141-148) for full migration

#### 2. **django/utils/log.py** (INDIRECT)
- **Line 97**: `AdminEmailHandler.emit()` checks `if not settings.ADMINS`
- **Line 138**: `AdminEmailHandler.send_mail()` calls `mail.mail_admins()` which delegates to `_send_server_message()`
- No direct tuple processing; relies on mail module's handling
- No changes needed here if core mail module is updated

#### 3. **django/middleware/common.py** (INDIRECT)
- **Line 129-140**: `BrokenLinkEmailsMiddleware.process_response()` calls `mail_managers()`
- Delegates to `mail_managers()` which calls `_send_server_message()`
- No direct tuple processing; relies on mail module's handling
- No changes needed here

#### 4. **django/core/management/commands/sendtestemail.py** (INDIRECT)
- **Line 3**: Imports `mail_admins, mail_managers`
- **Lines 45-46**: Calls `mail_admins()` and `mail_managers()`
- Delegates to mail module functions
- No direct tuple processing; no changes needed

### Settings Definition

#### 5. **django/conf/global_settings.py**
- **Line 24-25**: Comment shows old tuple format
  ```python
  # [('Full Name', 'email@example.com'), ('Full Name', 'anotheremail@example.com')]
  ADMINS = []
  ```
  - ACTION: Update comment to show new string format
  - **Line 174**: `MANAGERS = ADMINS` (set by reference)
  - No code change needed, just documentation update

### Test Files

#### 6. **tests/mail/tests.py** (CRITICAL)
- **Lines 1782-1805**: `test_mail_admins_and_managers()`
  - Tests new string format: email strings, tuples of strings, lazy strings
  - KEEP: This test validates the new format and should pass

- **Lines 1864-1888**: `test_deprecated_admins_managers_tuples()`
  - Tests old tuple format with deprecation warning
  - ACTION: REMOVE this entire test when tuple support is removed (7.0)
  - Currently checks for `RemovedInDjango70Warning`

- **Lines 1890-1900**: `test_wrong_admins_managers()`
  - Lines 1894-1897: COMMENTED section showing cases to uncomment after tuple removal
  - ACTION: Uncomment the tuple test cases that are currently commented:
    ```python
    # RemovedInDjango70Warning: uncomment these cases when support for
    # deprecated (name, address) tuples is removed.
    #    [(\"nobody\", \"nobody@example.com\"), (\"other\", \"other@example.com\")],
    #    [[\"nobody\", \"nobody@example.com\"], [\"other\", \"other@example.com\"]],
    ```
  - These should be moved from `test_deprecated_admins_managers_tuples()` or modified to expect `ImproperlyConfigured` error instead of deprecation warning

- **Lines 1853-1862**: `test_empty_admins()`
  - Tests empty ADMINS/MANAGERS lists
  - KEEP: No changes needed, works for both formats

- **Lines 1807-1835**: `test_html_mail_admins()` and `test_html_mail_managers()`
  - Use new string format in decorators
  - KEEP: No changes needed

- **Lines 1837-1850**: `test_manager_and_admin_mail_prefix()`
  - Uses new string format
  - KEEP: No changes needed

#### 7. **tests/mail/test_sendtestemail.py** (MINOR)
- **Lines 6-14**: Uses new string format in `@override_settings`
  ```python
  @override_settings(
      ADMINS=[\"admin@example.com\", \"admin_and_manager@example.com\"],
      MANAGERS=[\"manager@example.com\", \"admin_and_manager@example.com\"],
  )
  ```
- KEEP: Already using new format, no changes needed

#### 8. **tests/logging_tests/tests.py** (MINOR)
- **Line 452**: `@override_settings(ADMINS=[\"admin@example.com\"])`
- **Line 474-475**: `@override_settings(ADMINS=[])`
- Already using new string format
- KEEP: No changes needed

#### 9. **tests/middleware/tests.py** (MINOR)
- **Line 392**: `MANAGERS=[\"manager@example.com\"]`
- Already using new string format
- KEEP: No changes needed

### Documentation Files

#### 10. **docs/ref/settings.txt** (DOCUMENTATION)
- **Lines 43-61**: ADMINS setting documentation
  ```rst
  Each item in the list should be an email address string. Example::

      ADMINS = [\"john@example.com\", '\"Ng, Mary\" <mary@example.com>']

  .. versionchanged:: 6.0

      In older versions, required a list of (name, address) tuples.
  ```
  - ACTION: When tuple support is removed (7.0), remove the `versionchanged` note about 6.0

- **Lines 2077-2080**: MANAGERS setting documentation
  ```rst
  A list in the same format as :setting:`ADMINS` that specifies who should get
  broken link notifications when
  :class:`~django.middleware.common.BrokenLinkEmailsMiddleware` is enabled.
  ```
  - KEEP: References ADMINS format, will be correct after ADMINS is updated

#### 11. **docs/releases/6.0.txt** (RELEASE NOTES)
- **Lines 331-334**: Deprecation notice
  ```
  * Setting :setting:`ADMINS` or :setting:`MANAGERS` to a list of (name, address)
    tuples is deprecated. Set to a list of email address strings instead. Django
    never used the name portion. To include a name, format the address string as
    ``'\"Name\" <address>'`` or use Python's :func:`email.utils.formataddr`.
  ```
  - KEEP: Historical release notes should not be modified

#### 12. **docs/internals/deprecation.txt** (DEPRECATION GUIDE)
- **Lines 31-32**: Future removal note
  ```
  * Support for setting the ``ADMINS`` or ``MANAGERS`` settings to a list of
    (name, address) tuples will be removed.
  ```
  - ACTION: When removing tuple support, move this to "7.0" section and mark as completed
  - Create entry noting the removal in the 7.0 release notes

#### 13. **docs/howto/error-reporting.txt** (DOCUMENTATION)
- **Lines 44-46**: References to ADMINS setting for error emails
- **Lines 56-71**: Discussion of 404 error reporting to MANAGERS
- No format examples shown; no changes needed

#### 14. **docs/topics/email.txt** (DOCUMENTATION)
- **Lines 166-183**: `mail_admins()` function documentation
- **Lines 187-193**: `mail_managers()` function documentation
- No format examples shown; no changes needed

#### 15. **docs/topics/logging.txt** (DOCUMENTATION)
- **Line 394**: Mentions "emails any `ERROR` (or higher) message to the site :setting:`ADMINS`"
- No format examples shown; no changes needed

### Validation and Error Handling

The new validation in `_send_server_message()` (lines 150-155) will properly reject invalid formats:
```python
if not isinstance(recipients, (list, tuple)) or not all(
    isinstance(address, (str, Promise)) for address in recipients
):
    raise ImproperlyConfigured(
        f\"The {setting_name} setting must be a list of email address strings.\"
    )
```

This validation will automatically catch user errors after tuple support is removed.

## Affected Components

1. **django.core.mail** - Core email sending module (PRIMARY)
2. **django.utils.log** - Logging error handler (INDIRECT)
3. **django.middleware.common** - Broken link notifications middleware (INDIRECT)
4. **django.core.management.commands** - Test email command (INDIRECT)
5. **Test Suite** - 6 test modules with deprecation and format tests
6. **Documentation** - Settings reference and release notes

## Recommendation: Migration Checklist

### Phase 1: Code Changes (For Django 7.0)

#### Must Remove/Change:
- [ ] **django/core/mail/__init__.py** (lines 141-148)
  - Remove tuple format detection and deprecation warning code
  - Keep string validation (lines 150-155)
  - Updated function will only accept email strings

- [ ] **django/conf/global_settings.py** (line 24-25)
  - Change comment from old tuple format to new string format:
    ```python
    # ['email1@example.com', 'email2@example.com']
    ADMINS = []
    ```

- [ ] **tests/mail/tests.py**
  - Remove `test_deprecated_admins_managers_tuples()` (lines 1864-1888)
  - Uncomment and modify test cases in `test_wrong_admins_managers()` (lines 1894-1897)
  - These uncommented cases should now expect `ImproperlyConfigured` error instead of deprecation warning

#### No Changes Needed:
- [ ] django/utils/log.py - Indirectly uses mail module; no direct tuple processing
- [ ] django/middleware/common.py - Indirectly uses mail module; no direct tuple processing
- [ ] django/core/management/commands/sendtestemail.py - Delegates to mail module
- [ ] tests/mail/test_sendtestemail.py - Already uses new format
- [ ] tests/logging_tests/tests.py - Already uses new format
- [ ] tests/middleware/tests.py - Already uses new format

#### Documentation Updates:
- [ ] **docs/ref/settings.txt** (ADMINS section)
  - Remove the `.. versionchanged:: 6.0` note mentioning old tuple format
  - Keep current example showing new string format

- [ ] **docs/releases/6.0.txt**
  - Keep as-is (historical release notes)

- [ ] **docs/internals/deprecation.txt**
  - Move the tuple removal note from current location to completed removals section for 7.0
  - Add to Django 7.0 release notes

#### Validation:
- [ ] Run `tests/mail/tests.py` to ensure all tests pass
- [ ] Run full test suite to verify no regressions
- [ ] Verify that old tuple format raises `ImproperlyConfigured` error

### Phase 2: User Migration Path

Users with old-format settings will need to be aware of:

1. **Warning Period (6.0-6.x)**: Code works but shows deprecation warning
   - Users see: `RemovedInDjango70Warning: Using (name, address) pairs in the ADMINS setting is deprecated...`
   - Action: Convert to new format `['email@example.com']` or `['"Name" <email@example.com>']`

2. **Removal (7.0+)**: Old format raises `ImproperlyConfigured` error
   - Error message: `The ADMINS setting must be a list of email address strings.`
   - Users forced to update their settings

### Third-Party Compatibility Notes

Applications and packages that read `settings.ADMINS` or `settings.MANAGERS`:
- Will need to update if they unpack tuples: `for name, email in settings.ADMINS:`
- Can be fixed to use new format: `for email in settings.ADMINS:`
- Or use Python's `email.utils.formataddr()` to parse names from strings if needed

The deprecation warning in 6.0 will help identify affected third-party code early.

## Key Migration Details

### Format Changes:

**Old Format (Deprecated in 6.0, Remove in 7.0):**
```python
ADMINS = [
    ('John Doe', 'john@example.com'),
    ('Jane Smith', 'jane@example.com'),
]
```

**New Format (Required from 7.0):**
```python
ADMINS = [
    'john@example.com',
    'jane@example.com',
    # Or with display names (RFC 5322 format):
    '\"John Doe\" <john@example.com>',
    '\"Jane Smith\" <jane@example.com>',
]
```

### Validation After Migration:

The `_send_server_message()` function will validate:
1. `recipients` must be a list or tuple
2. Each item must be a string or Promise (lazy string)
3. No tuple unpacking occurs
4. `ImproperlyConfigured` raised for invalid formats

### Impact Summary

| Component | Impact | Action Required |
|-----------|--------|-----------------|
| django/core/mail/__init__.py | CRITICAL | Remove tuple handling code |
| django/conf/global_settings.py | MINOR | Update example comment |
| tests/mail/tests.py | CRITICAL | Remove deprecation test, update error tests |
| Other modules | NONE | No code changes needed |
| Documentation | MINOR | Remove version-changed notes |

