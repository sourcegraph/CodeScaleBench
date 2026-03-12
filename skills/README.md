# AI Agent Skills for CodeScaleBench

This directory contains reusable **skill definitions** for AI coding agents (Claude Code, Cursor, Copilot, etc.) that operate on this repository. Skills are structured instructions that tell an AI agent *how* to perform specific operational tasks — think of them as runbooks that an agent can follow autonomously.

Only **project-specific** (CSB) skills are kept here. General-purpose skills
(coding standards, security review, TDD, agent delegation, etc.) live in
`~/.claude/skills/` and in `.cursor/rules/` as separate `.mdc` files.

## Why Skills?

Running a benchmark suite like CodeScaleBench involves many repetitive multi-step workflows: validating tasks, launching runs, triaging failures, comparing configs, generating reports. Rather than re-explaining these workflows each session, skills encode the operational knowledge once and let any AI agent execute them reliably.

Skills are particularly valuable for:
- **Onboarding** — New operators (human or AI) can immediately operate the benchmark
- **Consistency** — The same procedure runs the same way every time
- **Composability** — Skills can be chained (e.g., check-infra → validate-tasks → run-benchmark)
- **Tool-agnostic** — Works with any agent that reads markdown instructions

## Directory Structure

```
skills/
├── README.md                  ← You are here
├── csb/                       ← Consolidated CSB skill guides (grouped by phase)
│   ├── pre-run.md             ← Infrastructure checks, task validation, launching runs
│   ├── monitoring.md          ← Run status, watching benchmark progress
│   ├── triage-rerun.md        ← Failure investigation, quick reruns to verify fixes
│   ├── analysis.md            ← Config comparison, MCP audit, IR metrics, cost reports
│   ├── maintenance.md         ← Metadata sync, metric re-extraction, archiving, reports
│   └── task-authoring.md      ← Scaffolding new tasks, quality scoring, ABC audits
│
├── archive-run/SKILL.md       ← Individual skill runbooks (one per skill)
├── benchmark-audit/SKILL.md
├── check-infra/SKILL.md
├── compare-configs/SKILL.md
├── cost-report/SKILL.md
├── evaluate-traces/SKILL.md
├── generate-report/SKILL.md
├── ir-analysis/SKILL.md
├── mcp-audit/SKILL.md
├── quick-rerun/SKILL.md
├── reextract-metrics/SKILL.md
├── repo-health/SKILL.md
├── run-benchmark/SKILL.md
├── run-status/SKILL.md
├── scaffold-task/SKILL.md
├── score-tasks/SKILL.md
├── sync-metadata/SKILL.md
├── triage-failure/SKILL.md
├── validate-tasks/SKILL.md
├── watch-benchmarks/SKILL.md
└── whats-next/SKILL.md
```

## Skill Index

### Individual Skills (per-directory `SKILL.md`)

| Skill | Directory | When to Use |
|-------|-----------|-------------|
| Archive Run | [archive-run](archive-run/SKILL.md) | Clean up old completed runs to save disk |
| Benchmark Audit | [benchmark-audit](benchmark-audit/SKILL.md) | ABC framework compliance audit |
| Check Infrastructure | [check-infra](check-infra/SKILL.md) | Before any benchmark run |
| Compare Configs | [compare-configs](compare-configs/SKILL.md) | Finding signal between baseline and MCP configs |
| Cost Report | [cost-report](cost-report/SKILL.md) | Token usage and cost breakdown |
| Evaluate Traces | [evaluate-traces](evaluate-traces/SKILL.md) | Comprehensive trace audit |
| Generate Report | [generate-report](generate-report/SKILL.md) | Producing evaluation reports |
| IR Analysis | [ir-analysis](ir-analysis/SKILL.md) | Measuring file retrieval quality |
| MCP Audit | [mcp-audit](mcp-audit/SKILL.md) | Analyzing MCP tool usage patterns |
| Quick Rerun | [quick-rerun](quick-rerun/SKILL.md) | Verifying a fix on a single task |
| Re-extract Metrics | [reextract-metrics](reextract-metrics/SKILL.md) | After extraction bug fixes |
| Repo Health | [repo-health](repo-health/SKILL.md) | Before syncing changes — reduce drift and keep repository checks green |
| Run Benchmark | [run-benchmark](run-benchmark/SKILL.md) | Launching paired or gap-fill benchmark runs |
| Run Status | [run-status](run-status/SKILL.md) | Quick check on active runs |
| Scaffold Task | [scaffold-task](scaffold-task/SKILL.md) | Creating new benchmark tasks |
| Score Tasks | [score-tasks](score-tasks/SKILL.md) | Quality-scoring task definitions |
| Sync Metadata | [sync-metadata](sync-metadata/SKILL.md) | Keeping task.toml in sync with registry |
| Triage Failure | [triage-failure](triage-failure/SKILL.md) | Investigating why a task failed |
| Validate Tasks | [validate-tasks](validate-tasks/SKILL.md) | Before launching, after editing task definitions |
| Watch Benchmarks | [watch-benchmarks](watch-benchmarks/SKILL.md) | Full status dashboard for all runs |
| What's Next | [whats-next](whats-next/SKILL.md) | Deciding the highest-value next action |

### Consolidated Guides (`csb/`)

The `csb/` subdirectory groups the same skills by workflow phase for quick
reference. These are summaries — the individual `SKILL.md` files have the
full detail.

| Guide | File | Covers |
|-------|------|--------|
| Pre-Run | [csb/pre-run.md](csb/pre-run.md) | check-infra, validate-tasks, run-benchmark |
| Monitoring | [csb/monitoring.md](csb/monitoring.md) | run-status, watch-benchmarks |
| Triage & Rerun | [csb/triage-rerun.md](csb/triage-rerun.md) | triage-failure, quick-rerun |
| Analysis | [csb/analysis.md](csb/analysis.md) | compare-configs, mcp-audit, ir-analysis, cost-report, evaluate-traces |
| Maintenance | [csb/maintenance.md](csb/maintenance.md) | sync-metadata, reextract-metrics, archive-run, generate-report, whats-next |
| Task Authoring | [csb/task-authoring.md](csb/task-authoring.md) | scaffold-task, score-tasks, benchmark-audit |

## How to Use These Skills

### With Cursor (`.cursor/rules/`)

All CSB skills are already installed as individual `.mdc` rules in
`.cursor/rules/`. Cursor will auto-load them based on file glob matching.
The rules are named to match the skill directories (e.g.,
`.cursor/rules/check-infra.mdc` corresponds to `skills/check-infra/SKILL.md`).

### With Claude Code (`CLAUDE.md`)

Reference skills from your `CLAUDE.md` or `AGENTS.md`:

```markdown
## Skills Reference
See `skills/` for operational runbooks:
- Pre-run checklist: `skills/check-infra/SKILL.md`
- Failure triage: `skills/triage-failure/SKILL.md`
```

Claude Code will read the files when relevant context is needed.

### With Other Agents

Skills are plain markdown — any agent that can read files can use them. Point the agent at the relevant skill file when starting a task:

```
Read skills/mcp-audit/SKILL.md and then run an MCP audit for the latest benchmark run.
```
