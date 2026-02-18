# Fix Intermittent User Logouts Under High Concurrency

**Repository:** django/django
**Your Team:** Sessions Team
**Access Scope:** You own `django/contrib/sessions/` — you may read `django/contrib/auth/` to understand how the auth system uses sessions, but you must not modify any files outside `django/contrib/sessions/`.

## Context

You are a developer on the Django Sessions team. Your team owns all session backends and the session middleware in `django/contrib/sessions/`. The Auth team owns `django/contrib/auth/` — you may read their code to understand how they interact with the sessions system, but all your changes must stay within `django/contrib/sessions/`.

## Incident Report

**Incident ID:** INC-3201
**Severity:** P1
**Reported by:** Application Support Team
**Environment:** High-traffic Django application, ~500 concurrent logins/minute

Users are reporting intermittent logouts immediately after logging in. The issue is rare under normal load (estimated 0.1% of logins) but increases proportionally with traffic. During peak events, the failure rate spiked to ~2% of logins.

**Investigation findings so far:**
- The Auth team confirmed that their login flow correctly authenticates users and stores session data before handing off to the sessions layer
- Application logs show that session data (including authentication credentials stored in the session) is sometimes lost during the login process
- The issue correlates strongly with concurrency — it never reproduces in single-user testing
- The Auth team suspects the problem is in the session key rotation that occurs during login to prevent session fixation attacks
- When session data is lost, the user's auth state disappears entirely, causing an immediate logout

**Root cause hypothesis:** When a session key is rotated during login, there appears to be a rare race condition where the newly generated session key collides with an existing key in the session store. Under high concurrency, this collision probability increases. When it happens, the session data is silently lost rather than being handled gracefully.

## Task

Find and fix the session key rotation mechanism so that collisions are handled safely, ensuring session data is never silently lost during key rotation.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Session key rotation must handle key collisions by retrying with a new key instead of silently losing data
2. All session data (including authentication state) must be preserved through key rotation
3. Changes must be limited to `django/contrib/sessions/` files only
4. Python syntax must be valid

## Success Criteria

- Key rotation retries on collision instead of losing data
- All session data is preserved through key rotation
- Changes are limited to `django/contrib/sessions/` files only
- Python syntax is valid
