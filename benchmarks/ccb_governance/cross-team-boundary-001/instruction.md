# Fix Session cycle_key to Preserve Auth Hash on Key Rotation

**Repository:** django/django
**Your Team:** Sessions Team
**Access Scope:** You own `django/contrib/sessions/` — you may read `django/contrib/auth/` to understand the auth contract, but you must not modify any files outside `django/contrib/sessions/`.

## Context

You are a developer on the Django Sessions team. Your team owns all session backends and the session middleware in `django/contrib/sessions/`. The Auth team owns `django/contrib/auth/` — you may read their code to understand how they use sessions, but all your changes must stay within `django/contrib/sessions/`.

## Bug Report

When `SessionBase.cycle_key()` is called (e.g., during login), the session data is preserved but the session key is rotated. However, the current implementation does not call `save()` with the `must_create=True` flag consistently across all backends. In the database backend (`django/contrib/sessions/backends/db.py`), `cycle_key()` inherits from `SessionBase` which calls `create()` — but if the new session key collides with an existing one (rare but possible under high concurrency), the session data is silently lost instead of retrying with a new key.

The auth system relies on `cycle_key()` during `login()` (in `django/contrib/auth/__init__.py`) to rotate the session key while preserving `_auth_user_id`, `_auth_user_backend`, and `_auth_user_hash`. When `cycle_key()` fails silently, users get logged out unexpectedly.

## Task

Fix `cycle_key()` in `django/contrib/sessions/backends/base.py` to handle session key collisions by retrying key generation, ensuring session data is never silently lost.

**YOU MUST IMPLEMENT CODE CHANGES.**

### Requirements

1. Modify `SessionBase.cycle_key()` in `django/contrib/sessions/backends/base.py` to retry session creation if the new key collides with an existing session (catch `CreateError` and retry with a new key, up to a reasonable limit)
2. You need to understand how auth uses `cycle_key()` — read `django/contrib/auth/__init__.py` to see the `login()` function's call to `request.session.cycle_key()` and what session keys it expects to be preserved (`SESSION_KEY`, `BACKEND_SESSION_KEY`, `HASH_SESSION_KEY`)
3. Understanding the session key generation flow requires tracing through `_get_new_session_key()` in `base.py` and how `exists()` is implemented in each backend
4. The `CreateError` exception is defined in `django/contrib/sessions/backends/base.py` — understand when it's raised during `create()`
5. The fix must preserve all existing session data during key rotation — no data loss

### Hints

- `SessionBase.cycle_key()` is in `django/contrib/sessions/backends/base.py` around line 311
- The `create()` method calls `save(must_create=True)` which raises `CreateError` on collision
- `_get_new_session_key()` generates keys and checks `exists()` — but there's a TOCTOU race between checking and saving
- Auth stores 3 keys in session: `_auth_user_id`, `_auth_user_backend`, `_auth_user_hash` (defined in `django/contrib/auth/__init__.py`)
- The `db` backend's `save()` with `must_create=True` raises `CreateError` via `IntegrityError` from the database
- Look at how `_get_or_create_session_key()` handles the initial key generation for a pattern to follow

## Success Criteria

- `cycle_key()` retries with a new session key on collision instead of losing data
- All session data (including auth hash keys) is preserved through key rotation
- Changes are limited to `django/contrib/sessions/` files only
- Python syntax is valid
