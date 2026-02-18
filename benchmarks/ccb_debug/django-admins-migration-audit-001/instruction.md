# Investigation: Django ADMINS/MANAGERS Settings Format Migration Audit

**Repository:** django/django
**Task Type:** Migration Audit (investigation only — no code changes)

## Scenario

Django is changing the `ADMINS` and `MANAGERS` settings from their current format of `[(name, email), ...]` tuples to simple `[email, ...]` string lists. This is tracked in ticket #36138. Before executing this migration, the team needs a comprehensive audit of all code that reads, validates, or processes these settings.

## Your Task

Produce a migration audit report at `/logs/agent/investigation.md`.

Your report MUST cover:
1. Every file that reads `settings.ADMINS` or `settings.MANAGERS`
2. Every file that validates or type-checks the settings format
3. Every file that unpacks the tuple format (e.g., `for name, email in settings.ADMINS`)
4. All documentation references that show the old tuple format
5. Test files that use the old format in fixtures or assertions
6. Third-party compatibility concerns (what breaks for users with old-format settings)
7. A migration checklist: each file that needs changes, what change is needed

## Output Requirements

Write your investigation report to `/logs/agent/investigation.md` with these sections:

```
# Investigation Report

## Summary
<1-2 sentence finding>

## Root Cause
<Core code paths that consume the tuple format>

## Evidence
<Code references with file paths and line numbers>

## Affected Components
<List of modules/packages impacted>

## Recommendation
<Migration checklist with specific files and changes needed>
```

## Constraints

- Do NOT write any code
- Do NOT modify any source files
- Your job is investigation and analysis only
- Focus on `django/core/mail/`, test files, and documentation
