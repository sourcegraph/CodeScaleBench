# CodeScaleBench Benchmarks

275 tasks representing realistic developer work in large, enterprise-scale codebases. Tasks are organized by **developer work type** across 20 source directories. Suite sizes use DOE-driven Neyman-optimal allocation.

Non-canonical tasks are archived in `backups/`. See [`docs/explanations/taxonomy_rationale.md`](../docs/explanations/taxonomy_rationale.md) for the design rationale. See [`docs/TASK_SELECTION.md`](../docs/TASK_SELECTION.md) for selection methodology.

---

## Work Types

| Work Type | Tasks | Source Directories | Repo Scope |
|-----------|------:|-------------------|------------|
| **crossrepo** | 47 | `csb_org_crossrepo` (11), `csb_org_crossrepo_tracing` (11), `csb_org_crossorg` (12), `csb_org_platform` (13) | 18 single, 9 dual, 20 multi |
| **understand** | 44 | `csb_sdlc_understand` (11), `csb_sdlc_design` (11), `csb_org_domain` (11), `csb_org_onboarding` (11) | 36 single, 4 dual, 4 multi |
| **refactor** | 43 | `csb_sdlc_refactor` (18), `csb_org_migration` (25) | 26 single, 2 dual, 15 multi |
| **security** | 39 | `csb_sdlc_secure` (13), `csb_org_security` (13), `csb_org_compliance` (13) | 26 single, 2 dual, 11 multi |
| **feature** | 34 | `csb_sdlc_feature` (23), `csb_org_org` (11) | 24 single, 2 dual, 8 multi |
| **debug** | 26 | `csb_sdlc_debug` (13), `csb_org_incident` (13) | 15 single, 8 dual, 3 multi |
| **fix** | 19 | `csb_sdlc_fix` (19) | 19 single |
| **test** | 12 | `csb_sdlc_test` (12) | 12 single |
| **document** | 11 | `csb_sdlc_document` (11) | 10 single, 1 dual |

The on-disk `csb_sdlc_*` and `csb_org_*` prefixes are legacy naming from the original build phases. All tasks target enterprise-scale codebases; the prefix does not imply a meaningful SDLC/Org distinction. The reporting layer maps directories to work types for analysis.

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

# Run a specific source directory
bash configs/run_selected_tasks.sh --benchmark csb_sdlc_fix

# Single task
harbor run --path benchmarks/csb_sdlc_feature/servo-scrollend-event-feat-001 \
  --agent-import-path agents.claude_baseline_agent:BaselineClaudeCodeAgent \
  --model anthropic/claude-haiku-4-5-20251001 \
  -n 1
```

See [`docs/reference/CONFIGS.md`](../docs/reference/CONFIGS.md) for the full tool-by-tool breakdown of each config.
