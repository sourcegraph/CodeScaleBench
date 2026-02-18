# Deterministic Control Plane

This document describes how to use the **deterministic control plane** in CodeContextBench: a single declarative spec that defines exactly which runs execute, with stable experiment/run/pair IDs and ordering. Same spec + same task source → same manifest every time.

## Rationale

- **Single source of truth**: "What to run" is defined in one place (control plane spec + task list), not scattered across CLI flags and shell logic.
- **Reproducibility**: Experiment ID, run IDs, and pair IDs are derived from invariants (config hash, task set, model, seeds) so re-runs and comparisons are stable.
- **Separation of concerns**: Control plane = *what* to run (task × config × seed matrix). Execution (Harbor, Docker) = *how* it runs.

## Components

| Component | Role |
|-----------|------|
| **Control plane spec** | YAML that defines experiment name, task source, benchmark filter, configs, model, seeds, category. |
| **Task source** | Canonical task list (e.g. `configs/selected_benchmark_tasks.json`). |
| **Manifest generator** | Script that reads spec + task source, sorts tasks deterministically, computes IDs via `lib.matrix.id_generator`, and writes a **run manifest** (JSON). |
| **Runner** | Existing `run_selected_tasks.sh` or a manifest-driven wrapper; executes each run from the manifest so ordering and IDs are fixed. |

## Control plane spec (YAML)

Example: `configs/control_plane_ccb.yaml`

```yaml
# Deterministic control plane for CodeContextBench 2-config runs.
# Same file + same task source → same experiment_id and run list.

experiment_name: ccb_2config
description: "CCB 157 tasks × baseline + sourcegraph_full"
run_category: staging

# Where to get tasks (must have .tasks[].benchmark, .tasks[].task_id, .tasks[].task_dir)
task_source: configs/selected_benchmark_tasks.json

# Optional: limit to one benchmark (e.g. ccb_fix). Omit or empty = all benchmarks.
benchmark_filter: ""

models:
  - anthropic/claude-opus-4-6

mcp_modes:
  - baseline
  - sourcegraph_full

seeds: [0]
```

- **experiment_id** is computed from `experiment_name` + hash of the spec (and optionally task source path), so it is deterministic.
- **run_id** / **pair_id** use the existing `lib.matrix.id_generator` (task_id, model, mcp_mode, seed, experiment_id).

## Determinism

Same spec file + same task source file → same `experiment_id`, same `run_id` and `pair_id` for every run, and same ordering. The only field that changes between invocations is `generated_at` in the manifest.

## Generating the manifest

From the repo root:

```bash
# Generate manifest only (no execution)
python3 scripts/control_plane.py generate --spec configs/control_plane_ccb.yaml --output runs/staging/manifest.json

# Dry-run: print what would be run
python3 scripts/control_plane.py generate --spec configs/control_plane_ccb.yaml --dry-run
```

The manifest JSON looks like:

```json
{
  "experiment_id": "exp_ccb2config_2026-02-18_abc123",
  "experiment_name": "ccb_2config",
  "run_category": "staging",
  "generated_at": "2026-02-18T12:00:00Z",
  "runs": [
    {
      "run_id": "run_baseline_opus_..._seed0_xyz",
      "pair_id": "pair_opus_..._seed0_...",
      "task_id": "...",
      "task_dir": "ccb_design/...",
      "benchmark": "ccb_design",
      "mcp_mode": "baseline",
      "model": "anthropic/claude-opus-4-6",
      "seed": 0
    }
  ],
  "pairs": [ ... ]
}
```

## Using the manifest to drive runs

**Option A – Keep current runner, add optional manifest mode**

- Add a flag to `run_selected_tasks.sh`: e.g. `--manifest runs/staging/<experiment_id>/manifest.json`.
- When `--manifest` is set, the script reads `manifest["runs"]`, iterates in order, and for each run invokes `harbor run --path ...` with the task_dir from the manifest. Output directories can include `run_id` so they are stable.

**Option B – Manifest as input to a thin Python runner**

- A small script (e.g. `scripts/run_from_manifest.py`) that reads the manifest and for each run calls Harbor (or shells out to the same `harbor run` logic), so all execution is manifest-driven.

Either way, the **control plane** is the spec + manifest; the runner is a consumer of the manifest.

## Relation to existing v2 experiment YAMLs

The repo already has a **v2 experiment path** (`lib/config`, `lib/matrix/expander`, `run-eval run -c experiment.yaml`) that uses Harbor’s **registry** and dataset/task_names. That path is well-suited to benchmarks like swebenchpro that are in the registry.

The **control plane layer** described here is complementary:

- For **CCB in-repo tasks** (benchmarks under `benchmarks/ccb_*`), the control plane spec + manifest generator use the same deterministic ID logic (`id_generator`) but drive the **path-based** runner (`harbor run --path`), which does not require a registry.
- You can later unify by having the manifest generator emit an experiment YAML (or RunSpec list) consumable by the v2 runner if CCB is ever registered in Harbor.

## Checklist for a new deterministic run

1. Ensure `configs/selected_benchmark_tasks.json` (or your task source) is up to date.
2. Create or edit a control plane spec (e.g. `configs/control_plane_ccb.yaml`).
3. Run `python3 scripts/control_plane.py generate --spec ... --output ...` to produce the manifest.
4. Run the benchmark using that manifest (e.g. `run_selected_tasks.sh --manifest runs/staging/<exp_id>/manifest.json` or `scripts/run_from_manifest.py ...`).
5. Post-run: `generate_manifest.py`, `generate_eval_report.py`, etc. can key off `experiment_id` and run IDs from the control plane manifest for consistent reporting.

## Files

| File | Purpose |
|------|---------|
| `docs/CONTROL_PLANE.md` | This design and usage. |
| `configs/control_plane_ccb.yaml` | Example control plane spec for CCB 2-config. |
| `scripts/control_plane.py` | Manifest generator: spec + task source → manifest JSON. |
| `lib/matrix/id_generator.py` | Deterministic experiment_id, run_id, pair_id (unchanged). |
