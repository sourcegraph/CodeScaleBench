# Investigation Report: Django ADMINS/MANAGERS Settings Format Migration Audit

## Summary

Django is transitioning the `ADMINS` and `MANAGERS` settings from a tuple-based format `[(name, email), ...]` to a simple email string list `[email, ...]`. This audit identifies all code paths that consume, validate, or depend on these settings, revealing the scope of the migration and what must be updated in Django 7.0 when the old format support is removed.

**Key Finding:** The migration is already partially implemented in Django 6.0 with deprecation warnings. The code provides backwards compatibility via a conversion layer in `_send_server_message()` that transforms old tuples to strings. For Django 7.0, this conversion must be removed, and all deprecated tuple-based examples and tests must be eliminated.

## Root Cause

The core format conversion and validation happens in a single function: `_send_server_message()` in `django/core/mail/__init__.py` (lines 127-166). This function:

1. **Detects old format** (lines 141-148): Uses `all(isinstance(a, (list, tuple)) and len(a) == 2 for a in recipients)` to identify tuples
2. **Warns and converts** (lines 142-148): Emits `RemovedInDjango70Warning` and extracts email addresses: `recipients = [a[1] for a in recipients]`
3. **Validates new format** (lines 150-155): Enforces that all recipients are strings or Promise objects, raising `ImproperlyConfigured` if validation fails

This function is called by:
- `mail_admins()` (line 169-180)
- `mail_managers()` (line 183-194)

Both of these public API functions delegate to `_send_server_message()` with the appropriate `setting_name` parameter.

## Evidence

### 1. Core Implementation Files

#### **django/core/mail/__init__.py** (Lines 127-194)
- **`_send_server_message()`**: Central function handling format detection, conversion, and validation
  - Line 141-148: Tuple detection and deprecation warning with `RemovedInDjango70Warning`
  - Line 148: Tuple conversion extracting `a[1]` (email from `(name, email)`)
  - Line 150-155: New format validation requiring list/tuple of strings
- **`mail_admins()`**: Public function that calls `_send_server_message()` with `setting_name="ADMINS"`
- **`mail_managers()`**: Public function that calls `_send_server_message()` with `setting_name="MANAGERS"`

#### **django/conf/global_settings.py** (Line 25-26, 174)
- **Line 25**: Outdated comment: `# [('Full Name', 'email@example.com'), ('Full Name', 'anotheremail@example.com')]`
  - **Action needed**: Update comment to show new format
- **Line 26**: `ADMINS = []` (already using new format)
- **Line 174**: `MANAGERS = ADMINS` (references ADMINS by assignment)

### 2. Email/Messaging Integration

#### **django/core/management/commands/sendtestemail.py** (Lines 1-47)
- **Line 24**: Help text mentions `settings.MANAGERS`
- **Line 29**: Help text mentions `settings.ADMINS`
- **Lines 42-46**: Calls `mail_managers()` and `mail_admins()` functions
- **Action needed**: No code changes required (uses public API that handles conversion)

#### **django/utils/log.py** (Lines 79-150)
- **Class `AdminEmailHandler`**: Logging handler that sends errors to admins
  - **Line 97**: Checks `if not settings.ADMINS` to decide if email should be sent
  - **Line 138-139**: Calls `mail.mail_admins()` from within `send_mail()` method
- **Line 13-14**: DEFAULT_LOGGING configuration references `AdminEmailHandler` in handler definition
- **Action needed**: No changes required (uses public API)

### 3. Test Files Using Old Tuple Format

#### **tests/mail/tests.py** (Lines 1782-1913)
- **Line 1782-1806: `test_mail_admins_and_managers()`**
  - Tests new string format (correct):
    - Line 1785: `['\"Name, Full\" <test@example.com>']`
    - Line 1787-1788: `["test@example.com", "other@example.com"]`
    - Line 1790: Lazy strings
  - **Status**: Already updated for new format

- **Lines 1864-1888: `test_deprecated_admins_managers_tuples()` (RemovedInDjango70Warning)**
  - Tests the deprecated tuple format with expectation of warning
  - Line 1867: `[(\"nobody\", \"nobody@example.com\"), (\"other\", \"other@example.com\")]`
  - Line 1868: Alternative format: `[[\"nobody\", \"nobody@example.com\"], [\"other\", \"other@example.com\"]]`
  - Line 1884: Asserts `RemovedInDjango70Warning` is raised
  - **Action needed (Django 7.0)**: This test must be deleted entirely when old format support is removed

- **Lines 1890-1913: `test_wrong_admins_managers()`**
  - Tests invalid format handling
  - Lines 1894-1897: Commented-out section showing old tuples that would be valid in old code
  - Comment says: "RemovedInDjango70Warning: uncomment these cases when support for deprecated (name, address) tuples is removed."
  - Line 1898-1900: Tests invalid formats that should fail
  - **Action needed (Django 7.0)**: Uncomment lines 1894-1897 after removing old format support

#### **tests/mail/test_sendtestemail.py** (Lines 1-110)
- **Lines 6-9**: `@override_settings` using new string format (correct):
  - `ADMINS=[\"admin@example.com\", \"admin_and_manager@example.com\"]`
  - `MANAGERS=[\"manager@example.com\", \"admin_and_manager@example.com\"]`
- **Status**: Already updated, no changes needed

#### **tests/logging_tests/tests.py**
- **Line 474**: `@override_settings(ADMINS=[])`
- **Status**: Already using new format (empty list), no changes needed

### 4. Documentation References

#### **docs/ref/settings.txt** (Lines 42-62, 2070-2083)

**ADMINS Setting Documentation (Lines 42-62)**:
```
ADMINS
------

Default: [] (Empty list)

A list of all the people who get code error notifications...

Each item in the list should be an email address string. Example::

    ADMINS = ["john@example.com", '"Ng, Mary" <mary@example.com>']

.. versionchanged:: 6.0

    In older versions, required a list of (name, address) tuples.
```
- **Line 57**: Example shows new string format (correct)
- **Lines 59-61**: `versionchanged:: 6.0` directive explaining old tuple format
- **Action needed (Django 7.0)**: Remove the `versionchanged:: 6.0` block (old news), keep string example

**MANAGERS Setting Documentation (Lines 2070-2083)**:
```
MANAGERS
--------

Default: [] (Empty list)

A list in the same format as :setting:`ADMINS` that specifies...

.. versionchanged:: 6.0

    In older versions, required a list of (name, address) tuples.
```
- **Lines 2081-2083**: `versionchanged:: 6.0` directive explaining old format
- **Action needed (Django 7.0)**: Remove the `versionchanged:: 6.0` block

#### **docs/releases/6.0.txt** (Lines 329-334)

**Deprecation Notice**:
```
* Setting :setting:`ADMINS` or :setting:`MANAGERS` to a list of (name, address)
  tuples is deprecated. Set to a list of email address strings instead. Django
  never used the name portion. To include a name, format the address string as
  ``'\"Name\" <address>'`` or use Python's :func:`email.utils.formataddr`.
```
- **Status**: This is the deprecation notice for Django 6.0
- **Action needed (Django 7.0)**: Move this to "Features removed in 7.0" section and update wording to past tense

#### **docs/topics/email.txt** (Lines 164-193)

**`mail_admins()` Documentation**:
```
mail_admins()
=============

.. function:: mail_admins(subject, message, fail_silently=False, connection=None, html_message=None)

``django.core.mail.mail_admins()`` is a shortcut for sending an email to the
site admins, as defined in the :setting:`ADMINS` setting.
```
- **Status**: Function documentation is generic and doesn't specify format
- **Action needed**: No changes required

**`mail_managers()` Documentation**:
```
mail_managers()
===============

.. function:: mail_managers(subject, message, fail_silently=False, connection=None, html_message=None)

``django.core.mail.mail_managers()`` is just like ``mail_admins()``, except it
sends an email to the site managers, as defined in the :setting:`MANAGERS`
setting.
```
- **Status**: Function documentation is generic
- **Action needed**: No changes required

#### **docs/topics/logging.txt** (Lines 41-50, 332-340)

- References `AdminEmailHandler` and mentions it emails `:setting:`ADMINS`
- **Status**: Documentation is generic, references the public API
- **Action needed**: No changes required

#### **docs/howto/deployment/checklist.txt** (Lines 250-258)

**ADMINS and MANAGERS Section**:
```
:setting:`ADMINS` and :setting:`MANAGERS`
-----------------------------------------

:setting:`ADMINS` will be notified of 500 errors by email.

:setting:`MANAGERS` will be notified of 404 errors.
:setting:`IGNORABLE_404_URLS` can help filter out spurious reports.
```
- **Status**: Documentation doesn't specify format
- **Action needed**: No changes required

#### **docs/howto/error-reporting.txt**

- References `ADMINS` setting in context of error email handlers
- **Status**: Generic documentation, no format specified
- **Action needed**: No changes required

### 5. Public API Functions (No Breaking Changes Needed)

#### **django/core/mail/__init__.py** - `mail_admins()` and `mail_managers()`
- These are public API functions that already handle both old and new formats
- **Status**: The deprecation warning is built-in
- **Action needed (Django 7.0)**: Remove the tuple detection code (lines 141-148) since old format won't be supported

### 6. Third-Party Compatibility Concerns

**Breaking Changes in Django 7.0**:

1. **Direct Settings Access**: Code that reads `settings.ADMINS` or `settings.MANAGERS` directly expecting tuples will fail
   ```python
   # OLD CODE (WILL BREAK):
   for name, email in settings.ADMINS:  # Will fail - strings can't unpack to 2 values
       notify_admin(name, email)

   # NEW CODE (REQUIRED):
   for email_address in settings.ADMINS:
       # Parse if name needed using email.utils.parseaddr()
   ```

2. **No Migration Path Within Django**: Django's `_send_server_message()` removes the conversion layer
   - Users must update their own code that depends on tuple format
   - No deprecation warnings will be issued in 7.0 (only in 6.x)

3. **Email Address Parsing**: Code that needs to extract names will need to use `email.utils.parseaddr()`
   ```python
   from email.utils import parseaddr

   name, email_address = parseaddr(admin_email)
   ```

4. **Admin Interface**: Custom admin classes that interact with `ADMINS` settings
   - Any subclass of `AdminEmailHandler` that overrides `send_mail()` will continue working
   - But if code accesses `settings.ADMINS` directly, it will break

## Affected Components

### Core Modules
1. **django.core.mail** - Central processing of ADMINS/MANAGERS
2. **django.utils.log** - AdminEmailHandler uses ADMINS
3. **django.core.management.commands.sendtestemail** - Indirect usage via mail_admins/mail_managers

### Test Modules
1. **tests.mail.tests** - Contains deprecated tuple format tests
2. **tests.mail.test_sendtestemail** - Already migrated to new format
3. **tests.logging_tests** - Uses AdminEmailHandler

### Documentation
1. **docs/ref/settings.txt** - ADMINS and MANAGERS settings reference
2. **docs/releases/6.0.txt** - Contains deprecation notice
3. **docs/topics/email.txt** - mail_admins() and mail_managers() documentation
4. **docs/topics/logging.txt** - AdminEmailHandler documentation
5. **docs/howto/deployment/checklist.txt** - Deployment configuration guidance
6. **docs/howto/error-reporting.txt** - Error reporting configuration

### Configuration Files
1. **django/conf/global_settings.py** - Default ADMINS/MANAGERS settings with outdated comments

## Recommendation

### Migration Checklist for Django 7.0

#### Code Changes (Removal Phase)

**Priority 1: Remove Backwards Compatibility**
- [ ] **django/core/mail/__init__.py**
  - Line 140-148: Delete the tuple detection and deprecation warning block
  - Line 150-155: Keep format validation (now only for strings)
  - Simplify `_send_server_message()` to expect recipients are already strings

**Priority 2: Remove Deprecated Tests**
- [ ] **tests/mail/tests.py**
  - Line 1864-1888: Delete `test_deprecated_admins_managers_tuples()` entirely
  - Lines 1894-1897: Uncomment the three tuple format test cases in `test_wrong_admins_managers()`
  - Verify tests now expect `ImproperlyConfigured` for all tuple formats

**Priority 3: Update Documentation and Comments**
- [ ] **django/conf/global_settings.py**
  - Line 25: Update comment from old tuple format to new string format
  - Example: Change to `# ["john@example.com", '"Full Name" <admin@example.com>']`

- [ ] **docs/ref/settings.txt**
  - Lines 59-61: Remove the `.. versionchanged:: 6.0` block for ADMINS
  - Lines 2081-2083: Remove the `.. versionchanged:: 6.0` block for MANAGERS

- [ ] **docs/releases/6.0.txt**
  - Lines 331-334: Move deprecation notice to a new "Features removed in 7.0" section
  - Reword to past tense: "Setting... to a list of (name, address) tuples was deprecated in 6.0 and has been removed."

#### Testing Strategy

1. **Run existing tests** to ensure new format works correctly:
   - `tests/mail/tests.py::MailTests::test_mail_admins_and_managers`
   - `tests/mail/test_sendtestemail.py`
   - `tests/logging_tests/tests.py::AdminEmailHandlerTest`

2. **Verify tuple rejection**:
   - All tuple formats should raise `ImproperlyConfigured` without warnings
   - No `RemovedInDjango70Warning` should be emitted

3. **Check AdminEmailHandler integration**:
   - Logging tests with `@override_settings(ADMINS=[...])` should still pass
   - Handler should gracefully skip email if ADMINS is empty

#### Code Review Checklist

- [ ] No references to old tuple format remain in production code
- [ ] Deprecation warning code completely removed
- [ ] All test assertions updated to expect `ImproperlyConfigured` for tuples
- [ ] Documentation examples reflect only string format
- [ ] Release notes updated with removal notice
- [ ] No backwards compatibility shims left behind

### Post-Migration Validation

1. **Search codebase for residual tuple handling**:
   ```bash
   grep -r "for.*,.*in.*ADMINS" django/
   grep -r "for.*,.*in.*MANAGERS" django/
   ```

2. **Verify tuple format is rejected everywhere**:
   - Test with `ADMINS = [("Name", "email@example.com")]`
   - Confirm `ImproperlyConfigured` is raised
   - Confirm NO `RemovedInDjango70Warning` is raised

3. **Validate email parsing still works**:
   - Test with `ADMINS = ['"Full Name" <email@example.com>']`
   - Confirm emails are sent correctly
   - Confirm name is preserved in email "From" header if desired

## Summary of Migration Impact

| File/Component | Change Type | Scope | Priority |
|---|---|---|---|
| django/core/mail/__init__.py | Code removal | Remove tuple conversion logic (8 lines) | P1 |
| tests/mail/tests.py | Test removal | Delete deprecated test, uncomment cases | P1 |
| django/conf/global_settings.py | Documentation | Update comment example | P2 |
| docs/ref/settings.txt | Documentation | Remove versionchanged blocks | P2 |
| docs/releases/6.0.txt | Documentation | Move to removal section | P2 |

**Estimated Impact**: ~40-50 lines of code/comments to remove or update across 5 files. This is a straightforward removal of deprecated functionality with minimal risk since Django 6.0 already provides the deprecation pathway.
