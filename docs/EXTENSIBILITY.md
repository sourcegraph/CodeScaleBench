# Extensibility Guide

This guide defines the minimum changes required to safely extend
CodeContextBench.

## 1) Add New Benchmark Tasks or Suites

1. Add task directories under `benchmarks/<suite>/<task>/`.
2. Ensure each task has:
   - `task.toml`
   - `instruction.md`
   - verifier (`tests/test.sh` or suite-equivalent)
3. Register tasks in `configs/selected_benchmark_tasks.json`.
4. Run preflight:
   ```bash
   python3 scripts/validate_tasks_preflight.py --suite <suite>
   ```
5. Add/update the suite runner in `configs/<suite>_2config.sh`.

## 2) Add New Agent Variant / Harness + Model Combo

For Harbor runs, model and agent wiring are typically set in runner scripts:

- agent path: `--agent-import-path`
- model: `--model`

Recommended pattern:

1. Keep runner defaults stable.
2. Add explicit CLI overrides (`--model`, optionally `--agent-path`) for experiments.
3. Keep output directory naming deterministic (`<suite>_<model_short>_<timestamp>`).

For cross-agent comparison scaffolding, see:

- `configs/multi_harness_compare.sh`

## 3) Add New Code Intelligence Config (e.g., GitHub MCP)

Use `configs/eval_matrix.json` as the first change.

1. Add config entry in `config_definitions`.
2. Add config name to `supported_configs`.
3. Optionally include in `official_default_configs` only after validation.
4. Update relevant runner scripts to pass the new `BASELINE_MCP_TYPE`.
5. Update the external agent harness implementation to recognize the mode.

## 4) Keep Analysis and Curation Stable

After introducing new configs/suites:

```bash
python3 scripts/generate_manifest.py --require-triage --fail-on-unknown-prefix
python3 scripts/validate_official_integrity.py --runs-dir runs/official --check-mcp-trace-health
python3 scripts/audit_traces.py --json
```

If MCP-enabled failed tasks have zero MCP calls, quarantine before analysis:

```bash
python3 scripts/quarantine_invalid_tasks.py --execute
```

## 5) Documentation Drift Guard

Run:

```bash
python3 scripts/docs_consistency_check.py
```

This validates that core docs do not reference missing scripts/configs.

## 6) Task Environment Variants

When adding benchmark environment variants, keep canonical task definitions intact:

1. Keep `environment/Dockerfile` as the canonical default.
2. Add variant files with explicit names (for example `Dockerfile.isolated`,
   `Dockerfile.sg_only`).
3. Document variant intent and caveats in a per-suite `VARIANTS.md`
   (for example under `benchmarks/ccb_docgen/`).
4. Treat variant runs as separate studies in reporting and curation.
