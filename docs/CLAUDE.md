# Docs Directory Guide

Use this file when editing documentation or improving agent navigation.

## Documentation IA (Agent-Optimized)
- `docs/START_HERE_BY_TASK.md` - task-based routing (first stop for operations)
- `docs/ops/` - runbooks, indexes, troubleshooting, handoff templates
- `docs/reference/` - stable specs and policies (indexes/pointers first; migration can be gradual)
- `docs/technical_reports/` - versioned white papers and technical report snapshots
- `docs/explanations/` - design rationale and context
- `docs/archive/` - historical artifacts and non-canonical docs

## Authoring Rules
- Prefer short index pages that route to deeper docs.
- Add a "When To Read This" header block to new operational docs.
- Avoid duplicating script inventories in multiple docs; update the generated script index instead.
- Keep root `AGENTS.md` / `CLAUDE.md` thin; route, do not duplicate.

## Maintenance
- Regenerate agent guides and script index after structural changes.
- Run `python3 scripts/docs_consistency_check.py` after editing links or references.
