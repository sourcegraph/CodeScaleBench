# Skills System

CodeScaleBench includes a set of **AI agent skill definitions** in the [`skills/`](../skills/) directory. These are structured markdown runbooks that encode operational knowledge for common benchmark workflows, enabling any AI coding agent to operate the benchmark suite reliably.

## Overview

Skills solve a practical problem: running a benchmark involves many multi-step workflows (infrastructure checks, task validation, run monitoring, failure triage, report generation) that are tedious to re-explain each session. By encoding these as structured files, any agent — Claude Code, Cursor, Copilot, or others — can follow them autonomously.

## Skill Categories

### CSB Operations (`skills/csb/`)

Project-specific skills for operating the CodeScaleBench pipeline:

| File | Skills | Purpose |
|------|--------|---------|
| `pre-run.md` | Check Infrastructure, Validate Tasks, Run Benchmark | Pre-launch readiness and execution |
| `monitoring.md` | Run Status, Watch Benchmarks | Active run monitoring |
| `triage-rerun.md` | Triage Failure, Quick Rerun | Failure investigation and fix verification |
| `analysis.md` | Compare Configs, MCP Audit, IR Analysis, Cost Report, Evaluate Traces | Post-run analysis |
| `maintenance.md` | Repo Health, Sync Metadata, Re-extract Metrics, Archive Run, Generate Report, What's Next | Data hygiene, health gate, reporting |
| `task-authoring.md` | Scaffold Task, Score Tasks, Benchmark Audit | Task creation and quality assurance |

### General Purpose (`skills/general/`)

Reusable skills applicable to any software project:

| File | Skills | Purpose |
|------|--------|---------|
| `workflow-tools.md` | Session Handoff, Strategic Compact, PRD Generator, Ralph Agent, Eval Harness | Session and workflow management |
| `agent-delegation.md` | Delegate, Codex/Cursor/Copilot/Gemini CLI Guides | Multi-agent task routing |
| `deep-search-clickhouse.md` | Deep Search CLI, ClickHouse Patterns | Semantic search and analytics |
| `dev-practices.md` | Security Review, Coding Standards, TDD, Verification Loop, Frontend/Backend Patterns | Development best practices |

## Integration

### Cursor

Skills originated as `.cursor/rules/*.mdc` files. To use them with Cursor, copy into `.cursor/rules/` and add YAML front-matter with `description` and optional `globs` fields. See [`skills/README.md`](../skills/README.md) for details.

### Claude Code

Reference skill files from `CLAUDE.md` or `AGENTS.md`. The agent reads referenced files on demand.

### Other Agents

Skills are plain markdown — any file-reading agent can use them directly.

## Creating New Skills

See the [Adapting for Your Own Project](../skills/README.md#adapting-for-your-own-project) section in the skills README for guidance on writing skills for your own workflows.

## Related Documentation

- [`skills/README.md`](../skills/README.md) — Full skill index and usage guide
- [`CLAUDE.md`](../CLAUDE.md) / [`AGENTS.md`](../AGENTS.md) — Operational quick-reference (references skills)
- [`docs/QA_PROCESS.md`](QA_PROCESS.md) — Quality assurance pipeline (skills automate parts of this)
- [`docs/ERROR_CATALOG.md`](ERROR_CATALOG.md) — Known error patterns (used by triage skill)
