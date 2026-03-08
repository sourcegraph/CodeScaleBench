# CodeScaleBench Benchmarks

This directory contains SDLC-aligned suites plus Org org-scale retrieval suites. The canonical task set is defined by [`unified_benchmark_manifest.json`](../configs/unified_benchmark_manifest.json) (275 tasks across 20 suites: 131 SDLC + 144 Org). Suite sizes use DOE-driven Neyman-optimal allocation to maximize statistical power per suite.

Non-canonical tasks are archived in `backups/`.

See [`docs/TASK_SELECTION.md`](../docs/TASK_SELECTION.md) for selection methodology.

---

## SDLC Suite Overview

| Suite | SDLC Phase | Tasks | Description |
|-------|-----------|------:|-------------|
| `csb_sdlc_feature` | Feature Implementation | 23 | New features, interface implementation, big-code features |
| `csb_sdlc_fix` | Bug Repair | 19 | Diagnosing and fixing real bugs across production codebases |
| `csb_sdlc_refactor` | Cross-File Refactoring | 18 | Cross-file refactoring, enterprise dependency refactoring, rename refactoring |
| `csb_sdlc_debug` | Debugging & Investigation | 13 | Root cause tracing, fault localization, provenance |
| `csb_sdlc_secure` | Security & Compliance | 13 | CVE analysis, reachability, governance, access control |
| `csb_sdlc_test` | Testing & QA | 12 | Code review, performance testing, code search validation, test generation |
| `csb_sdlc_design` | Architecture & Design | 11 | Architecture analysis, dependency graphs, change impact |
| `csb_sdlc_document` | Documentation | 11 | API references, architecture docs, migration guides, runbooks |
| `csb_sdlc_understand` | Requirements & Discovery | 11 | Codebase comprehension, onboarding, Q&A, knowledge recovery |
| **Total** | | **131** | |

---

## CodeScaleBench-Org Suite Overview

These suites measure cross-repo discovery, tracing, and org-scale code intelligence use cases.

| Suite | Tasks | Description |
|-------|------:|-------------|
| `csb_org_migration` | 25 | Framework and platform migrations across repos |
| `csb_org_compliance` | 13 | Compliance, audit, and provenance workflows |
| `csb_org_incident` | 13 | Incident debugging across services and repos |
| `csb_org_platform` | 13 | Platform/devtools and tribal-knowledge discovery |
| `csb_org_security` | 13 | Vulnerability remediation and security analysis at org scale |
| `csb_org_crossorg` | 12 | Cross-org discovery and authoritative repo identification |
| `csb_org_crossrepo` | 11 | Cross-repo search, dependency discovery, impact analysis |
| `csb_org_crossrepo_tracing` | 11 | Cross-repo dependency tracing and symbol resolution |
| `csb_org_domain` | 11 | Domain-specific lineage and analysis workflows |
| `csb_org_onboarding` | 11 | Onboarding, architecture comprehension, API discovery |
| `csb_org_org` | 11 | Org-wide coding correctness tasks requiring broad context |
| **Total** | **144** | |

For suite taxonomy, authoring, and oracle evaluation details, see [`docs/ORG_TASKS.md`](../docs/ORG_TASKS.md).

---

## Task Directory Structure

Each task follows this layout:

```
{task-name}/
  task.toml          # Task metadata: id, language, difficulty, timeouts
  instruction.md     # Agent instructions (what to do)
  environment/       # Dockerfile and build context
  tests/             # test.sh, ground truth, eval scripts
  solution/          # Reference solution (optional)
```

---

## Running Benchmarks

```bash
# Run all 275 canonical tasks across 2 configs
bash configs/run_selected_tasks.sh

# Run a single SDLC phase
bash configs/run_selected_tasks.sh --benchmark csb_sdlc_fix

# Single task
harbor run --path benchmarks/csb_sdlc_feature/servo-scrollend-event-feat-001 \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

See [`docs/CONFIGS.md`](../docs/CONFIGS.md) for the full tool-by-tool breakdown of each config.
