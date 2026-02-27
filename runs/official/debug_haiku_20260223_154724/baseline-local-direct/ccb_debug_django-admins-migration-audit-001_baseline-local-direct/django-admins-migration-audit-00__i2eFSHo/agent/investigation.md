# Investigation Report: Django ADMINS/MANAGERS Settings Format Migration

## Summary

Django's `ADMINS` and `MANAGERS` settings are currently defined as lists of 2-tuples in the format `[(name, email), ...]`. A migration to simple email lists `[email, ...]` requires changes to:
- One core validation function (`_send_server_message()` in `django/core/mail/__init__.py`)
- One usage check (`AdminEmailHandler.emit()` in `django/utils/log.py`)
- Five documentation files
- Six test files with fixture definitions and assertions

## Root Cause

The tuple format is unpacked in a single critical function that validates and extracts email addresses from both `ADMINS` and `MANAGERS` settings. This function serves as the central gateway for all admin/manager email notifications.

**Core Code Path**: `django/core/mail/__init__.py:_send_server_message()` (lines 122-148)
```python
def _send_server_message(...):
    recipients = getattr(settings, setting_name)  # Get ADMINS or MANAGERS
    if not recipients:
        return

    # Line 135-136: Tuple format validation
    if not all(isinstance(a, (list, tuple)) and len(a) == 2 for a in recipients):
        raise ValueError(f"The {setting_name} setting must be a list of 2-tuples.")

    # Line 142: Email extraction from tuple[1]
    to=[a[1] for a in recipients],
```

This function is called by:
- `mail_admins()` (line 150)
- `mail_managers()` (line 164)

## Evidence

### 1. Files Reading ADMINS/MANAGERS Settings

#### Production Code

| File | Line | Pattern | Impact |
|------|------|---------|--------|
| `django/core/mail/__init__.py` | 135-136 | Tuple validation: `if not all(isinstance(a, (list, tuple)) and len(a) == 2 for a in recipients)` | **CRITICAL**: Validates 2-tuple format and raises ValueError if not met |
| `django/core/mail/__init__.py` | 142 | Email extraction: `to=[a[1] for a in recipients]` | **CRITICAL**: Unpacks email from tuple index 1 |
| `django/utils/log.py` | 97 | Boolean check: `not settings.ADMINS` | Checks if ADMINS is non-empty; no format dependency |
| `django/core/management/commands/sendtestemail.py` | 43, 46 | Calls `mail_admins()` and `mail_managers()` | Indirect - calls the functions that unpack tuples |
| `django/middleware/common.py` | 129 | Calls `mail_managers()` | Indirect - calls the function that unpacks tuples |

#### Global Settings Defaults

| File | Line | Content |
|------|------|---------|
| `django/conf/global_settings.py` | 24-26 | `# [('Full Name', 'email@example.com'), (...)]` + `ADMINS = []` |
| `django/conf/global_settings.py` | 172-174 | `# Not-necessarily-technical managers...` + `MANAGERS = ADMINS` |

### 2. Test Files Using Old Format

#### tests/mail/tests.py
- **test_mail_admins_and_managers()**: Tests with `@override_settings` using tuple format `("name", "email")`
- **test_html_mail_managers()**: `@override_settings(MANAGERS=[("nobody", "nobody@example.com")])`
- **test_html_mail_admins()**: `@override_settings(ADMINS=[("nobody", "nobody@example.com")])`
- **test_manager_and_admin_mail_prefix()**: Tuple format with lazy translation strings
- **test_empty_admins()**: `ADMINS=[], MANAGERS=[]` (format agnostic but labeled with old structure)
- **test_wrong_admins_managers()**: Tests `ValueError` when format is invalid
- **test_connection_arg_mail_admins()**: `@override_settings(ADMINS=[("nobody", "nobody@example.com")])`
- **test_connection_arg_mail_managers()**: `@override_settings(MANAGERS=[("nobody", "nobody@example.com")])`

#### tests/mail/test_sendtestemail.py
- **Class-level @override_settings** (lines 6-14):
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
- **test_manager_receivers()**: Assertion on extracted emails (lines 61-75)
- **test_admin_receivers()**: Assertion on extracted emails (lines 77-91)
- **test_manager_and_admin_receivers()**: Dual assertions (lines 93-115)

#### tests/logging_tests/tests.py
- **test_emit_non_ascii()**: `@override_settings(ADMINS=[("whatever admin", "admin@example.com")])`
- **test_customize_send_mail_method()**: `@override_settings(MANAGERS=[("manager", "manager@example.com")], ...)`
- **test_custom_exception_reporter_is_used()**: `@override_settings(ADMINS=[("A.N.Admin", "admin@example.com")])`
- **test_emit_no_form_tag()**: `@override_settings(ADMINS=[("admin", "admin@example.com")])`
- **test_emit_no_admins()**: `@override_settings(ADMINS=[])`
- **test_suspicious_email_admins()**: Admin email generation tests

#### tests/middleware/tests.py
- **Class-level @override_settings** (lines 390-393):
  ```python
  @override_settings(
      IGNORABLE_404_URLS=[re.compile(r"foo")],
      MANAGERS=[("PHD", "PHB@dilbert.com")],
  )
  ```
- **test_404_error_reporting()**: Tests mail.outbox with MANAGERS (lines 405-408)
- **test_404_error_reporting_no_referer()**: Tests MANAGERS behavior (line 410)
- **test_referer_equal_to_requested_url_on_another_domain()**: (line 449)

#### tests/view_tests/tests/test_debug.py
- **verify_unsafe_email()**: `with self.settings(ADMINS=[("Admin", "admin@fattie-breakie.com")]):`
- **verify_safe_email()**: `with self.settings(ADMINS=[("Admin", "admin@fattie-breakie.com")]):`
- **verify_paranoid_email()**: `with self.settings(ADMINS=[("Admin", "admin@fattie-breakie.com")]):`

### 3. Documentation References

#### docs/ref/settings.txt
- **ADMINS** (lines 43-57): Documents format as `[("Full name, "email@example.com"), ...]`
- **MANAGERS** (lines 2066-2075): References "same format as ADMINS"

#### docs/topics/email.txt
- **mail_admins()** (lines 168-174): References `:setting:\`ADMINS\`` and tuple format implications
- **mail_managers()** (lines 190-192): References `:setting:\`MANAGERS\`` format

#### docs/topics/logging.txt
- **AdminEmailHandler** (lines 392-395): Documents behavior with site `:setting:\`ADMINS\``

#### docs/howto/error-reporting.txt
- **Error notifications** (lines 20-27): Describes using ADMINS setting for error notifications
- **Email recipients** (lines 44-45): "put the email addresses of the recipients in the :setting:\`ADMINS\` setting"
- **Broken links** (lines 64-69): Describes MANAGERS behavior for 404 errors

#### docs/ref/middleware.txt
- **BrokenLinkEmailsMiddleware**: References MANAGERS setting usage

#### docs/ref/logging.txt
- **AdminEmailHandler**: Configuration documentation referencing ADMINS

### 4. Functions Calling mail_admins() and mail_managers()

| Function | File | Line | Context |
|----------|------|------|---------|
| `mail_admins()` wrapper | `django/core/mail/__init__.py` | 150-161 | Direct entry point |
| `mail_managers()` wrapper | `django/core/mail/__init__.py` | 164-175 | Direct entry point |
| `AdminEmailHandler.send_mail()` | `django/utils/log.py` | 137-140 | Logging handler for errors |
| `BrokenLinkEmailsMiddleware.process_response()` | `django/middleware/common.py` | 129-142 | 404 error notification |
| `sendtestemail` command | `django/core/management/commands/sendtestemail.py` | 43, 46 | Admin test email utility |

## Affected Components

1. **django.core.mail**
   - Validation logic in `_send_server_message()`
   - Function signatures for `mail_admins()` and `mail_managers()`

2. **django.utils.log**
   - `AdminEmailHandler` - checks `if not settings.ADMINS`
   - Error notification pipeline

3. **django.middleware.common**
   - `BrokenLinkEmailsMiddleware` - uses `mail_managers()`

4. **Test Framework**
   - All test fixtures using `@override_settings`
   - All assertions on mail recipients

5. **Documentation**
   - Settings reference documentation
   - How-to guides on error reporting
   - Email topic guide
   - Logging documentation

## Third-Party Compatibility Concerns

**Breaking Change Impact**:

1. **User Configuration Files**
   - Existing Django projects with tuple-format ADMINS/MANAGERS will fail with `ValueError: "The ADMINS setting must be a list of 2-tuples."` if settings are not updated
   - Example breaking case:
     ```python
     # Old format (will fail after migration)
     ADMINS = [("John Doe", "john@example.com")]
     ```

2. **Custom Code**
   - Any user code that unpacks the tuple format manually will break:
     ```python
     for name, email in settings.ADMINS:  # Will fail with new format
         process_admin(email)
     ```

3. **Serialization/Deserialization**
   - Tools that generate ADMINS/MANAGERS settings (e.g., deployment automation) may encode the tuple format
   - API endpoints returning settings configuration need updates

4. **Migration Path Required**
   - A deprecation period is recommended
   - Phase 1: Accept both formats with deprecation warning
   - Phase 2: Only accept new format

## Recommendation

### Phase 1: Add Backwards Compatibility with Deprecation Warning

**File**: `django/core/mail/__init__.py` - `_send_server_message()` (lines 122-148)

Change the validation and extraction logic to:
1. Detect old tuple format
2. Issue deprecation warning if tuple format is used
3. Extract emails correctly from both formats

```python
def _send_server_message(...):
    recipients = getattr(settings, setting_name)
    if not recipients:
        return

    # Check for tuple format (old) vs string format (new)
    if recipients and isinstance(recipients[0], (list, tuple)):
        # OLD format: [("Name", "email"), ...]
        import warnings
        warnings.warn(
            f"The {setting_name} setting format is changing from "
            "[('name', 'email'), ...] to ['email', ...]. "
            "Update your ADMINS/MANAGERS settings to use the new format.",
            DeprecationWarning,
            stacklevel=3
        )
        emails = [a[1] for a in recipients]
    else:
        # NEW format: ["email", ...]
        emails = recipients

    mail = EmailMultiAlternatives(
        subject=...,
        to=emails,
        ...
    )
```

### Phase 2: Remove Old Format Support

After deprecation period (suggest 2-3 Django versions):
- Remove tuple format handling
- Simplify to: `to=recipients`

### Files Requiring Changes

#### Core Implementation
| File | Line(s) | Change Required |
|------|---------|-----------------|
| `django/core/mail/__init__.py` | 122-148 | Update `_send_server_message()` to handle both formats with deprecation warning |
| `django/core/mail/__init__.py` | 24-26 | Update comment in global_settings.py to show both formats |

#### Documentation
| File | Section | Change Required |
|------|---------|-----------------|
| `docs/ref/settings.txt` | ADMINS (43-57) | Add new format, deprecation note |
| `docs/ref/settings.txt` | MANAGERS (2066-2075) | Add new format, deprecation note |
| `docs/topics/email.txt` | mail_admins/mail_managers | Document format change |
| `docs/howto/error-reporting.txt` | All ADMINS references | Update examples |
| `docs/topics/logging.txt` | AdminEmailHandler | Document format change |
| `docs/releases/X.Y.txt` | Release notes | Deprecation warning |

#### Test Files
| File | Change Required |
|------|-----------------|
| `tests/mail/tests.py` | Add tests for new format, verify deprecation warning |
| `tests/mail/test_sendtestemail.py` | Update fixtures to new format |
| `tests/logging_tests/tests.py` | Update all ADMINS/MANAGERS fixtures |
| `tests/middleware/tests.py` | Update MANAGERS fixture |
| `tests/view_tests/tests/test_debug.py` | Update ADMINS fixtures |

#### Default Settings
| File | Line(s) | Change Required |
|------|---------|-----------------|
| `django/conf/global_settings.py` | 24-26 | Update comment to show both old (deprecated) and new format |
| `django/conf/global_settings.py` | 172-174 | Update comment for MANAGERS |

### Migration Checklist

- [ ] **Step 1: Add Backwards Compatibility**
  - [ ] Modify `django/core/mail/__init__.py` `_send_server_message()` to detect format
  - [ ] Add deprecation warning for tuple format
  - [ ] Test with both old and new formats

- [ ] **Step 2: Add New Format Tests**
  - [ ] Add test cases for string list format in `tests/mail/tests.py`
  - [ ] Verify deprecation warning is raised for old format
  - [ ] Verify new format works without warning

- [ ] **Step 3: Update Test Fixtures**
  - [ ] Convert all `@override_settings` fixtures to new format
  - [ ] Run full test suite to ensure compatibility

- [ ] **Step 4: Update Documentation**
  - [ ] Update `docs/ref/settings.txt` for both ADMINS and MANAGERS
  - [ ] Add migration guide to release notes
  - [ ] Update all example code in how-to guides
  - [ ] Add deprecation warning notice to each section

- [ ] **Step 5: Release and Monitor**
  - [ ] Release with deprecation warnings (e.g., Django 5.0)
  - [ ] Monitor deprecation warnings in user projects
  - [ ] Track issue for feedback

- [ ] **Step 6: Remove Old Format (Future Release)**
  - [ ] Remove tuple format handling from `_send_server_message()`
  - [ ] Simplify email extraction to direct list usage
  - [ ] Update all documentation
  - [ ] Note breaking change in release notes

### Risk Assessment

**High Risk Items**:
- `django/core/mail/__init__.py:_send_server_message()` - centralized code path, affects email notifications
- Test failures if fixtures not updated consistently
- Documentation not updated in sync with code changes

**Medium Risk Items**:
- Existing user projects with tuple-format settings will see deprecation warnings (expected)
- Admin deployments may fail if settings are auto-generated in old format

**Mitigation Strategies**:
1. Provide clear deprecation message with example of new format
2. Ensure documentation shows before/after examples
3. Include converter script or migration guide in release notes
4. Test with common deployment tools (Django cookiecutter, etc.)

## Summary of Code Locations

**Critical Path** (must be changed for format support):
- `django/core/mail/__init__.py:_send_server_message()` - Lines 122-148

**Usage Check** (boolean check, format-agnostic but should verify):
- `django/utils/log.py:AdminEmailHandler.emit()` - Line 97

**Documentation** (5 files):
- `docs/ref/settings.txt`
- `docs/topics/email.txt`
- `docs/topics/logging.txt`
- `docs/howto/error-reporting.txt`
- `docs/ref/middleware.txt`

**Test Fixtures** (6 test files with 20+ test methods):
- `tests/mail/tests.py` - 8 test methods
- `tests/mail/test_sendtestemail.py` - 3 test methods
- `tests/logging_tests/tests.py` - 6 test methods
- `tests/middleware/tests.py` - 3 test methods
- `tests/view_tests/tests/test_debug.py` - 3 test methods
